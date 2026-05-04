"""End-to-end Home Assistant setup tests for ha_gitops.

Architecture: docs/architecture.md §5.1 (file structure), §6 (configuration),
§8 (GitManager contract) and §12 (release roadmap).

Uses the `pytest-homeassistant-custom-component` `hass` fixture with a
`MockConfigEntry` and `async_setup_entry` (Config Flow path). GitManager is
replaced with an AsyncMock so tests do not run the real `git` binary.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_gitops.const import (
    CONF_BRANCH,
    CONF_GIT_AUTHOR_EMAIL,
    CONF_GIT_AUTHOR_NAME,
    CONF_REPO_URL,
    CONF_SCAN_INTERVAL,
    CONF_SSH_KEY_PATH,
    DATA_MANAGER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SyncStatus,
)
from custom_components.ha_gitops.git_manager import GitError


@pytest.fixture(autouse=True)
def _enable_custom_integrations(
    enable_custom_integrations: Any,
) -> None:
    """Make our custom_component discoverable for every test in this module."""
    return None


def _entry_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        CONF_REPO_URL: "git@example.com:test/config.git",
        CONF_BRANCH: "main",
        CONF_GIT_AUTHOR_NAME: "Test",
        CONF_GIT_AUTHOR_EMAIL: "test@local",
        CONF_SSH_KEY_PATH: "/config/.ha_gitops/id_ed25519",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    }
    base.update(overrides)
    return base


def _fake_manager() -> MagicMock:
    manager = MagicMock(name="GitManager")
    manager.initialize = AsyncMock(return_value=None)
    manager.get_status = AsyncMock(return_value=SyncStatus.UNKNOWN)
    manager.fetch = AsyncMock(return_value=None)
    return manager


async def test_async_setup_without_entries_does_not_touch_domain_data(
    hass: HomeAssistant,
) -> None:
    """Top-level async_setup must not require YAML or pre-create hass.data."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert DOMAIN not in hass.data


async def test_setup_entry_initializes_manager_and_creates_entities(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA GitOps",
        data=_entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    fake = _fake_manager()
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    fake.initialize.assert_awaited_once()
    assert hass.data[DOMAIN][entry.entry_id][DATA_MANAGER] is fake

    sensor_states = [s for s in hass.states.async_all() if s.entity_id.startswith("sensor.")]
    button_states = [s for s in hass.states.async_all() if s.entity_id.startswith("button.")]
    assert len(sensor_states) == 1, f"expected one ha_gitops sensor, got: {sensor_states}"
    assert len(button_states) == 3, f"expected pull+fetch+push buttons, got: {button_states}"


async def test_setup_entry_fails_when_initialize_raises(
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
    fake.initialize = AsyncMock(side_effect=GitError("ssh key missing"))
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is not ConfigEntryState.LOADED
