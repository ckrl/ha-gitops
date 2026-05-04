"""Button platform for ha_gitops — Pull and Push actions."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_MANAGER, DOCUMENTATION_URL, DOMAIN
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pull/Push buttons from a config entry."""
    manager: GitManager = hass.data[DOMAIN][entry.entry_id][DATA_MANAGER]
    async_add_entities(
        [
            HaGitopsPullButton(hass, entry, manager),
            HaGitopsPushButton(hass, entry, manager),
        ]
    )


class _BaseGitopsButton(ButtonEntity):
    """Common bits for ha_gitops buttons."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: GitManager) -> None:
        self._hass = hass
        self._entry = entry
        self._manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HA GitOps",
            model="/config Git sync",
            configuration_url=DOCUMENTATION_URL,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def _notify(self, title: str, message: str) -> None:
        """Send a persistent notification with a sanitized message."""
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": title, "message": message, "notification_id": self.unique_id},
            blocking=False,
        )


class HaGitopsPullButton(_BaseGitopsButton):
    """Fetch + ff-only merge from origin/<branch>."""

    _attr_name = "Pull"
    _attr_icon = "mdi:cloud-download-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: GitManager) -> None:
        super().__init__(hass, entry, manager)
        self._attr_unique_id = f"{entry.entry_id}_pull"

    async def async_press(self) -> None:
        try:
            result = await self._manager.pull()
        except GitError as exc:
            _LOGGER.error("ha_gitops pull failed: %s", exc)
            await self._notify("HA GitOps: pull failed", str(exc))
            return

        if result.changed_files:
            await self._notify(
                "HA GitOps: config updated",
                "Remote changes pulled. Reload Home Assistant to apply.",
            )


class HaGitopsPushButton(_BaseGitopsButton):
    """Stage YAML files (excluding secrets), commit, push."""

    _attr_name = "Push"
    _attr_icon = "mdi:cloud-upload-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: GitManager) -> None:
        super().__init__(hass, entry, manager)
        self._attr_unique_id = f"{entry.entry_id}_push"

    async def async_press(self) -> None:
        try:
            await self._manager.push()
        except GitError as exc:
            _LOGGER.error("ha_gitops push failed: %s", exc)
            await self._notify("HA GitOps: push failed", str(exc))
