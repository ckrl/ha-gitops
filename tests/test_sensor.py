"""Unit tests for the ha_gitops sync-status sensor.

Architecture: docs/architecture.md §6.2 (Status sensor) and §7.3 (states table).

These tests exercise the sensor entity in isolation with a MagicMock
GitManager — fast, no HA event loop required. End-to-end registration
through Home Assistant is covered by tests/test_setup.py.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory

from custom_components.ha_gitops.const import DEFAULT_SCAN_INTERVAL, DOMAIN, SyncStatus
from custom_components.ha_gitops.sensor import HaGitopsStatusSensor


def _mock_config_entry(entry_id: str = "test_entry_id") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "HA GitOps"
    return entry


def _make_sensor(
    *,
    status: SyncStatus = SyncStatus.CLEAN,
    raises: Exception | None = None,
    scan_interval: int = DEFAULT_SCAN_INTERVAL,
    entry_id: str = "test_entry_id",
) -> tuple[HaGitopsStatusSensor, MagicMock]:
    manager = MagicMock()
    if raises is not None:
        manager.get_status = AsyncMock(side_effect=raises)
    else:
        manager.get_status = AsyncMock(return_value=status)
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
    manager.get_status.assert_awaited_once()


async def test_sensor_propagates_each_status_value() -> None:
    """Every SyncStatus emitted by GitManager surfaces as the native value."""
    for status in SyncStatus:
        sensor, _ = _make_sensor(status=status)
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
    sensor, _ = _make_sensor(status=SyncStatus.ERROR)
    sensor._attrs["last_error"] = "prior failure"
    await sensor.async_update()
    assert sensor.native_value == SyncStatus.ERROR.value
    assert sensor.extra_state_attributes["last_error"] == "prior failure"


async def test_sensor_extra_attrs_are_initialized() -> None:
    sensor, _ = _make_sensor()
    attrs = sensor.extra_state_attributes
    for key in (
        "last_operation",
        "last_operation_time",
        "last_error",
        "local_commit",
        "remote_commit",
    ):
        assert key in attrs
        assert attrs[key] is None
