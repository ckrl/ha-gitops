"""UI Config Flow for ha_gitops.

Architecture: docs/architecture.md §6 (configuration) and §12.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AUTO_RELOAD_AFTER_PULL,
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

STEP_OPTIONS_MENU_SCHEMA = vol.Schema(
    {
        vol.Required("menu_action"): vol.In(
            ["settings", "generate_key", "test_connection"]
        ),
    }
)

STEP_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REPO_URL): cv.string,
        vol.Optional(CONF_BRANCH, default=DEFAULT_BRANCH): cv.string,
        vol.Optional(CONF_GIT_AUTHOR_NAME, default=DEFAULT_AUTHOR_NAME): cv.string,
        vol.Optional(CONF_GIT_AUTHOR_EMAIL, default=DEFAULT_AUTHOR_EMAIL): cv.string,
        vol.Optional(CONF_SSH_KEY_PATH, default=""): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=86400)
        ),
        vol.Optional(CONF_AUTO_RELOAD_AFTER_PULL, default=False): cv.boolean,
    }
)

STEP_GENERATE_KEY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SSH_KEY_PATH, default=""): cv.string,
    }
)


def _build_git_manager(hass: HomeAssistant, data: dict[str, Any]) -> GitManager:
    """Construct GitManager from entry-shaped dict (uses hass.config.path())."""
    return GitManager(
        config_dir=hass.config.path(),
        repo_url=data[CONF_REPO_URL].strip(),
        branch=(data.get(CONF_BRANCH) or DEFAULT_BRANCH).strip(),
        ssh_key_path=(data.get(CONF_SSH_KEY_PATH) or "").strip(),
        author_name=(data.get(CONF_GIT_AUTHOR_NAME) or DEFAULT_AUTHOR_NAME).strip(),
        author_email=(data.get(CONF_GIT_AUTHOR_EMAIL) or DEFAULT_AUTHOR_EMAIL).strip(),
    )


def _coerce_scan_interval(data: dict[str, Any]) -> int:
    """Return scan interval in seconds (clamped)."""
    raw = data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL
    return max(30, min(n, 86400))


async def _validate_git_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Run GitManager.initialize(); return normalized data for ConfigEntry storage."""
    manager = _build_git_manager(hass, data)
    await manager.initialize()

    return {
        CONF_REPO_URL: data[CONF_REPO_URL].strip(),
        CONF_BRANCH: (data.get(CONF_BRANCH) or DEFAULT_BRANCH).strip(),
        CONF_GIT_AUTHOR_NAME: (data.get(CONF_GIT_AUTHOR_NAME) or DEFAULT_AUTHOR_NAME).strip(),
        CONF_GIT_AUTHOR_EMAIL: (data.get(CONF_GIT_AUTHOR_EMAIL) or DEFAULT_AUTHOR_EMAIL).strip(),
        CONF_SSH_KEY_PATH: str(manager.ssh_key_path),
        CONF_SCAN_INTERVAL: _coerce_scan_interval(data),
        CONF_AUTO_RELOAD_AFTER_PULL: bool(data.get(CONF_AUTO_RELOAD_AFTER_PULL, False)),
    }


class HaGitopsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: one instance per Home Assistant (single /config tree)."""

    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask for remote URL, branch, git author, and SSH private key path."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        errors: dict[str, str] = {}
        try:
            merged = {**user_input, CONF_AUTO_RELOAD_AFTER_PULL: False}
            normalized = await _validate_git_connection(self.hass, merged)
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HaGitopsOptionsFlow:
        """Allow changing connection settings from Integrations → Configure."""
        return HaGitopsOptionsFlow(config_entry)


class HaGitopsOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Options flow: menu for settings, SSH key generation, or connection test."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Root menu for HA GitOps options."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=STEP_OPTIONS_MENU_SCHEMA,
            )

        action = user_input["menu_action"]
        if action == "settings":
            return await self.async_step_settings()
        if action == "generate_key":
            return await self.async_step_generate_key()
        return await self.async_step_test_connection()

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit Git remote, author, SSH path, polling, and post-pull auto-reload."""
        if user_input is None:
            defaults = {**self.config_entry.data}
            if CONF_AUTO_RELOAD_AFTER_PULL not in defaults:
                defaults[CONF_AUTO_RELOAD_AFTER_PULL] = False
            return self.async_show_form(
                step_id="settings",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_OPTIONS_SCHEMA,
                    defaults,
                ),
            )

        errors: dict[str, str] = {}
        try:
            normalized = await _validate_git_connection(self.hass, user_input)
        except GitError:
            _LOGGER.exception("ha_gitops options flow: repository initialization failed")
            errors["base"] = "git_error"
        except Exception:  # pragma: no cover - defensive
            _LOGGER.exception("ha_gitops options flow: unexpected error")
            errors["base"] = "unknown"
        else:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=normalized,
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(STEP_OPTIONS_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_generate_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Generate ED25519 key at the chosen path (default: integration SSH path)."""
        if user_input is None:
            return self.async_show_form(
                step_id="generate_key",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_GENERATE_KEY_SCHEMA,
                    {CONF_SSH_KEY_PATH: self.config_entry.data.get(CONF_SSH_KEY_PATH, "")},
                ),
            )

        raw = (user_input.get(CONF_SSH_KEY_PATH) or "").strip()
        merged = {**self.config_entry.data, CONF_SSH_KEY_PATH: raw}
        manager = _build_git_manager(self.hass, merged)
        try:
            pub = await manager.generate_ssh_key()
        except GitError as exc:
            _LOGGER.warning("ha_gitops: SSH key generation failed: %s", exc)
            return self.async_show_form(
                step_id="generate_key",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_GENERATE_KEY_SCHEMA,
                    user_input,
                ),
                errors={"base": "ssh_keygen_failed"},
            )

        new_path = str(manager.ssh_key_path)
        if new_path != self.config_entry.data.get(CONF_SSH_KEY_PATH, ""):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_SSH_KEY_PATH: new_path},
            )

        if self.hass.services.has_service("persistent_notification", "create"):
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "HA GitOps: SSH public key",
                    "message": (
                        "Add this **public** key to your Git host (deploy key or user SSH keys).\n\n"
                        f"```\n{pub}\n```\n\n"
                        f"Private key path (not shown): `{new_path}`"
                    ),
                    "notification_id": f"{DOMAIN}_ssh_key_generated",
                },
                blocking=False,
            )
        else:
            _LOGGER.info(
                "ha_gitops: generated SSH key at %s (persistent_notification not available)",
                new_path,
            )

        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_abort(reason="ssh_key_generated")

    async def async_step_test_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Run a lightweight ``git ls-remote`` against ``origin``."""
        if user_input is None:
            manager = _build_git_manager(self.hass, dict(self.config_entry.data))
            ok = await manager.test_connection()
            result_text = (
                "git ls-remote origin succeeded — SSH authentication and remote URL look OK."
                if ok
                else "git ls-remote origin failed. Check Home Assistant logs, deploy key access, and the repository URL."
            )
            return self.async_show_form(
                step_id="test_connection",
                data_schema=vol.Schema({}),
                description_placeholders={"result_text": result_text},
            )

        return await self.async_step_init()
