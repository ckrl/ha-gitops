"""HA GitOps — Git-backed synchronization for /config."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DATA_MANAGER,
    DATA_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)


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
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down platforms and drop runtime state for this entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
