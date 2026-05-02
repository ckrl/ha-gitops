"""Shared fixtures for ha_gitops tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custom_components.ha_gitops.git_manager import GitManager


@pytest.fixture
def bare_remote(tmp_path: Path) -> str:
    """Create a bare git repository in tmp_path and return a file:// URL.

    Lets us exercise GitManager against a real local remote without network
    or SSH, per .cursor/rules/testing.mdc.
    """
    bare = tmp_path / "remote.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    return f"file://{bare}"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Temporary HA config directory used as the GitManager working tree."""
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def git_manager(config_dir: Path, bare_remote: str) -> GitManager:
    """Construct a GitManager pointing at the local bare remote."""
    return GitManager(
        config_dir=config_dir,
        repo_url=bare_remote,
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )
