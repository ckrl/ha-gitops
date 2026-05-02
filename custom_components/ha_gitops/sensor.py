"""Sensor platform for ha_gitops."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    DATA_MANAGER,
    DATA_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SyncStatus,
)
from .git_manager import GitManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up ha_gitops sensors from YAML."""
    data = hass.data.get(DOMAIN)
    if not data:
        return

    manager: GitManager = data[DATA_MANAGER]
    interval: int = data.get(DATA_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    sensor = HaGitopsStatusSensor(manager, interval)
    async_add_entities([sensor], update_before_add=True)


class HaGitopsStatusSensor(SensorEntity):
    """Reports the current synchronization status of /config vs remote."""

    _attr_has_entity_name = True
    _attr_name = "Sync status"
    _attr_icon = "mdi:source-branch"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: GitManager, scan_interval: int) -> None:
        self._manager = manager
        self._attr_unique_id = f"{DOMAIN}_status"
        self._attr_native_value: str = SyncStatus.UNKNOWN.value
        self._attrs: dict[str, Any] = {
            "last_operation": None,
            "last_operation_time": None,
            "last_error": None,
            "local_commit": None,
            "remote_commit": None,
        }
        self._scan_interval = timedelta(seconds=scan_interval)

    @property
    def scan_interval(self) -> timedelta:
        return self._scan_interval

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    async def async_update(self) -> None:
        """Refresh the sensor state by asking GitManager for current status."""
        try:
            status = await self._manager.get_status()
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.exception("ha_gitops status update failed")
            self._attr_native_value = SyncStatus.ERROR.value
            self._attrs["last_error"] = str(exc)
            return

        self._attr_native_value = status.value
        if status is not SyncStatus.ERROR:
            self._attrs["last_error"] = None
