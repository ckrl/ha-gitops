"""Tests for ha_gitops services."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_gitops.const import (
    ATTR_COMMIT_MESSAGE,
    CONF_AUTO_RELOAD_AFTER_PULL,
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_COMMIT,
    SyncStatus,
)
from custom_components.ha_gitops.git_manager import GitError, GitResult, InspectionSnapshot


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: Any) -> None:
    return None


def _stub_sensor_manager(fake: MagicMock) -> MagicMock:
    """GitManager mock must satisfy sensor platform polling during setup."""
    fake.last_operation = None
    fake.last_operation_at = None
    fake.last_sync_at = None
    fake.async_get_inspection_snapshot = AsyncMock(
        return_value=InspectionSnapshot(
            status=SyncStatus.UNKNOWN,
            local=None,
            remote=None,
            changed=(),
        )
    )
    return fake


def _entry_data() -> dict[str, Any]:
    return {
        CONF_REPO_URL: "git@example.com:test/config.git",
        CONF_BRANCH: "main",
        CONF_GIT_AUTHOR_NAME: "Test",
        CONF_GIT_AUTHOR_EMAIL: "test@local",
        CONF_SSH_KEY_PATH: "/config/.ha_gitops/id_ed25519",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_AUTO_RELOAD_AFTER_PULL: False,
    }


async def test_commit_service_registers_and_calls_manager(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock(name="GitManager")
    fake.initialize = AsyncMock(return_value=None)
    fake.commit = AsyncMock(
        return_value=GitResult(ok=True, message="Committed", changed_files=("a.yaml",)),
    )
    _stub_sensor_manager(fake)
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_COMMIT)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMMIT,
        {ATTR_COMMIT_MESSAGE: "  Manual snapshot  \n"},
        blocking=True,
        return_response=False,
    )
    fake.commit.assert_awaited_once_with(message="Manual snapshot")


async def test_commit_service_omits_message_when_blank(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock(name="GitManager")
    fake.initialize = AsyncMock(return_value=None)
    fake.commit = AsyncMock(
        return_value=GitResult(ok=True, message="Nothing to commit", changed_files=()),
    )
    _stub_sensor_manager(fake)
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(DOMAIN, SERVICE_COMMIT, {}, blocking=True)
    fake.commit.assert_awaited_once_with(message=None)


async def test_commit_service_raises_homeassistant_error_on_git_error(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock(name="GitManager")
    fake.initialize = AsyncMock(return_value=None)
    fake.commit = AsyncMock(side_effect=GitError("staging failed"))
    _stub_sensor_manager(fake)
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="staging failed"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_COMMIT,
            {ATTR_COMMIT_MESSAGE: "x"},
            blocking=True,
        )


async def test_commit_service_removed_on_unload(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = MagicMock(name="GitManager")
    fake.initialize = AsyncMock(return_value=None)
    fake.commit = AsyncMock(return_value=GitResult(ok=True, message="ok", changed_files=()))
    _stub_sensor_manager(fake)
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_COMMIT)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, SERVICE_COMMIT)
