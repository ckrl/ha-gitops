"""Button platform for ha_gitops — Pull, Fetch, and Push actions."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_AUTO_RELOAD_AFTER_PULL,
    DATA_MANAGER,
    DOCUMENTATION_URL,
    DOMAIN,
    ISSUE_PULLED_CONFIG_RELOAD,
    MY_RELOAD_CORE_CONFIG_REDIRECT,
)
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)

_MAX_FILE_LIST_LEN = 400


def _format_changed_files(names: Sequence[str]) -> str:
    joined = ", ".join(sorted(names))
    if len(joined) > _MAX_FILE_LIST_LEN:
        return joined[: _MAX_FILE_LIST_LEN - 3] + "..."
    return joined


async def _notify_pull_with_changes(
    hass: HomeAssistant,
    *,
    notification_id: str,
    title: str,
    changed_files: tuple[str, ...],
) -> None:
    """Persistent notification + repairs issue (fix: reload core config)."""
    file_summary = _format_changed_files(changed_files)
    link = MY_RELOAD_CORE_CONFIG_REDIRECT
    message = (
        "Remote changes were merged into your configuration directory. "
        "Reload core configuration to apply YAML changes, or restart Home Assistant.\n\n"
        f"- [Reload core configuration]({link}) (via My Home Assistant)\n"
        f"- Changed files ({len(changed_files)}): {file_summary}\n\n"
        "You can also use **Settings → System → Repairs** and run the HA GitOps fix."
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": title, "message": message, "notification_id": notification_id},
        blocking=False,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_PULLED_CONFIG_RELOAD,
        is_fixable=True,
        is_persistent=False,
        learn_more_url=DOCUMENTATION_URL,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_PULLED_CONFIG_RELOAD,
        translation_placeholders={
            "count": str(len(changed_files)),
            "files": file_summary,
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pull / Fetch / Push buttons from a config entry."""
    manager: GitManager = hass.data[DOMAIN][entry.entry_id][DATA_MANAGER]
    async_add_entities(
        [
            HaGitopsPullButton(hass, entry, manager),
            HaGitopsFetchButton(hass, entry, manager),
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
            runtime = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            if runtime.get(DATA_AUTO_RELOAD_AFTER_PULL):
                await self._hass.services.async_call(
                    "homeassistant",
                    "reload_core_config",
                    {},
                    blocking=True,
                )
                await self._notify(
                    "HA GitOps: config updated",
                    "Core configuration was reloaded automatically after pull with YAML changes.",
                )
                return

            await _notify_pull_with_changes(
                self._hass,
                notification_id=self.unique_id,
                title="HA GitOps: config updated",
                changed_files=result.changed_files,
            )


class HaGitopsFetchButton(_BaseGitopsButton):
    """Run `git fetch origin` only — updates remote refs; does not merge."""

    _attr_name = "Fetch"
    _attr_icon = "mdi:cloud-sync-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: GitManager) -> None:
        super().__init__(hass, entry, manager)
        self._attr_unique_id = f"{entry.entry_id}_fetch"

    async def async_press(self) -> None:
        try:
            await self._manager.fetch()
        except GitError as exc:
            _LOGGER.error("ha_gitops fetch failed: %s", exc)
            await self._notify("HA GitOps: fetch failed", str(exc))


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
