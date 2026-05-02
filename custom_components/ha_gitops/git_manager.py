"""Git-backend for ha_gitops.

Public API matches docs/ha-gitops-proj-spec.md §8. Implementation runs the
`git` CLI through `asyncio.create_subprocess_exec` so the HA event loop is
never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from .const import (
    CO_AUTHOR_TRAILER,
    GITIGNORE_MARKER,
    GITIGNORE_TEMPLATE,
    SECRETS_FILENAMES,
    SyncStatus,
)

_LOGGER = logging.getLogger(__name__)


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
        await self._ensure_gitignore()

        try:
            await self._run_git("fetch", "origin", "--quiet")
        except GitError as exc:
            _LOGGER.warning("ha_gitops: initial fetch skipped: %s", exc)
            return

        rc, _, _ = await self._run_git("rev-parse", "--verify", "HEAD", check=False)
        if rc != 0:
            rc_remote, _, _ = await self._run_git(
                "rev-parse",
                "--verify",
                f"origin/{self._branch}",
                check=False,
            )
            if rc_remote == 0:
                await self._run_git(
                    "checkout", "-b", self._branch, f"origin/{self._branch}"
                )

    async def push(self) -> GitResult:
        raise NotImplementedError

    async def pull(self) -> GitResult:
        raise NotImplementedError

    async def fetch(self) -> GitResult:
        raise NotImplementedError

    async def commit(self, message: str | None = None) -> GitResult:
        raise NotImplementedError

    async def get_status(self) -> SyncStatus:
        return SyncStatus.UNKNOWN

    async def get_local_commit(self) -> CommitInfo | None:
        return None

    async def get_remote_commit(self) -> CommitInfo | None:
        return None

    async def get_changed_files(self) -> list[FileChange]:
        return []

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

    def _build_commit_message(
        self, changed_files: list[FileChange], version: str
    ) -> str:
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

        from datetime import datetime

        file_lines = "\n".join(f"  {f.status}  {f.name}" for f in changed_files)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        return (
            f"{subject}\n\n"
            f"Changed files ({len(changed_files)}):\n{file_lines}\n\n"
            f"Timestamp: {timestamp}\n"
            f"Pushed via: HA GitOps v{version}\n\n"
            f"{CO_AUTHOR_TRAILER}"
        )
