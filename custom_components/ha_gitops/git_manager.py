"""Git-backend for ha_gitops.

Public API matches docs/ha-gitops-proj-spec.md §8. Implementation runs the
`git` CLI through `asyncio.create_subprocess_exec` so the HA event loop is
never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .const import (
    CO_AUTHOR_TRAILER,
    GITIGNORE_MARKER,
    GITIGNORE_TEMPLATE,
    SECRETS_FILENAMES,
    SyncStatus,
)

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _read_integration_version() -> str:
    """Return the integration version from manifest.json (cached)."""
    manifest = Path(__file__).resolve().parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("version", "0.0.0"))
    except (OSError, ValueError):
        return "0.0.0"


class GitError(Exception):
    """Raised when a git operation fails or the repository is in a bad state."""


class GitAuthError(GitError):
    """Raised when SSH/HTTPS authentication fails."""


class GitConflictError(GitError):
    """Raised when a fast-forward merge is impossible (diverged branches)."""


@dataclass(slots=True, frozen=True)
class GitResult:
    """Outcome of a git operation reported back to entities."""

    ok: bool
    message: str
    changed_files: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class FileChange:
    """Single file change as reported by `git diff --name-status`."""

    status: str  # 'M' | 'A' | 'D' | 'R' | '?'
    name: str


@dataclass(slots=True, frozen=True)
class CommitInfo:
    """Minimal commit information surfaced to sensors."""

    short_hash: str
    full_hash: str
    message: str
    author: str
    timestamp: str  # ISO-8601


class GitManager:
    """Single entry point for every git interaction performed by the integration.

    The public API is stable; see docs/ha-gitops-proj-spec.md §8. Internal
    helpers (_run_git, _build_ssh_env, _get_yaml_files, _build_commit_message)
    may evolve freely — including a future migration from subprocess to
    GitPython.
    """

    def __init__(
        self,
        config_dir: Path | str,
        repo_url: str,
        branch: str,
        ssh_key_path: Path | str,
        author_name: str,
        author_email: str,
    ) -> None:
        self._config_dir = Path(config_dir)
        self._repo_url = repo_url
        self._branch = branch
        self._ssh_key_path = Path(ssh_key_path)
        self._author_name = author_name
        self._author_email = author_email

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def branch(self) -> str:
        return self._branch

    async def initialize(self) -> None:
        """Initialize the repository: git init / remote / .gitignore / first fetch.

        Idempotent: safe to call on every HA start. Network failures during the
        initial fetch are logged at WARNING and do not block setup so the
        integration stays usable for inspection even when the remote is down.
        """
        await asyncio.to_thread(self._config_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            self._ssh_key_path.parent.mkdir, parents=True, exist_ok=True
        )

        if not await asyncio.to_thread((self._config_dir / ".git").is_dir):
            await self._run_git("init", "-b", self._branch)

        await self._ensure_remote()

        fetch_ok = True
        try:
            await self._run_git("fetch", "origin", "--quiet")
        except GitError as exc:
            _LOGGER.warning("ha_gitops: initial fetch skipped: %s", exc)
            fetch_ok = False

        if fetch_ok:
            rc, _, _ = await self._run_git(
                "rev-parse", "--verify", "HEAD", check=False
            )
            if rc != 0:
                rc_remote, _, _ = await self._run_git(
                    "rev-parse",
                    "--verify",
                    f"origin/{self._branch}",
                    check=False,
                )
                if rc_remote == 0:
                    await self._run_git(
                        "checkout",
                        "-b",
                        self._branch,
                        f"origin/{self._branch}",
                    )

        await self._ensure_gitignore()

    async def push(self) -> GitResult:
        """Stage YAML files (secrets-guarded), commit if there are changes, push.

        Per spec §7.1, this is a single atomic action from the user's
        perspective: it commits any pending YAML edits and pushes; if there
        is nothing to commit but a previous local commit failed to reach the
        remote, it pushes that commit; if there is genuinely nothing to do,
        it returns a clean no-op.
        """
        await self._require_initialized()

        files = await self._stage_yaml_files()
        committed_changes: tuple[str, ...] = ()
        if files:
            message = self._build_commit_message(files)
            await self._run_git(*self._author_args(), "commit", "-m", message)
            committed_changes = tuple(f.name for f in files)

        rc, _, _ = await self._run_git("rev-parse", "--verify", "HEAD", check=False)
        if rc != 0:
            return GitResult(ok=True, message="Nothing to push")

        rc_remote, _, _ = await self._run_git(
            "rev-parse", "--verify", f"origin/{self._branch}", check=False
        )
        if rc_remote != 0:
            try:
                await self._run_git("push", "--set-upstream", "origin", self._branch)
            except GitError as exc:
                raise self._classify_push_error(exc) from exc
            return GitResult(
                ok=True, message="Initial push", changed_files=committed_changes
            )

        _, ahead_str, _ = await self._run_git(
            "rev-list", "--count", f"origin/{self._branch}..HEAD"
        )
        if int(ahead_str.strip() or "0") == 0:
            return GitResult(ok=True, message="Nothing to push")

        try:
            await self._run_git("push", "origin", self._branch)
        except GitError as exc:
            raise self._classify_push_error(exc) from exc
        return GitResult(ok=True, message="Pushed", changed_files=committed_changes)

    async def pull(self) -> GitResult:
        """Fetch and fast-forward only — never auto-merge or rebase."""
        await self._require_initialized()
        await self._run_git("fetch", "origin", "--quiet")

        rc, _, _ = await self._run_git(
            "rev-parse", "--verify", f"origin/{self._branch}", check=False
        )
        if rc != 0:
            raise GitError(
                f"Remote branch origin/{self._branch} not found"
            )

        rc_head, old_head_out, _ = await self._run_git(
            "rev-parse", "HEAD", check=False
        )
        old_head = old_head_out.strip() if rc_head == 0 else ""

        rc, stdout, stderr = await self._run_git(
            "merge", "--ff-only", f"origin/{self._branch}", check=False
        )
        if rc != 0:
            raise GitConflictError(
                f"Fast-forward merge refused (diverged history?): "
                f"{stderr.strip() or stdout.strip()}"
            )

        _, new_head_out, _ = await self._run_git("rev-parse", "HEAD")
        new_head = new_head_out.strip()

        changed: tuple[str, ...] = ()
        if old_head and old_head != new_head:
            _, diff_out, _ = await self._run_git(
                "diff", "--name-only", old_head, new_head
            )
            changed = tuple(line for line in diff_out.splitlines() if line)

        return GitResult(
            ok=True,
            message=stdout.strip() or "Pulled",
            changed_files=changed,
        )

    async def fetch(self) -> GitResult:
        """Run `git fetch origin` and report success/failure as GitResult."""
        await self._require_initialized()
        await self._run_git("fetch", "origin", "--quiet")
        return GitResult(ok=True, message="Fetched")

    async def commit(self, message: str | None = None) -> GitResult:
        """Stage YAML files and create a commit without pushing."""
        await self._require_initialized()
        files = await self._stage_yaml_files()
        if not files:
            return GitResult(ok=True, message="Nothing to commit")

        msg = message or self._build_commit_message(files)
        await self._run_git(*self._author_args(), "commit", "-m", msg)
        return GitResult(
            ok=True,
            message="Committed",
            changed_files=tuple(f.name for f in files),
        )

    async def get_status(self) -> SyncStatus:
        """Return current sync status per spec §8.1.

        Performs a soft `git fetch origin` first (network errors are downgraded
        to a WARNING), then reasons about local vs remote tips using
        `rev-parse` and `merge-base`. Returns UNKNOWN if the repository is
        not initialized or has no commits yet, or if the remote branch is
        unreachable and we have nothing to compare against.
        """
        if not await asyncio.to_thread((self._config_dir / ".git").is_dir):
            return SyncStatus.UNKNOWN

        try:
            await self._run_git("fetch", "origin", "--quiet")
        except GitError as exc:
            _LOGGER.warning("ha_gitops: status fetch failed: %s", exc)

        rc, _, _ = await self._run_git(
            "rev-parse", "--verify", "HEAD", check=False
        )
        if rc != 0:
            return SyncStatus.UNKNOWN

        _, porcelain, _ = await self._run_git("status", "--porcelain")
        if porcelain.strip():
            return SyncStatus.MODIFIED

        rc, local_out, _ = await self._run_git("rev-parse", "HEAD", check=False)
        if rc != 0:
            return SyncStatus.UNKNOWN

        rc, remote_out, _ = await self._run_git(
            "rev-parse", "--verify", f"origin/{self._branch}", check=False
        )
        if rc != 0:
            return SyncStatus.UNKNOWN

        local_h = local_out.strip()
        remote_h = remote_out.strip()
        if local_h == remote_h:
            return SyncStatus.CLEAN

        rc, base_out, _ = await self._run_git(
            "merge-base", "HEAD", f"origin/{self._branch}", check=False
        )
        if rc != 0:
            return SyncStatus.DIVERGED

        base_h = base_out.strip()
        if base_h == remote_h:
            return SyncStatus.AHEAD
        if base_h == local_h:
            return SyncStatus.BEHIND
        return SyncStatus.DIVERGED

    async def get_local_commit(self) -> CommitInfo | None:
        return None

    async def get_remote_commit(self) -> CommitInfo | None:
        return None

    async def get_changed_files(self) -> list[FileChange]:
        """Return staged + unstaged tracked YAML changes (root-level)."""
        if not await asyncio.to_thread((self._config_dir / ".git").is_dir):
            return []

        rc, out, _ = await self._run_git(
            "status", "--porcelain=v1", check=False
        )
        if rc != 0:
            return []

        result: list[FileChange] = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            staged_code = line[0]
            unstaged_code = line[1]
            name = line[3:].strip()
            if not name.endswith(".yaml") or "/" in name:
                continue
            if name in SECRETS_FILENAMES or name.endswith(".secrets.yaml"):
                continue
            primary = staged_code if staged_code != " " else unstaged_code
            mapped = primary if primary in {"M", "A", "D", "R"} else "?"
            result.append(FileChange(status=mapped, name=name))
        return result

    async def generate_ssh_key(self) -> str:
        raise NotImplementedError

    async def test_connection(self) -> bool:
        raise NotImplementedError

    async def _run_git(
        self, *args: str, check: bool = True
    ) -> tuple[int, str, str]:
        """Run `git <args>` with the integration's SSH env.

        Returns (returncode, stdout, stderr). When `check=True` (default) and
        the command exits non-zero, raises `GitError` with a sanitized message.
        """
        env = os.environ.copy()
        env.update(self._build_ssh_env())
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(self._config_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        rc = proc.returncode or 0
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        _LOGGER.debug(
            "git %s -> rc=%s", " ".join(shlex.quote(a) for a in args), rc
        )
        if check and rc != 0:
            subcmd = next((a for a in args if not a.startswith("-")), "")
            raise GitError(
                f"git {subcmd} failed (exit {rc}): {stderr.strip() or stdout.strip()}"
            )
        return rc, stdout, stderr

    async def _require_initialized(self) -> None:
        """Raise GitError if `.git/` is missing in the configured working tree."""
        if not await asyncio.to_thread((self._config_dir / ".git").is_dir):
            raise GitError(
                "Repository not initialized. Call initialize() first."
            )

    async def _stage_yaml_files(self) -> list[FileChange]:
        """Stage root-level YAML files (excluding secrets) and return staged FileChanges.

        Performs the secrets panic guard from spec §10 / security.mdc: if any
        secrets-like file ends up staged (e.g. user removed it from
        .gitignore and force-added it), it is unstaged and GitError is
        raised so the push/commit aborts loud and clear.
        """
        yaml_files = self._get_yaml_files()
        if yaml_files:
            await self._run_git("add", "--", *yaml_files)

        rc, ls_out, _ = await self._run_git(
            "ls-files", "--", "*.yaml", check=False
        )
        if rc == 0:
            tracked = [
                f
                for f in (line.strip() for line in ls_out.splitlines())
                if f
                and "/" not in f
                and f not in SECRETS_FILENAMES
                and not f.endswith(".secrets.yaml")
            ]
            if tracked:
                await self._run_git(
                    "add", "--update", "--", *tracked, check=False
                )

        rc, staged_out, _ = await self._run_git(
            "diff", "--cached", "--name-only", check=False
        )
        if rc != 0:
            raise GitError("failed to inspect staged files")

        staged = [s for s in staged_out.splitlines() if s.strip()]
        leaked = [
            f
            for f in staged
            if f in SECRETS_FILENAMES or f.endswith(".secrets.yaml")
        ]
        if leaked:
            for f in leaked:
                await self._run_git("reset", "HEAD", "--", f, check=False)
            raise GitError(
                "Refused to push: secrets file(s) detected in staged area: "
                f"{', '.join(leaked)}"
            )

        return await self._get_staged_changes()

    async def _get_staged_changes(self) -> list[FileChange]:
        """Return staged changes as FileChange list, parsed from diff --name-status."""
        rc, out, _ = await self._run_git(
            "diff", "--cached", "--name-status", check=False
        )
        if rc != 0:
            return []
        result: list[FileChange] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status = parts[0].strip()[:1]
            result.append(FileChange(status=status, name=parts[1].strip()))
        return result

    @staticmethod
    def _classify_push_error(exc: GitError) -> GitError:
        """Translate raw git push errors into a more actionable message."""
        msg = str(exc).lower()
        if "rejected" in msg or "non-fast-forward" in msg or "fetch first" in msg:
            return GitError(
                "Push rejected: remote has new changes. Pull first."
            )
        return exc

    async def _ensure_remote(self) -> None:
        """Make sure `origin` points at the configured repo URL."""
        rc, stdout, _ = await self._run_git(
            "remote", "get-url", "origin", check=False
        )
        if rc != 0:
            await self._run_git("remote", "add", "origin", self._repo_url)
            return
        if stdout.strip() != self._repo_url:
            await self._run_git("remote", "set-url", "origin", self._repo_url)

    async def _ensure_gitignore(self) -> None:
        """Create or append the ha-gitops managed block in .gitignore."""
        target = self._config_dir / ".gitignore"

        def _apply() -> None:
            if not target.exists():
                target.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
                return
            existing = target.read_text(encoding="utf-8")
            if GITIGNORE_MARKER in existing:
                return
            separator = "" if existing.endswith("\n") else "\n"
            target.write_text(
                existing + separator + "\n" + GITIGNORE_TEMPLATE, encoding="utf-8"
            )

        await asyncio.to_thread(_apply)

    def _build_ssh_env(self) -> dict[str, str]:
        """Return env dict with GIT_SSH_COMMAND configured for our key/known_hosts."""
        known_hosts = self._ssh_key_path.parent / "known_hosts"
        ssh_cmd = (
            f"ssh -i {self._ssh_key_path} "
            f"-o UserKnownHostsFile={known_hosts} "
            "-o StrictHostKeyChecking=accept-new "
            "-o IdentitiesOnly=yes"
        )
        return {"GIT_SSH_COMMAND": ssh_cmd}

    def _get_yaml_files(self) -> list[str]:
        """Return root-level *.yaml files, excluding secrets per security policy."""
        result: list[str] = []
        for path in sorted(self._config_dir.glob("*.yaml")):
            name = path.name
            if name in SECRETS_FILENAMES or name.endswith(".secrets.yaml"):
                continue
            result.append(name)
        return result

    def _author_args(self) -> tuple[str, ...]:
        """Pre-built `-c user.name=... -c user.email=...` args for commits."""
        return (
            "-c",
            f"user.name={self._author_name}",
            "-c",
            f"user.email={self._author_email}",
        )

    def _build_commit_message(self, changed_files: list[FileChange]) -> str:
        """Build the adaptive commit subject + body per spec §8.3."""
        names = [f.name for f in changed_files]
        if len(names) == 1:
            subject = f"Update: {names[0]}"
        elif len(names) <= 3:
            subject = f"Update: {', '.join(names)}"
        else:
            subject = (
                f"Update: {names[0]}, {names[1]} (+{len(names) - 2} more)"
            )

        file_lines = "\n".join(f"  {f.status}  {f.name}" for f in changed_files)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        version = _read_integration_version()

        return (
            f"{subject}\n\n"
            f"Changed files ({len(changed_files)}):\n{file_lines}\n\n"
            f"Timestamp: {timestamp}\n"
            f"Pushed via: HA GitOps v{version}\n\n"
            f"{CO_AUTHOR_TRAILER}"
        )
