"""End-to-end Home Assistant setup tests for ha_gitops.

Architecture: docs/architecture.md §5.1 (file structure), §6 (entities),
§8 (GitManager contract) and §12 (release roadmap).

These tests use the `pytest-homeassistant-custom-component` `hass` fixture
to spin up a real HA event loop and verify that ``async_setup`` wires the
GitManager, loads the sensor + button platforms and surfaces the entities
in the state machine. GitManager itself is replaced with an AsyncMock so
the test does not touch the real `git` binary.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ha_gitops.const import DATA_MANAGER, DOMAIN, SyncStatus
from custom_components.ha_gitops.git_manager import GitError


@pytest.fixture(autouse=True)
def _enable_custom_integrations(
    enable_custom_integrations: Any,
) -> None:
    """Make our custom_component discoverable for every test in this module."""
    return None


def _yaml_config(**overrides: Any) -> dict[str, dict[str, Any]]:
    base: dict[str, Any] = {
        "repo_url": "git@example.com:test/config.git",
        "branch": "main",
    }
    base.update(overrides)
    return {DOMAIN: base}


def _fake_manager() -> MagicMock:
    manager = MagicMock(name="GitManager")
    manager.initialize = AsyncMock(return_value=None)
    manager.get_status = AsyncMock(return_value=SyncStatus.UNKNOWN)
    return manager


async def test_setup_no_op_when_domain_missing(hass: HomeAssistant) -> None:
    """Loading the integration with no YAML block must be a successful no-op."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert DOMAIN not in hass.data


async def test_setup_initializes_manager_and_loads_platforms(
    hass: HomeAssistant,
) -> None:
    fake = _fake_manager()
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        ok = await async_setup_component(hass, DOMAIN, _yaml_config())
    await hass.async_block_till_done()

    assert ok is True
    fake.initialize.assert_awaited_once()
    assert hass.data[DOMAIN][DATA_MANAGER] is fake

    sensor_states = [s for s in hass.states.async_all() if s.entity_id.startswith("sensor.")]
    button_states = [s for s in hass.states.async_all() if s.entity_id.startswith("button.")]
    assert len(sensor_states) == 1, f"expected one ha_gitops sensor, got: {sensor_states}"
    assert len(button_states) == 2, f"expected pull+push buttons, got: {button_states}"


async def test_setup_uses_default_branch_when_not_provided(
    hass: HomeAssistant,
) -> None:
    fake = _fake_manager()
    minimal = {DOMAIN: {"repo_url": "git@example.com:test/config.git"}}
    with patch("custom_components.ha_gitops.GitManager", return_value=fake) as gm_cls:
        ok = await async_setup_component(hass, DOMAIN, minimal)
    await hass.async_block_till_done()

    assert ok is True
    kwargs = gm_cls.call_args.kwargs
    assert kwargs["branch"] == "main"
    assert kwargs["repo_url"] == "git@example.com:test/config.git"


async def test_setup_returns_false_when_initialize_fails(
    hass: HomeAssistant,
) -> None:
    fake = MagicMock(name="GitManager")
    fake.initialize = AsyncMock(side_effect=GitError("ssh key missing"))
    with patch("custom_components.ha_gitops.GitManager", return_value=fake):
        ok = await async_setup_component(hass, DOMAIN, _yaml_config())

    assert ok is False
    assert DATA_MANAGER not in hass.data.get(DOMAIN, {})
