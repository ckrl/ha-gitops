"""UI Config Flow for ha_gitops.

Architecture: docs/architecture.md §6 (configuration) and §12 item 1.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DEFAULT_AUTHOR_EMAIL,
    DEFAULT_AUTHOR_NAME,
    DEFAULT_BRANCH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .git_manager import GitError, GitManager

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REPO_URL): cv.string,
        vol.Optional(CONF_BRANCH, default=DEFAULT_BRANCH): cv.string,
        vol.Optional(CONF_GIT_AUTHOR_NAME, default=DEFAULT_AUTHOR_NAME): cv.string,
        vol.Optional(CONF_GIT_AUTHOR_EMAIL, default=DEFAULT_AUTHOR_EMAIL): cv.string,
        vol.Optional(CONF_SSH_KEY_PATH, default=""): cv.string,
    }
)


async def _validate_git_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Run GitManager.initialize(); return normalized data for ConfigEntry storage."""
    ssh_raw = (data.get(CONF_SSH_KEY_PATH) or "").strip()

    manager = GitManager(
        config_dir=hass.config.path(),
        repo_url=data[CONF_REPO_URL].strip(),
        branch=(data.get(CONF_BRANCH) or DEFAULT_BRANCH).strip(),
        ssh_key_path=ssh_raw,
        author_name=(data.get(CONF_GIT_AUTHOR_NAME) or DEFAULT_AUTHOR_NAME).strip(),
        author_email=(data.get(CONF_GIT_AUTHOR_EMAIL) or DEFAULT_AUTHOR_EMAIL).strip(),
    )
    await manager.initialize()

    return {
        CONF_REPO_URL: data[CONF_REPO_URL].strip(),
        CONF_BRANCH: (data.get(CONF_BRANCH) or DEFAULT_BRANCH).strip(),
        CONF_GIT_AUTHOR_NAME: (data.get(CONF_GIT_AUTHOR_NAME) or DEFAULT_AUTHOR_NAME).strip(),
        CONF_GIT_AUTHOR_EMAIL: (data.get(CONF_GIT_AUTHOR_EMAIL) or DEFAULT_AUTHOR_EMAIL).strip(),
        CONF_SSH_KEY_PATH: str(manager.ssh_key_path),
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    }


class HaGitopsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: one instance per Home Assistant (single /config tree)."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask for remote URL, branch, git author, and SSH private key path."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        errors: dict[str, str] = {}
        try:
            normalized = await _validate_git_connection(self.hass, user_input)
        except GitError:
            _LOGGER.exception("ha_gitops config flow: repository initialization failed")
            errors["base"] = "git_error"
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("ha_gitops config flow: unexpected error")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="HA GitOps", data=normalized)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )
