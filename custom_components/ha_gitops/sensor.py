"""Sensor platform for ha_gitops."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_MANAGER,
    DATA_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOCUMENTATION_URL,
    DOMAIN,
    SyncStatus,
)
from .git_manager import CommitInfo, GitManager, InspectionSnapshot

_LOGGER = logging.getLogger(__name__)


class _HaGitopsDiagnosticSensor(SensorEntity):
    """Shared device info + poll interval for Git-backed diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        self._entry = entry
        self._manager = manager
        self._scan_interval = timedelta(seconds=scan_interval)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HA GitOps",
            configuration_url=DOCUMENTATION_URL,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def scan_interval(self) -> timedelta:
        return self._scan_interval


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sync status and inspection sensors from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    manager: GitManager = runtime[DATA_MANAGER]
    interval: int = int(runtime.get(DATA_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    async_add_entities(
        [
            HaGitopsStatusSensor(entry, manager, interval),
            HaGitopsLocalCommitSensor(entry, manager, interval),
            HaGitopsRemoteCommitSensor(entry, manager, interval),
            HaGitopsChangedFilesSensor(entry, manager, interval),
            HaGitopsLastSyncSensor(entry, manager, interval),
        ],
        update_before_add=True,
    )


def _commit_attrs(info: CommitInfo | None) -> dict[str, Any]:
    if info is None:
        return {
            "full_hash": None,
            "message": None,
            "author": None,
            "timestamp": None,
        }
    return {
        "full_hash": info.full_hash,
        "message": info.message,
        "author": info.author,
        "timestamp": info.timestamp,
    }


class HaGitopsStatusSensor(_HaGitopsDiagnosticSensor):
    """Reports the current synchronization status of /config vs remote."""

    _attr_name = "Sync status"
    _attr_icon = "mdi:source-branch"
    _attr_translation_key = "sync_status"

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        super().__init__(entry, manager, scan_interval)
        self._attr_unique_id = f"{entry.entry_id}_sync_status"
        self._attr_native_value: str = SyncStatus.UNKNOWN.value
        self._attrs: dict[str, Any] = {
            "last_operation": None,
            "last_operation_time": None,
            "last_error": None,
            "last_sync": None,
            "local_commit": None,
            "remote_commit": None,
            "changed_files_count": None,
            "changed_files": None,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    def _apply_snapshot(self, snap: InspectionSnapshot) -> None:
        self._attr_native_value = snap.status.value
        if snap.status is not SyncStatus.ERROR:
            self._attrs["last_error"] = None
        self._attrs["local_commit"] = snap.local.short_hash if snap.local else None
        self._attrs["remote_commit"] = snap.remote.short_hash if snap.remote else None
        self._attrs["changed_files_count"] = len(snap.changed)
        self._attrs["changed_files"] = [fc.name for fc in snap.changed]
        op = self._manager.last_operation
        op_at = self._manager.last_operation_at
        sync_at = self._manager.last_sync_at
        self._attrs["last_operation"] = op
        self._attrs["last_operation_time"] = op_at.isoformat() if op_at else None
        self._attrs["last_sync"] = sync_at.isoformat() if sync_at else None

    async def async_update(self) -> None:
        """Refresh the sensor state via a single GitManager inspection snapshot."""
        try:
            snap = await self._manager.async_get_inspection_snapshot()
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.exception("ha_gitops status update failed")
            self._attr_native_value = SyncStatus.ERROR.value
            self._attrs["last_error"] = str(exc)
            return

        self._apply_snapshot(snap)


class HaGitopsLocalCommitSensor(_HaGitopsDiagnosticSensor):
    """Local HEAD commit (short hash + metadata)."""

    _attr_icon = "mdi:source-commit-local"
    _attr_translation_key = "local_commit"

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        super().__init__(entry, manager, scan_interval)
        self._attr_unique_id = f"{entry.entry_id}_local_commit"
        self._attr_object_id = "ha_gitops_commit_local"
        self._attr_native_value: str | None = STATE_UNKNOWN
        self._extra: dict[str, Any] = _commit_attrs(None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    async def async_update(self) -> None:
        try:
            snap = await self._manager.async_get_inspection_snapshot()
        except Exception:  # pragma: no cover - defensive
            self._attr_native_value = STATE_UNKNOWN
            return
        if snap.local:
            self._attr_native_value = snap.local.short_hash
            self._extra = _commit_attrs(snap.local)
        else:
            self._attr_native_value = STATE_UNKNOWN
            self._extra = _commit_attrs(None)


class HaGitopsRemoteCommitSensor(_HaGitopsDiagnosticSensor):
    """origin/<branch> tip commit (short hash + metadata)."""

    _attr_icon = "mdi:source-commit"
    _attr_translation_key = "remote_commit"

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        super().__init__(entry, manager, scan_interval)
        self._attr_unique_id = f"{entry.entry_id}_remote_commit"
        self._attr_object_id = "ha_gitopss_commit_remote"
        self._attr_native_value: str | None = STATE_UNKNOWN
        self._extra = _commit_attrs(None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    async def async_update(self) -> None:
        try:
            snap = await self._manager.async_get_inspection_snapshot()
        except Exception:  # pragma: no cover - defensive
            self._attr_native_value = STATE_UNKNOWN
            return
        if snap.remote:
            self._attr_native_value = snap.remote.short_hash
            self._extra = _commit_attrs(snap.remote)
        else:
            self._attr_native_value = STATE_UNKNOWN
            self._extra = _commit_attrs(None)


class HaGitopsChangedFilesSensor(_HaGitopsDiagnosticSensor):
    """Count of root-level YAML files with local working-tree changes."""

    _attr_icon = "mdi:file-document-edit-outline"
    _attr_translation_key = "changed_files"

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        super().__init__(entry, manager, scan_interval)
        self._attr_unique_id = f"{entry.entry_id}_changed_files"
        self._attr_object_id = "ha_gitops_changed_files"
        self._attr_native_value = 0
        self._files_attr: list[dict[str, str]] = []

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"files": self._files_attr}

    async def async_update(self) -> None:
        try:
            snap = await self._manager.async_get_inspection_snapshot()
        except Exception:  # pragma: no cover - defensive
            self._attr_native_value = 0
            self._files_attr = []
            return
        self._attr_native_value = len(snap.changed)
        self._files_attr = [{"name": fc.name, "status": fc.status} for fc in snap.changed]


class HaGitopsLastSyncSensor(_HaGitopsDiagnosticSensor):
    """When the integration last completed a remote sync (fetch / pull / push)."""

    _attr_icon = "mdi:cloud-sync-outline"
    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: ConfigEntry, manager: GitManager, scan_interval: int) -> None:
        super().__init__(entry, manager, scan_interval)
        self._attr_unique_id = f"{entry.entry_id}_last_sync"
        self._attr_native_value: Any = None

    async def async_update(self) -> None:
        try:
            await self._manager.async_get_inspection_snapshot()
        except Exception:  # pragma: no cover - defensive
            self._attr_native_value = None
            return
        self._attr_native_value = self._manager.last_sync_at
