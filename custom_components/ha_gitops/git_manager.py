"""Git-backend for ha_gitops.

MVP scaffolding: public API matches docs/ha-gitops-proj-spec.md §8. Method bodies
are intentionally minimal so the integration can load and tests can import the
module. Real implementation lands in the next iteration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .const import SECRETS_FILENAMES, SyncStatus

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
        """Initialize the repository (git init, remote, .gitignore) if needed."""
        _LOGGER.info("ha_gitops initialize() — scaffolding, not implemented yet")

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
