"""Tests for GitManager inspection snapshot and commit metadata."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from custom_components.ha_gitops.const import SyncStatus
from custom_components.ha_gitops.git_manager import GitManager


async def test_get_local_commit_returns_metadata_after_init(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    info = await git_manager_seeded.get_local_commit()
    assert info is not None
    assert len(info.short_hash) >= 7
    assert info.full_hash.startswith(info.short_hash)
    assert info.message


async def test_get_remote_commit_matches_origin_after_init(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    local = await git_manager_seeded.get_local_commit()
    remote = await git_manager_seeded.get_remote_commit()
    assert local is not None and remote is not None
    assert local.full_hash == remote.full_hash


async def test_inspection_snapshot_is_cached_within_lock(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    first = await git_manager_seeded.async_get_inspection_snapshot()
    second = await git_manager_seeded.async_get_inspection_snapshot()
    assert first is second
    assert first.status is SyncStatus.CLEAN


async def test_inspection_snapshot_invalidated_after_fetch(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    first = await git_manager_seeded.async_get_inspection_snapshot()
    await git_manager_seeded.fetch()
    second = await git_manager_seeded.async_get_inspection_snapshot()
    assert first is not second


async def test_last_operation_recorded_after_fetch(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    assert git_manager_seeded.last_operation is None
    await git_manager_seeded.fetch()
    assert git_manager_seeded.last_operation == "fetch"
    assert git_manager_seeded.last_operation_at is not None
    assert git_manager_seeded.last_sync_at is not None


async def test_changed_files_in_snapshot(
    git_manager_seeded: GitManager, config_dir: Path
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "automations.yaml").write_text("- changed: true\n", encoding="utf-8")
    snap = await git_manager_seeded.async_get_inspection_snapshot()
    assert snap.status is SyncStatus.MODIFIED
    assert len(snap.changed) >= 1
    names = {c.name for c in snap.changed}
    assert "automations.yaml" in names


async def test_local_commit_sensor_reads_short_hash(
    git_manager_seeded: GitManager,
) -> None:
    from custom_components.ha_gitops.sensor import HaGitopsLocalCommitSensor

    await git_manager_seeded.initialize()
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.title = "T"
    sensor = HaGitopsLocalCommitSensor(entry, git_manager_seeded, 300)
    await sensor.async_update()
    assert sensor.native_value is not None
    assert sensor.native_value != "unknown"
    assert "full_hash" in sensor.extra_state_attributes
