"""Tests for GitManager SSH key generation and remote connectivity check."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from custom_components.ha_gitops.git_manager import GitError, GitManager

pytestmark = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None,
    reason="ssh-keygen not available",
)


async def test_generate_ssh_key_creates_ed25519_pair(
    git_manager: GitManager,
    config_dir: Path,
) -> None:
    pub = await git_manager.generate_ssh_key()
    assert pub.startswith("ssh-ed25519")
    priv = git_manager.ssh_key_path
    assert priv.is_file()
    assert (priv.parent / f"{priv.name}.pub").is_file()
    mode = priv.stat().st_mode & 0o777
    assert mode == 0o600


async def test_generate_ssh_key_refuses_existing_nonempty_key(
    git_manager: GitManager,
) -> None:
    await git_manager.generate_ssh_key()
    with pytest.raises(GitError, match="already exists"):
        await git_manager.generate_ssh_key()


async def test_test_connection_true_after_initialize(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    assert await git_manager_seeded.test_connection() is True


async def test_test_connection_false_without_git(
    config_dir: Path,
    tmp_path: Path,
) -> None:
    manager = GitManager(
        config_dir=config_dir,
        repo_url=f"file://{tmp_path}/nope.git",
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="T",
        author_email="t@t",
    )
    assert await manager.test_connection() is False
