"""Tests for GitManager.get_status — full SyncStatus algorithm coverage."""

from __future__ import annotations

from pathlib import Path

from custom_components.ha_gitops.const import SyncStatus
from custom_components.ha_gitops.git_manager import GitManager

from .conftest import make_local_commit, push_remote_commit


async def test_status_unknown_when_not_initialized(
    git_manager: GitManager,
) -> None:
    assert await git_manager.get_status() is SyncStatus.UNKNOWN


async def test_status_unknown_for_empty_repo(git_manager: GitManager, config_dir: Path) -> None:
    """git init was done but nothing was ever committed locally or pushed."""
    await git_manager.initialize()
    assert await git_manager.get_status() is SyncStatus.UNKNOWN


async def test_status_clean_after_initial_checkout(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    assert await git_manager_seeded.get_status() is SyncStatus.CLEAN


async def test_status_modified_when_tracked_file_changes(
    git_manager_seeded: GitManager, config_dir: Path
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "automations.yaml").write_text("- new line\n", encoding="utf-8")
    assert await git_manager_seeded.get_status() is SyncStatus.MODIFIED


async def test_status_modified_when_new_yaml_added(
    git_manager_seeded: GitManager, config_dir: Path
) -> None:
    """Untracked yaml file (not in .gitignore) should surface as MODIFIED."""
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("turn_on: noop\n", encoding="utf-8")
    assert await git_manager_seeded.get_status() is SyncStatus.MODIFIED


async def test_status_ahead_after_local_commit(
    git_manager_seeded: GitManager, config_dir: Path
) -> None:
    await git_manager_seeded.initialize()
    make_local_commit(config_dir, filename="scripts.yaml", content="local: true")
    assert await git_manager_seeded.get_status() is SyncStatus.AHEAD


async def test_status_behind_when_remote_advances(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    push_remote_commit(seeded_remote, tmp_path / "third_party")

    assert await git_manager_seeded.get_status() is SyncStatus.BEHIND


async def test_status_diverged_when_both_sides_advance(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    make_local_commit(config_dir, filename="local_only.yaml", content="local: true")
    push_remote_commit(seeded_remote, tmp_path / "third_party", filename="remote_only.yaml")

    assert await git_manager_seeded.get_status() is SyncStatus.DIVERGED


async def test_status_unknown_when_remote_unreachable(config_dir: Path, tmp_path: Path) -> None:
    """No HEAD locally + unreachable remote → UNKNOWN, not ERROR."""
    manager = GitManager(
        config_dir=config_dir,
        repo_url=f"file://{tmp_path}/missing.git",
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )
    await manager.initialize()
    assert await manager.get_status() is SyncStatus.UNKNOWN
