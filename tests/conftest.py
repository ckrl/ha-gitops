"""Shared fixtures for ha_gitops tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custom_components.ha_gitops.git_manager import GitManager


def _git(cwd: Path, *args: str) -> str:
    """Helper: run git in cwd and return stdout, raising on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


@pytest.fixture
def bare_remote(tmp_path: Path) -> str:
    """Create an empty bare git repository and return its file:// URL.

    Using a real local remote (not mocked subprocess) lets us exercise the
    full GitManager surface area, per .cursor/rules/testing.mdc.
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
def seeded_remote(tmp_path: Path) -> str:
    """Bare remote that already has an initial commit on `main`."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "seed@example.com")
    _git(seed, "config", "user.name", "Seeder")
    (seed / "automations.yaml").write_text("[]\n", encoding="utf-8")
    _git(seed, "add", "automations.yaml")
    _git(seed, "commit", "-m", "Initial config")
    _git(seed, "remote", "add", "origin", f"file://{bare}")
    _git(seed, "push", "origin", "main")
    return f"file://{bare}"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Temporary HA config directory used as the GitManager working tree."""
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def git_manager(config_dir: Path, bare_remote: str) -> GitManager:
    """GitManager pointing at an empty local bare remote."""
    return GitManager(
        config_dir=config_dir,
        repo_url=bare_remote,
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )


@pytest.fixture
def git_manager_seeded(config_dir: Path, seeded_remote: str) -> GitManager:
    """GitManager pointing at a remote that already has commits."""
    return GitManager(
        config_dir=config_dir,
        repo_url=seeded_remote,
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )
