"""Button platform for ha_gitops — Pull and Push actions."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DATA_MANAGER, DOMAIN
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up ha_gitops buttons from YAML."""
    data = hass.data.get(DOMAIN)
    if not data:
        return

    manager: GitManager = data[DATA_MANAGER]
    async_add_entities(
        [
            HaGitopsPullButton(hass, manager),
            HaGitopsPushButton(hass, manager),
        ]
    )


class _BaseGitopsButton(ButtonEntity):
    """Common bits for ha_gitops buttons."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, manager: GitManager) -> None:
        self._hass = hass
        self._manager = manager

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

    def __init__(self, hass: HomeAssistant, manager: GitManager) -> None:
        super().__init__(hass, manager)
        self._attr_unique_id = f"{DOMAIN}_pull"

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

    def __init__(self, hass: HomeAssistant, manager: GitManager) -> None:
        super().__init__(hass, manager)
        self._attr_unique_id = f"{DOMAIN}_push"

    async def async_press(self) -> None:
        try:
            await self._manager.push()
        except GitError as exc:
            _LOGGER.error("ha_gitops push failed: %s", exc)
            await self._notify("HA GitOps: push failed", str(exc))
