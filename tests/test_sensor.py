"""Unit tests for the ha_gitops sync-status sensor.

Architecture: docs/architecture.md §6.2 (Status sensor) and §7.3 (states table).

These tests exercise the sensor entity in isolation with a MagicMock
GitManager — fast, no HA event loop required. End-to-end registration
through Home Assistant is covered by tests/test_setup.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import STATE_UNKNOWN, EntityCategory

from custom_components.ha_gitops.const import DEFAULT_SCAN_INTERVAL, DOMAIN, SyncStatus
from custom_components.ha_gitops.git_manager import CommitInfo, FileChange, InspectionSnapshot
from custom_components.ha_gitops.sensor import (
    HaGitopsChangedFilesSensor,
    HaGitopsLastSyncSensor,
    HaGitopsLocalCommitSensor,
    HaGitopsRemoteCommitSensor,
    HaGitopsStatusSensor,
)


def _mock_config_entry(entry_id: str = "test_entry_id") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "HA GitOps"
    return entry


def _snapshot(
    *,
    status: SyncStatus = SyncStatus.CLEAN,
    local: CommitInfo | None = None,
    remote: CommitInfo | None = None,
    changed: tuple[FileChange, ...] = (),
) -> InspectionSnapshot:
    return InspectionSnapshot(
        status=status,
        local=local,
        remote=remote,
        changed=changed,
    )


def _make_sensor(
    *,
    status: SyncStatus = SyncStatus.CLEAN,
    raises: Exception | None = None,
    scan_interval: int = DEFAULT_SCAN_INTERVAL,
    entry_id: str = "test_entry_id",
    snap: InspectionSnapshot | None = None,
) -> tuple[HaGitopsStatusSensor, MagicMock]:
    manager = MagicMock()
    if raises is not None:
        manager.async_get_inspection_snapshot = AsyncMock(side_effect=raises)
    else:
        manager.async_get_inspection_snapshot = AsyncMock(
            return_value=snap or _snapshot(status=status)
        )
    manager.last_operation = None
    manager.last_operation_at = None
    manager.last_sync_at = None
    entry = _mock_config_entry(entry_id)
    return HaGitopsStatusSensor(entry, manager, scan_interval), manager


async def test_sensor_initial_state_is_unknown() -> None:
    sensor, _ = _make_sensor()
    assert sensor.native_value == SyncStatus.UNKNOWN.value


async def test_sensor_metadata_matches_spec() -> None:
    sensor, _ = _make_sensor(entry_id="e1")
    assert sensor.unique_id == "e1_sync_status"
    assert sensor.name == "Sync status"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.icon == "mdi:source-branch"
    assert sensor.scan_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    assert sensor.device_info is not None
    assert (DOMAIN, "e1") in sensor.device_info["identifiers"]


async def test_sensor_updates_to_clean_after_async_update() -> None:
    sensor, manager = _make_sensor(status=SyncStatus.CLEAN)
    await sensor.async_update()
    assert sensor.native_value == SyncStatus.CLEAN.value
    assert sensor.extra_state_attributes["last_error"] is None
    manager.async_get_inspection_snapshot.assert_awaited_once()


async def test_sensor_propagates_each_status_value() -> None:
    """Every SyncStatus emitted by GitManager surfaces as the native value."""
    for status in SyncStatus:
        snap = _snapshot(status=status)
        sensor, _ = _make_sensor(snap=snap)
        await sensor.async_update()
        assert sensor.native_value == status.value


async def test_sensor_handles_get_status_exception() -> None:
    sensor, _ = _make_sensor(raises=RuntimeError("boom"))
    await sensor.async_update()
    assert sensor.native_value == SyncStatus.ERROR.value
    assert sensor.extra_state_attributes["last_error"] == "boom"


async def test_sensor_clears_last_error_on_recovery() -> None:
    sensor, _ = _make_sensor(status=SyncStatus.CLEAN)
    sensor._attrs["last_error"] = "previous failure"
    await sensor.async_update()
    assert sensor.extra_state_attributes["last_error"] is None


async def test_sensor_keeps_error_attr_when_status_is_error() -> None:
    """If the manager reports ERROR explicitly, last_error stays untouched.

    The sensor only clears last_error when a *non*-ERROR status comes back —
    that keeps the previous failure visible until a real recovery.
    """
    sensor, _ = _make_sensor(snap=_snapshot(status=SyncStatus.ERROR))
    sensor._attrs["last_error"] = "prior failure"
    await sensor.async_update()
    assert sensor.native_value == SyncStatus.ERROR.value
    assert sensor.extra_state_attributes["last_error"] == "prior failure"


async def test_sensor_extra_attrs_include_commits_and_changed_files() -> None:
    local = CommitInfo(
        short_hash="abc1234",
        full_hash="abc1234" * 5 + "f",
        message="L",
        author="a",
        timestamp="2020-01-01T00:00:00+00:00",
    )
    remote = CommitInfo(
        short_hash="def9876",
        full_hash="def9876" * 5 + "0",
        message="R",
        author="b",
        timestamp="2020-01-02T00:00:00+00:00",
    )
    changed = (FileChange("M", "automations.yaml"),)
    sensor, manager = _make_sensor(
        snap=_snapshot(status=SyncStatus.MODIFIED, local=local, remote=remote, changed=changed)
    )
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    manager.last_operation = "push"
    manager.last_operation_at = ts
    manager.last_sync_at = ts
    await sensor.async_update()
    attrs = sensor.extra_state_attributes
    assert attrs["local_commit"] == "abc1234"
    assert attrs["remote_commit"] == "def9876"
    assert attrs["changed_files_count"] == 1
    assert attrs["changed_files"] == ["automations.yaml"]
    assert attrs["last_operation"] == "push"
    assert attrs["last_operation_time"] == ts.isoformat()
    assert attrs["last_sync"] == ts.isoformat()


async def test_local_commit_sensor_unknown_when_missing() -> None:
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.async_get_inspection_snapshot = AsyncMock(return_value=_snapshot(local=None))
    sensor = HaGitopsLocalCommitSensor(entry, manager, 60)
    await sensor.async_update()
    assert sensor.native_value == STATE_UNKNOWN


async def test_local_commit_sensor_shows_short_hash() -> None:
    info = CommitInfo(
        short_hash="deadbeef",
        full_hash="deadbeef" * 5 + "0",
        message="m",
        author="x",
        timestamp="2020-01-01T00:00:00+00:00",
    )
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.async_get_inspection_snapshot = AsyncMock(
        return_value=_snapshot(local=info, remote=None)
    )
    sensor = HaGitopsLocalCommitSensor(entry, manager, 60)
    await sensor.async_update()
    assert sensor.native_value == "deadbeef"
    assert sensor.extra_state_attributes["message"] == "m"


async def test_changed_files_sensor_counts() -> None:
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.async_get_inspection_snapshot = AsyncMock(
        return_value=_snapshot(
            changed=(
                FileChange("M", "a.yaml"),
                FileChange("A", "b.yaml"),
            )
        )
    )
    sensor = HaGitopsChangedFilesSensor(entry, manager, 60)
    await sensor.async_update()
    assert sensor.native_value == 2
    assert sensor.extra_state_attributes["files"] == [
        {"name": "a.yaml", "status": "M"},
        {"name": "b.yaml", "status": "A"},
    ]


async def test_last_sync_sensor_reads_manager_timestamp() -> None:
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.async_get_inspection_snapshot = AsyncMock(return_value=_snapshot())
    ts = datetime(2025, 6, 1, 8, 30, tzinfo=UTC)
    manager.last_sync_at = ts
    sensor = HaGitopsLastSyncSensor(entry, manager, 60)
    await sensor.async_update()
    assert sensor.native_value == ts


async def test_remote_commit_sensor_matches_local_when_clean() -> None:
    info = CommitInfo(
        short_hash="aaa",
        full_hash="aaa",
        message="m",
        author="u",
        timestamp="2020-01-01T00:00:00+00:00",
    )
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.async_get_inspection_snapshot = AsyncMock(return_value=_snapshot(remote=info))
    sensor = HaGitopsRemoteCommitSensor(entry, manager, 60)
    await sensor.async_update()
    assert sensor.native_value == "aaa"
