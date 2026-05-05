"""Unit tests for the ha_gitops Pull / Fetch / Push buttons.

Architecture: docs/architecture.md §7.1 (Pull / Fetch / Push buttons),
§8 (GitManager contract), §10 (Security — sanitized notifications).

A MagicMock GitManager + MagicMock hass keep these tests fast. End-to-end
loading inside Home Assistant is exercised by tests/test_setup.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EntityCategory

from custom_components.ha_gitops.button import (
    HaGitopsFetchButton,
    HaGitopsPullButton,
    HaGitopsPushButton,
)
from custom_components.ha_gitops.const import (
    DATA_AUTO_RELOAD_AFTER_PULL,
    DOMAIN,
    ISSUE_PULLED_CONFIG_RELOAD,
)
from custom_components.ha_gitops.git_manager import GitError, GitResult


def _mock_config_entry(entry_id: str = "test_entry_id") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "HA GitOps"
    return entry


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
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
    entry = _mock_config_entry("e_pull")
    btn = HaGitopsPullButton(hass, entry, MagicMock())
    assert btn.unique_id == "e_pull_pull"
    assert btn.name == "Pull"
    assert btn.icon == "mdi:cloud-download-outline"
    assert btn.entity_category is EntityCategory.CONFIG


async def test_pull_button_invokes_manager_pull() -> None:
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(ok=True, message="up to date", changed_files=())
    )
    await HaGitopsPullButton(hass, entry, manager).async_press()
    manager.pull.assert_awaited_once()


async def test_pull_button_silent_when_no_changes() -> None:
    """Successful pull with no changed files must not spam notifications."""
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(ok=True, message="up to date", changed_files=())
    )
    await HaGitopsPullButton(hass, entry, manager).async_press()
    hass.services.async_call.assert_not_called()


async def test_pull_button_auto_reload_skips_repairs() -> None:
    hass = _make_hass()
    entry = _mock_config_entry("e_auto")
    hass.data = {DOMAIN: {entry.entry_id: {DATA_AUTO_RELOAD_AFTER_PULL: True}}}
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(
            ok=True,
            message="ff",
            changed_files=("automations.yaml",),
        )
    )
    with patch("custom_components.ha_gitops.button.ir.async_create_issue") as mock_issue:
        await HaGitopsPullButton(hass, entry, manager).async_press()
    mock_issue.assert_not_called()
    assert hass.services.async_call.await_count >= 2
    first = hass.services.async_call.await_args_list[0]
    assert first.args[0] == "homeassistant"
    assert first.args[1] == "reload_core_config"


async def test_pull_button_notifies_on_changed_files() -> None:
    hass = _make_hass()
    entry = _mock_config_entry("e1")
    manager = MagicMock()
    manager.pull = AsyncMock(
        return_value=GitResult(
            ok=True,
            message="ff",
            changed_files=("automations.yaml", "scripts.yaml"),
        )
    )
    with patch("custom_components.ha_gitops.button.ir.async_create_issue") as mock_issue:
        await HaGitopsPullButton(hass, entry, manager).async_press()
    payload = _last_notification(hass)
    assert "config updated" in payload["title"].lower()
    assert "reload" in payload["message"].lower()
    assert "my.home-assistant.io" in payload["message"]
    assert payload["notification_id"] == "e1_pull"
    mock_issue.assert_called_once()
    _call = mock_issue.call_args
    assert _call.args[2] == ISSUE_PULLED_CONFIG_RELOAD


async def test_pull_button_notifies_on_git_error() -> None:
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.pull = AsyncMock(side_effect=GitError("Pull first."))
    await HaGitopsPullButton(hass, entry, manager).async_press()
    payload = _last_notification(hass)
    assert "pull failed" in payload["title"].lower()
    assert "Pull first." in payload["message"]


async def test_pull_button_does_not_swallow_non_git_exceptions() -> None:
    """Non-GitError must propagate so HA's exception handler sees it.

    Logic mirrors button.py: only GitError is caught; everything else is
    a programming bug and should crash loudly during development.
    """
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.pull = AsyncMock(side_effect=RuntimeError("logic bug"))
    btn = HaGitopsPullButton(hass, entry, manager)
    try:
        await btn.async_press()
    except RuntimeError as exc:
        assert "logic bug" in str(exc)
    else:  # pragma: no cover - sanity
        raise AssertionError("RuntimeError should have propagated")


# ---------------------------------------------------------------------------
# Fetch button
# ---------------------------------------------------------------------------


async def test_fetch_button_metadata() -> None:
    hass = _make_hass()
    entry = _mock_config_entry("e_fetch")
    btn = HaGitopsFetchButton(hass, entry, MagicMock())
    assert btn.unique_id == "e_fetch_fetch"
    assert btn.name == "Fetch"
    assert btn.icon == "mdi:cloud-sync-outline"
    assert btn.entity_category is EntityCategory.CONFIG


async def test_fetch_button_invokes_manager_fetch() -> None:
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.fetch = AsyncMock(return_value=GitResult(ok=True, message="Fetched", changed_files=()))
    await HaGitopsFetchButton(hass, entry, manager).async_press()
    manager.fetch.assert_awaited_once()
    hass.services.async_call.assert_not_called()


async def test_fetch_button_notifies_on_git_error() -> None:
    hass = _make_hass()
    entry = _mock_config_entry("e3")
    manager = MagicMock()
    manager.fetch = AsyncMock(side_effect=GitError("network down"))
    await HaGitopsFetchButton(hass, entry, manager).async_press()
    payload = _last_notification(hass)
    assert "fetch failed" in payload["title"].lower()
    assert "network down" in payload["message"]
    assert payload["notification_id"] == "e3_fetch"


async def test_fetch_button_does_not_swallow_non_git_exceptions() -> None:
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.fetch = AsyncMock(side_effect=RuntimeError("logic bug"))
    btn = HaGitopsFetchButton(hass, entry, manager)
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
    entry = _mock_config_entry("e_push")
    btn = HaGitopsPushButton(hass, entry, MagicMock())
    assert btn.unique_id == "e_push_push"
    assert btn.name == "Push"
    assert btn.icon == "mdi:cloud-upload-outline"
    assert btn.entity_category is EntityCategory.CONFIG


async def test_push_button_invokes_manager_push() -> None:
    hass = _make_hass()
    entry = _mock_config_entry()
    manager = MagicMock()
    manager.push = AsyncMock(return_value=GitResult(ok=True, message="pushed", changed_files=()))
    await HaGitopsPushButton(hass, entry, manager).async_press()
    manager.push.assert_awaited_once()
    hass.services.async_call.assert_not_called()


async def test_push_button_notifies_on_git_error() -> None:
    hass = _make_hass()
    entry = _mock_config_entry("e2")
    manager = MagicMock()
    manager.push = AsyncMock(side_effect=GitError("push rejected: remote ahead"))
    await HaGitopsPushButton(hass, entry, manager).async_press()
    payload = _last_notification(hass)
    assert "push failed" in payload["title"].lower()
    assert "remote ahead" in payload["message"]
    assert payload["notification_id"] == "e2_push"
