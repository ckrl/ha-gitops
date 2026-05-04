"""Tests for the ha_gitops UI Config Flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_gitops.config_flow import HaGitopsConfigFlow
from custom_components.ha_gitops.const import (
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
