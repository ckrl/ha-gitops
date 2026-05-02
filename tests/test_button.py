"""Unit tests for the ha_gitops Pull/Push buttons.

Architecture: docs/architecture.md §6.1 (Buttons), §7.1 (Push action),
§8 (GitManager contract), §10 (Security — sanitized notifications).

A MagicMock GitManager + MagicMock hass keep these tests fast. End-to-end
loading inside Home Assistant is exercised by tests/test_setup.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory

from custom_components.ha_gitops.button import HaGitopsPullButton, HaGitopsPushButton
from custom_components.ha_gitops.const import DOMAIN
from custom_components.ha_gitops.git_manager import GitError, GitResult


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _last_notification(hass: MagicMock) -> dict[str, str]:
    """Extract the {title, message, notification_id} payload from the call."""
    hass.services.async_call.assert_awaited()
    call = hass.services.async_call.call_args
    domain, service, payload = call.args[0], call.args[1], call.args[2]
    assert domain == "persistent_notification"
    assert service == "create"
    return payload


# ---------------------------------------------------------------------------
# Pull button
# ---------------------------------------------------------------------------


async def test_pull_button_metadata() -> None:
    hass = _make_hass()
    btn = HaGitopsPullButton(hass, MagicMock())
    assert btn.unique_id == f"{DOMAIN}_pull"
    assert btn.name == "Pull"
    assert btn.icon == "mdi:cloud-download-outline"
    assert btn.entity_category is EntityCategory.CONFIG


async def test_pull_button_invokes_manager_pull() -> None:
    hass = _make_hass()
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(ok=True, message="up to date", changed_files=())
    )
    await HaGitopsPullButton(hass, manager).async_press()
    manager.pull.assert_awaited_once()


async def test_pull_button_silent_when_no_changes() -> None:
    """Successful pull with no changed files must not spam notifications."""
    hass = _make_hass()
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(ok=True, message="up to date", changed_files=())
    )
    await HaGitopsPullButton(hass, manager).async_press()
    hass.services.async_call.assert_not_called()


async def test_pull_button_notifies_on_changed_files() -> None:
    hass = _make_hass()
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(
            ok=True,
            message="ff",
            changed_files=("automations.yaml", "scripts.yaml"),
        )
    )
    await HaGitopsPullButton(hass, manager).async_press()
    payload = _last_notification(hass)
    assert "config updated" in payload["title"].lower()
    assert "reload" in payload["message"].lower()
    assert payload["notification_id"] == f"{DOMAIN}_pull"


async def test_pull_button_notifies_on_git_error() -> None:
    hass = _make_hass()
    manager = MagicMock()
    manager.pull = AsyncMock(side_effect=GitError("Pull first."))
    await HaGitopsPullButton(hass, manager).async_press()
    payload = _last_notification(hass)
    assert "pull failed" in payload["title"].lower()
    assert "Pull first." in payload["message"]


async def test_pull_button_does_not_swallow_non_git_exceptions() -> None:
    """Non-GitError must propagate so HA's exception handler sees it.

    Logic mirrors button.py: only GitError is caught; everything else is
    a programming bug and should crash loudly during development.
    """
    hass = _make_hass()
    manager = MagicMock()
    manager.pull = AsyncMock(side_effect=RuntimeError("logic bug"))
    btn = HaGitopsPullButton(hass, manager)
    try:
        await btn.async_press()
    except RuntimeError as exc:
        assert "logic bug" in str(exc)
    else:  # pragma: no cover - sanity
        raise AssertionError("RuntimeError should have propagated")


# ---------------------------------------------------------------------------
# Push button
# ---------------------------------------------------------------------------


async def test_push_button_metadata() -> None:
    hass = _make_hass()
    btn = HaGitopsPushButton(hass, MagicMock())
    assert btn.unique_id == f"{DOMAIN}_push"
    assert btn.name == "Push"
    assert btn.icon == "mdi:cloud-upload-outline"
    assert btn.entity_category is EntityCategory.CONFIG


async def test_push_button_invokes_manager_push() -> None:
    hass = _make_hass()
    manager = MagicMock()
    manager.push = AsyncMock(return_value=GitResult(ok=True, message="pushed", changed_files=()))
    await HaGitopsPushButton(hass, manager).async_press()
    manager.push.assert_awaited_once()
    hass.services.async_call.assert_not_called()


async def test_push_button_notifies_on_git_error() -> None:
    hass = _make_hass()
    manager = MagicMock()
    manager.push = AsyncMock(side_effect=GitError("push rejected: remote ahead"))
    await HaGitopsPushButton(hass, manager).async_press()
    payload = _last_notification(hass)
    assert "push failed" in payload["title"].lower()
    assert "remote ahead" in payload["message"]
    assert payload["notification_id"] == f"{DOMAIN}_push"
