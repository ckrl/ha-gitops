"""Tests for GitManager.initialize and the _run_git plumbing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custom_components.ha_gitops.const import GITIGNORE_MARKER
from custom_components.ha_gitops.git_manager import GitError, GitManager, normalize_ssh_key_path


def test_normalize_ssh_key_path_default_and_relative(config_dir: Path) -> None:
    d = config_dir.resolve()
    assert normalize_ssh_key_path(d, "") == d / ".ha_gitops" / "id_ed25519"
    assert normalize_ssh_key_path(d, "  ") == d / ".ha_gitops" / "id_ed25519"
    assert (
        normalize_ssh_key_path(d, ".ha_gitops/id_ed25519")
        == (d / ".ha_gitops" / "id_ed25519").resolve()
    )
    assert normalize_ssh_key_path(d, "/tmp/abs_key") == Path("/tmp/abs_key")


async def test_run_git_success_returns_stdout(git_manager: GitManager) -> None:
    rc, stdout, _ = await git_manager._run_git("--version")
    assert rc == 0
    assert stdout.startswith("git version")


async def test_run_git_failure_raises_giterror(git_manager: GitManager) -> None:
    with pytest.raises(GitError, match="rev-parse"):
        await git_manager._run_git("rev-parse", "HEAD")


async def test_run_git_failure_returns_when_check_false(
    git_manager: GitManager,
) -> None:
    rc, _, stderr = await git_manager._run_git("rev-parse", "HEAD", check=False)
    assert rc != 0
    assert stderr  # should carry git's diagnostic


def test_git_process_env_injects_safe_directory(git_manager: GitManager) -> None:
    """Git 2.35+ dubious ownership is bypassed per-invocation (see docs/architecture.md §4.2)."""
    env = git_manager._git_process_env()
    n = int(env["GIT_CONFIG_COUNT"])
    assert n >= 1
    assert env[f"GIT_CONFIG_KEY_{n - 1}"] == "safe.directory"
    assert env[f"GIT_CONFIG_VALUE_{n - 1}"] == str(git_manager.config_dir.resolve())


def test_git_process_env_merges_existing_git_config_count(
    git_manager: GitManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.email")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "parent@example.com")
    env = git_manager._git_process_env()
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "user.email"
    assert env["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_1"] == str(git_manager.config_dir.resolve())


async def test_initialize_creates_repo_and_gitignore(
    git_manager: GitManager, config_dir: Path
) -> None:
    await git_manager.initialize()
    assert (config_dir / ".git").is_dir()

    gitignore = (config_dir / ".gitignore").read_text(encoding="utf-8")
    assert GITIGNORE_MARKER in gitignore
    assert "secrets.yaml" in gitignore
    assert ".storage/" in gitignore
    assert ".ha_gitops/" in gitignore


async def test_initialize_creates_ha_gitops_directory(
    git_manager: GitManager, config_dir: Path
) -> None:
    await git_manager.initialize()
    assert (config_dir / ".ha_gitops").is_dir()


async def test_initialize_is_idempotent(git_manager: GitManager, config_dir: Path) -> None:
    await git_manager.initialize()
    first = (config_dir / ".gitignore").read_text(encoding="utf-8")
    await git_manager.initialize()
    second = (config_dir / ".gitignore").read_text(encoding="utf-8")
    assert first == second
    assert second.count(GITIGNORE_MARKER) == 1


async def test_initialize_appends_to_existing_gitignore(
    git_manager: GitManager, config_dir: Path
) -> None:
    user_content = "# user-managed entries\nmy_local_notes.yaml\n"
    (config_dir / ".gitignore").write_text(user_content, encoding="utf-8")

    await git_manager.initialize()

    final = (config_dir / ".gitignore").read_text(encoding="utf-8")
    assert final.startswith(user_content)
    assert GITIGNORE_MARKER in final
    assert "secrets.yaml" in final


async def test_initialize_sets_origin_to_repo_url(
    git_manager: GitManager, config_dir: Path, bare_remote: str
) -> None:
    await git_manager.initialize()
    proc = subprocess.run(
        ["git", "-C", str(config_dir), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == bare_remote


async def test_initialize_updates_origin_when_url_changes(
    config_dir: Path, bare_remote: str, tmp_path: Path
) -> None:
    subprocess.run(
        ["git", "-C", str(config_dir), "init", "-b", "main"],
        check=True,
        capture_output=True,
    )
    stale = f"file://{tmp_path}/stale.git"
    subprocess.run(
        ["git", "-C", str(config_dir), "remote", "add", "origin", stale],
        check=True,
        capture_output=True,
    )

    manager = GitManager(
        config_dir=config_dir,
        repo_url=bare_remote,
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )
    await manager.initialize()

    proc = subprocess.run(
        ["git", "-C", str(config_dir), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == bare_remote


async def test_initialize_checks_out_branch_from_seeded_remote(
    git_manager_seeded: GitManager, config_dir: Path
) -> None:
    await git_manager_seeded.initialize()

    head = subprocess.run(
        ["git", "-C", str(config_dir), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip() == "main"
    assert (config_dir / "automations.yaml").exists()


async def test_initialize_does_not_fail_on_unreachable_remote(
    config_dir: Path, tmp_path: Path
) -> None:
    unreachable = f"file://{tmp_path}/does-not-exist.git"
    manager = GitManager(
        config_dir=config_dir,
        repo_url=unreachable,
        branch="main",
        ssh_key_path=config_dir / ".ha_gitops" / "id_ed25519",
        author_name="Test",
        author_email="test@local",
    )
    await manager.initialize()
    assert (config_dir / ".git").is_dir()
    assert (config_dir / ".gitignore").exists()
