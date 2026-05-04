"""Repairs platform for ha_gitops — fix flows for issue_registry entries."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .const import ISSUE_PULLED_CONFIG_RELOAD


class PulledConfigReloadRepairFlow(RepairsFlow):
    """Confirm step runs `homeassistant.reload_core_config` then closes the issue."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            await self.hass.services.async_call(
                "homeassistant",
                "reload_core_config",
                {},
                blocking=True,
            )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Dispatch repair flows by issue_id."""
    if issue_id == ISSUE_PULLED_CONFIG_RELOAD:
        return PulledConfigReloadRepairFlow()
    return ConfirmRepairFlow()
