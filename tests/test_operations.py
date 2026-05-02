"""Tests for GitManager push / pull / fetch / commit and commit message format."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custom_components.ha_gitops.const import SyncStatus
from custom_components.ha_gitops.git_manager import (
    FileChange,
    GitConflictError,
    GitError,
    GitManager,
)

from .conftest import _git, make_local_commit, push_remote_commit

# ---------------------------------------------------------------------------
# _build_commit_message — docs/architecture.md §8.3
# ---------------------------------------------------------------------------


def test_commit_message_one_file(git_manager: GitManager) -> None:
    msg = git_manager._build_commit_message([FileChange("M", "automations.yaml")])
    assert msg.startswith("Update: automations.yaml\n\n")
    assert "Changed files (1):" in msg
    assert "  M  automations.yaml" in msg
    assert "Pushed via: HA GitOps v" in msg
    assert msg.endswith("Co-authored-by: HA GitOps <ha-gitops@noreply.github.com>")


def test_commit_message_three_files(git_manager: GitManager) -> None:
    msg = git_manager._build_commit_message(
        [
            FileChange("M", "a.yaml"),
            FileChange("M", "b.yaml"),
            FileChange("A", "c.yaml"),
        ]
    )
    assert msg.startswith("Update: a.yaml, b.yaml, c.yaml\n")
    assert "Changed files (3):" in msg


def test_commit_message_four_or_more_files(git_manager: GitManager) -> None:
    msg = git_manager._build_commit_message([FileChange("M", f"f{i}.yaml") for i in range(5)])
    assert msg.startswith("Update: f0.yaml, f1.yaml (+3 more)\n")
    assert "Changed files (5):" in msg


def test_author_args_format(git_manager: GitManager) -> None:
    assert git_manager._author_args() == (
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@local",
    )


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


async def test_push_no_changes_is_noop(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    result = await git_manager_seeded.push()
    assert result.ok
    assert "Nothing to push" in result.message


async def test_push_commits_new_yaml_and_uploads_to_remote(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("turn_on: noop\n", encoding="utf-8")

    result = await git_manager_seeded.push()
    assert result.ok
    assert result.changed_files == ("scripts.yaml",)

    audit = tmp_path / "audit"
    audit.mkdir()
    _git(audit, "clone", seeded_remote, ".")
    assert (audit / "scripts.yaml").exists()


async def test_push_picks_up_yaml_deletion(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "automations.yaml").unlink()

    result = await git_manager_seeded.push()
    assert result.ok
    assert any(f == "automations.yaml" for f in result.changed_files)

    audit = tmp_path / "audit"
    audit.mkdir()
    _git(audit, "clone", seeded_remote, ".")
    assert not (audit / "automations.yaml").exists()


async def test_push_uses_configured_author_via_c_flags(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("k: v\n", encoding="utf-8")
    await git_manager_seeded.push()

    proc = subprocess.run(
        ["git", "-C", str(config_dir), "log", "-1", "--format=%an|%ae"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "Test|test@local"


async def test_push_only_pushes_when_unpushed_local_commits_exist(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    make_local_commit(config_dir, filename="local_only.yaml", content="x: 1")

    result = await git_manager_seeded.push()
    assert result.ok
    assert result.changed_files == ()  # no NEW commit was created

    audit = tmp_path / "audit"
    audit.mkdir()
    _git(audit, "clone", seeded_remote, ".")
    assert (audit / "local_only.yaml").exists()


async def test_push_aborts_on_staged_secrets(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    """Panic guard: if secrets.yaml ends up staged, push aborts and unstages it."""
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("legit: true\n", encoding="utf-8")
    (config_dir / "secrets.yaml").write_text("api_key: leak\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(config_dir), "add", "-f", "secrets.yaml"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(GitError, match="secrets"):
        await git_manager_seeded.push()

    proc = subprocess.run(
        ["git", "-C", str(config_dir), "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "secrets.yaml" not in proc.stdout


async def test_push_rejected_when_remote_ahead(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    push_remote_commit(seeded_remote, tmp_path / "third_party")
    make_local_commit(config_dir, filename="local_only.yaml", content="local: true")

    with pytest.raises(GitError, match="Pull first"):
        await git_manager_seeded.push()


async def test_push_to_empty_remote_is_initial_push(
    git_manager: GitManager,
    config_dir: Path,
    bare_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager.initialize()
    (config_dir / "automations.yaml").write_text("[]\n", encoding="utf-8")

    result = await git_manager.push()
    assert result.ok
    assert "Initial push" in result.message

    audit = tmp_path / "audit"
    audit.mkdir()
    _git(audit, "clone", bare_remote, ".")
    assert (audit / "automations.yaml").exists()


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


async def test_pull_fast_forwards_when_remote_advanced(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    push_remote_commit(seeded_remote, tmp_path / "third_party", filename="new_remote.yaml")

    result = await git_manager_seeded.pull()
    assert result.ok
    assert "new_remote.yaml" in result.changed_files
    assert (config_dir / "new_remote.yaml").exists()


async def test_pull_no_changes_is_noop(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    result = await git_manager_seeded.pull()
    assert result.ok
    assert result.changed_files == ()


async def test_pull_raises_on_divergence(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    make_local_commit(config_dir, filename="local.yaml", content="local: true")
    push_remote_commit(seeded_remote, tmp_path / "third_party", filename="remote.yaml")

    with pytest.raises(GitConflictError):
        await git_manager_seeded.pull()


async def test_pull_raises_when_repo_not_initialized(
    git_manager: GitManager,
) -> None:
    with pytest.raises(GitError, match="not initialized"):
        await git_manager.pull()


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


async def test_fetch_returns_ok(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    result = await git_manager_seeded.fetch()
    assert result.ok


async def test_fetch_makes_remote_changes_visible_in_status(
    git_manager_seeded: GitManager,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    push_remote_commit(seeded_remote, tmp_path / "third_party")

    await git_manager_seeded.fetch()
    assert await git_manager_seeded.get_status() is SyncStatus.BEHIND


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


async def test_commit_skips_when_nothing_to_commit(
    git_manager_seeded: GitManager,
) -> None:
    await git_manager_seeded.initialize()
    result = await git_manager_seeded.commit()
    assert result.ok
    assert "Nothing" in result.message


async def test_commit_uses_custom_message_when_provided(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("k: v\n", encoding="utf-8")

    result = await git_manager_seeded.commit(message="Custom message body")
    assert result.ok
    assert "scripts.yaml" in result.changed_files

    proc = subprocess.run(
        ["git", "-C", str(config_dir), "log", "-1", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "Custom message body"


async def test_commit_does_not_push(
    git_manager_seeded: GitManager,
    config_dir: Path,
    seeded_remote: str,
    tmp_path: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "scripts.yaml").write_text("k: v\n", encoding="utf-8")
    await git_manager_seeded.commit()

    audit = tmp_path / "audit"
    audit.mkdir()
    _git(audit, "clone", seeded_remote, ".")
    assert not (audit / "scripts.yaml").exists()


async def test_commit_aborts_on_secrets(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "secrets.yaml").write_text("api_key: leak\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(config_dir), "add", "-f", "secrets.yaml"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(GitError, match="secrets"):
        await git_manager_seeded.commit()


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------


async def test_get_changed_files_reports_modified_yaml(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "automations.yaml").write_text("- new line\n", encoding="utf-8")

    changes = await git_manager_seeded.get_changed_files()
    names = [c.name for c in changes]
    assert "automations.yaml" in names


async def test_get_changed_files_excludes_secrets(
    git_manager_seeded: GitManager,
    config_dir: Path,
) -> None:
    await git_manager_seeded.initialize()
    (config_dir / "secrets.yaml").write_text("api_key: leak\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(config_dir), "add", "-f", "secrets.yaml"],
        check=True,
        capture_output=True,
    )

    changes = await git_manager_seeded.get_changed_files()
    assert all(c.name != "secrets.yaml" for c in changes)
