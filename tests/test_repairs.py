"""Tests for ha_gitops repairs fix flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_gitops.const import ISSUE_PULLED_CONFIG_RELOAD
from custom_components.ha_gitops.repairs import (
    PulledConfigReloadRepairFlow,
    async_create_fix_flow,
)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: Any) -> None:
    return None


async def test_create_fix_flow_pulled_issue_returns_reload_flow() -> None:
    hass = MagicMock()
    flow = await async_create_fix_flow(hass, ISSUE_PULLED_CONFIG_RELOAD, None)
    assert isinstance(flow, PulledConfigReloadRepairFlow)


async def test_create_fix_flow_unknown_issue_returns_confirm() -> None:
    hass = MagicMock()
    flow = await async_create_fix_flow(hass, "other_issue", None)
    assert isinstance(flow, ConfirmRepairFlow)


async def test_pulled_reload_flow_confirm_calls_service() -> None:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)

    flow = PulledConfigReloadRepairFlow()
    flow.hass = hass

    shown = await flow.async_step_confirm(None)
    assert shown["type"] == FlowResultType.FORM

    done = await flow.async_step_confirm({})
    assert done["type"] == FlowResultType.CREATE_ENTRY
    hass.services.async_call.assert_awaited_once_with(
        "homeassistant",
        "reload_core_config",
        {},
        blocking=True,
    )
