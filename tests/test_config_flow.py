"""Tests for the ha_gitops UI Config Flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_gitops.config_flow import HaGitopsConfigFlow
from custom_components.ha_gitops.const import (
    CONF_AUTO_RELOAD_AFTER_PULL,
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.ha_gitops.git_manager import GitError


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: Any) -> None:
    return None


def _valid_user_input() -> dict[str, str]:
    return {
        CONF_REPO_URL: "git@example.com:owner/repo.git",
        CONF_BRANCH: "main",
        CONF_GIT_AUTHOR_NAME: "HA",
        CONF_GIT_AUTHOR_EMAIL: "ha@example.com",
        CONF_SSH_KEY_PATH: "",
    }


def _sample_entry_data() -> dict[str, Any]:
    return {
        CONF_REPO_URL: "git@example.com:org/old.git",
        CONF_BRANCH: "main",
        CONF_GIT_AUTHOR_NAME: "HA",
        CONF_GIT_AUTHOR_EMAIL: "ha@example.com",
        CONF_SSH_KEY_PATH: "/config/.ha_gitops/id_ed25519",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_AUTO_RELOAD_AFTER_PULL: False,
    }


async def test_config_flow_shows_form(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_config_flow_creates_entry_when_git_succeeds(hass: HomeAssistant) -> None:
    normalized = {
        **_valid_user_input(),
        CONF_SSH_KEY_PATH: "/config/.ha_gitops/id_ed25519",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_AUTO_RELOAD_AFTER_PULL: False,
    }
    with (
        patch(
            "custom_components.ha_gitops.config_flow._validate_git_connection",
            new=AsyncMock(return_value=normalized),
        ),
        # Creating the config entry schedules async_setup_entry; avoid real git in unit tests.
        patch(
            "custom_components.ha_gitops.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_valid_user_input(),
        )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    entry = result2["result"]
    assert entry.domain == DOMAIN
    assert entry.data[CONF_REPO_URL] == normalized[CONF_REPO_URL]
    assert entry.unique_id == DOMAIN


async def test_config_flow_shows_error_on_git_failure(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.ha_gitops.config_flow._validate_git_connection",
        new=AsyncMock(side_effect=GitError("nope")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_valid_user_input(),
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "git_error"}


async def test_config_flow_aborts_when_already_configured(hass: HomeAssistant) -> None:
    """Second flow must abort: single-instance integration."""
    normalized = {
        **_valid_user_input(),
        CONF_SSH_KEY_PATH: "/x",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_AUTO_RELOAD_AFTER_PULL: False,
    }
    with (
        patch(
            "custom_components.ha_gitops.config_flow._validate_git_connection",
            new=AsyncMock(return_value=normalized),
        ),
        patch(
            "custom_components.ha_gitops.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        first = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            first["flow_id"],
            user_input=_valid_user_input(),
        )

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert second["type"] == FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_config_flow_class_version() -> None:
    assert HaGitopsConfigFlow.VERSION == 1
    assert HaGitopsConfigFlow.MINOR_VERSION == 2


async def test_config_flow_exposes_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert HaGitopsConfigFlow.async_supports_options_flow(entry) is True


async def test_options_flow_shows_menu_first(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_updates_entry_data_and_reloads(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    updated = {
        **_sample_entry_data(),
        CONF_REPO_URL: "git@example.com:org/new.git",
        CONF_BRANCH: "develop",
        CONF_SCAN_INTERVAL: 600,
        CONF_AUTO_RELOAD_AFTER_PULL: True,
    }

    reload = AsyncMock(return_value=None)
    with (
        patch(
            "custom_components.ha_gitops.config_flow._validate_git_connection",
            new=AsyncMock(return_value=updated),
        ),
        patch.object(hass.config_entries, "async_reload", reload),
    ):
        start = await hass.config_entries.options.async_init(entry.entry_id)
        menu = await hass.config_entries.options.async_configure(
            start["flow_id"],
            user_input={"menu_action": "settings"},
        )
        assert menu["step_id"] == "settings"
        result = await hass.config_entries.options.async_configure(
            menu["flow_id"],
            user_input={
                CONF_REPO_URL: "git@example.com:org/new.git",
                CONF_BRANCH: "develop",
                CONF_GIT_AUTHOR_NAME: "HA",
                CONF_GIT_AUTHOR_EMAIL: "ha@example.com",
                CONF_SSH_KEY_PATH: "",
                CONF_SCAN_INTERVAL: 600,
                CONF_AUTO_RELOAD_AFTER_PULL: True,
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_REPO_URL] == "git@example.com:org/new.git"
    assert entry.data[CONF_BRANCH] == "develop"
    assert entry.data[CONF_SCAN_INTERVAL] == 600
    assert entry.data[CONF_AUTO_RELOAD_AFTER_PULL] is True
    reload.assert_awaited_once_with(entry.entry_id)


async def test_options_flow_shows_error_on_git_failure(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_gitops.config_flow._validate_git_connection",
        new=AsyncMock(side_effect=GitError("fail")),
    ):
        start = await hass.config_entries.options.async_init(entry.entry_id)
        settings = await hass.config_entries.options.async_configure(
            start["flow_id"],
            user_input={"menu_action": "settings"},
        )
        result = await hass.config_entries.options.async_configure(
            settings["flow_id"],
            user_input={
                CONF_REPO_URL: "git@example.com:org/bad.git",
                CONF_BRANCH: "main",
                CONF_GIT_AUTHOR_NAME: "HA",
                CONF_GIT_AUTHOR_EMAIL: "ha@example.com",
                CONF_SSH_KEY_PATH: "",
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_AUTO_RELOAD_AFTER_PULL: False,
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "git_error"}


async def test_options_flow_generate_key_aborts_after_success(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock()
    fake.generate_ssh_key = AsyncMock(return_value="ssh-ed25519 AAAA")
    fake.ssh_key_path = Path("/config/.ha_gitops/id_ed25519")

    reload = AsyncMock(return_value=None)
    with (
        patch("custom_components.ha_gitops.config_flow._build_git_manager", return_value=fake),
        patch.object(hass.config_entries, "async_reload", reload),
    ):
        start = await hass.config_entries.options.async_init(entry.entry_id)
        gen = await hass.config_entries.options.async_configure(
            start["flow_id"],
            user_input={"menu_action": "generate_key"},
        )
        assert gen["step_id"] == "generate_key"
        result = await hass.config_entries.options.async_configure(
            gen["flow_id"],
            user_input={CONF_SSH_KEY_PATH: ""},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "ssh_key_generated"
    fake.generate_ssh_key.assert_awaited_once()
    reload.assert_awaited_once_with(entry.entry_id)


async def test_options_flow_test_connection_returns_to_menu(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_sample_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock()
    fake.test_connection = AsyncMock(return_value=True)
    with patch("custom_components.ha_gitops.config_flow._build_git_manager", return_value=fake):
        start = await hass.config_entries.options.async_init(entry.entry_id)
        tc = await hass.config_entries.options.async_configure(
            start["flow_id"],
            user_input={"menu_action": "test_connection"},
        )
        assert tc["step_id"] == "test_connection"
        back = await hass.config_entries.options.async_configure(
            tc["flow_id"],
            user_input={},
        )

    assert back["type"] == FlowResultType.FORM
    assert back["step_id"] == "init"
    fake.test_connection.assert_awaited_once()
