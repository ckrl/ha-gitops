"""HA GitOps — Git-backed synchronization for /config."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_COMMIT_MESSAGE,
    CONF_AUTO_RELOAD_AFTER_PULL,
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DATA_AUTO_RELOAD_AFTER_PULL,
    DATA_MANAGER,
    DATA_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_COMMIT_MESSAGE_LENGTH,
    PLATFORMS,
    SERVICE_COMMIT,
)
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)

COMMIT_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_COMMIT_MESSAGE, default=""): vol.All(
            cv.string,
            vol.Length(max=MAX_COMMIT_MESSAGE_LENGTH),
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Bootstrap integration (Config Flow only; no YAML domain block)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha_gitops from a config entry created in the UI."""
    data: dict[str, Any] = dict(entry.data)

    manager = GitManager(
        config_dir=hass.config.path(),
        repo_url=data[CONF_REPO_URL],
        branch=data[CONF_BRANCH],
        ssh_key_path=data[CONF_SSH_KEY_PATH],
        author_name=data[CONF_GIT_AUTHOR_NAME],
        author_email=data[CONF_GIT_AUTHOR_EMAIL],
    )

    try:
        await manager.initialize()
    except GitError as exc:
        _LOGGER.error("ha_gitops initialization failed: %s", exc)
        raise ConfigEntryNotReady(f"Git initialization failed: {exc}") from exc

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_MANAGER: manager,
        DATA_SCAN_INTERVAL: int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        DATA_AUTO_RELOAD_AFTER_PULL: bool(data.get(CONF_AUTO_RELOAD_AFTER_PULL, False)),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_handle_commit(call: ServiceCall) -> None:
        """Stage root YAML (same rules as Push) and commit without pushing."""
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if not runtime:
            raise HomeAssistantError("HA GitOps is not loaded for this config entry")

        raw = call.data.get(ATTR_COMMIT_MESSAGE, "")
        message: str | None = raw.strip() if isinstance(raw, str) else None
        if message == "":
            message = None

        mgr: GitManager = runtime[DATA_MANAGER]
        try:
            await mgr.commit(message=message)
        except GitError as exc:
            _LOGGER.error("ha_gitops.commit service failed: %s", exc)
            raise HomeAssistantError(str(exc)) from exc

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMMIT,
        async_handle_commit,
        schema=COMMIT_SERVICE_SCHEMA,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down platforms and drop runtime state for this entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.services.async_remove(DOMAIN, SERVICE_COMMIT)
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
