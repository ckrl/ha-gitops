"""HA GitOps — Git-backed synchronization for /config."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
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
    DEFAULT_AUTHOR_EMAIL,
    DEFAULT_AUTHOR_NAME,
    DEFAULT_BRANCH,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSH_DIR,
    DEFAULT_SSH_KEY_FILENAME,
    DOMAIN,
    PLATFORMS,
)
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_REPO_URL): cv.string,
                vol.Optional(CONF_BRANCH, default=DEFAULT_BRANCH): cv.string,
                vol.Optional(CONF_SSH_KEY_PATH): cv.string,
                vol.Optional(CONF_GIT_AUTHOR_NAME, default=DEFAULT_AUTHOR_NAME): cv.string,
                vol.Optional(CONF_GIT_AUTHOR_EMAIL, default=DEFAULT_AUTHOR_EMAIL): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up ha_gitops from configuration.yaml (MVP)."""
    if DOMAIN not in config:
        return True

    conf: dict[str, Any] = config[DOMAIN]
    ssh_key_path = conf.get(CONF_SSH_KEY_PATH) or hass.config.path(
        DEFAULT_SSH_DIR, DEFAULT_SSH_KEY_FILENAME
    )

    manager = GitManager(
        config_dir=hass.config.path(),
        repo_url=conf[CONF_REPO_URL],
        branch=conf[CONF_BRANCH],
        ssh_key_path=ssh_key_path,
        author_name=conf[CONF_GIT_AUTHOR_NAME],
        author_email=conf[CONF_GIT_AUTHOR_EMAIL],
    )

    try:
        await manager.initialize()
    except GitError as exc:
        _LOGGER.error("ha_gitops initialization failed: %s", exc)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][DATA_MANAGER] = manager
    hass.data[DOMAIN][DATA_SCAN_INTERVAL] = conf[CONF_SCAN_INTERVAL]

    for platform in PLATFORMS:
        hass.async_create_task(
            discovery.async_load_platform(hass, platform, DOMAIN, {}, config)
        )

    return True
