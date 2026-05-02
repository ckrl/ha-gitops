"""Smoke tests — keep CI green during scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.ha_gitops.const import (
    DOMAIN,
    GITIGNORE_MARKER,
    GITIGNORE_TEMPLATE,
    SECRETS_FILENAMES,
    SyncStatus,
)
from custom_components.ha_gitops.git_manager import GitManager


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "custom_components" / "ha_gitops" / "manifest.json"


def test_domain_is_stable() -> None:
    assert DOMAIN == "ha_gitops"


def test_manifest_domain_matches_const() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["domain"] == DOMAIN
    assert manifest["iot_class"] == "local_push"


def test_gitignore_template_includes_marker_and_secrets() -> None:
    assert GITIGNORE_MARKER in GITIGNORE_TEMPLATE
    for name in SECRETS_FILENAMES:
        assert name in GITIGNORE_TEMPLATE
    assert ".ha_gitops/" in GITIGNORE_TEMPLATE
    assert ".storage/" in GITIGNORE_TEMPLATE


def test_get_yaml_files_excludes_secrets(config_dir: Path, git_manager: GitManager) -> None:
    (config_dir / "automations.yaml").write_text("[]\n", encoding="utf-8")
    (config_dir / "scripts.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "secrets.yaml").write_text("api_key: hunter2\n", encoding="utf-8")
    (config_dir / "secrets_backup.yaml").write_text("api_key: old\n", encoding="utf-8")
    (config_dir / "team.secrets.yaml").write_text("k: v\n", encoding="utf-8")

    yaml_files = git_manager._get_yaml_files()

    assert "automations.yaml" in yaml_files
    assert "scripts.yaml" in yaml_files
    assert "secrets.yaml" not in yaml_files
    assert "secrets_backup.yaml" not in yaml_files
    assert "team.secrets.yaml" not in yaml_files


def test_build_ssh_env_uses_managed_known_hosts(git_manager: GitManager) -> None:
    env = git_manager._build_ssh_env()
    cmd = env["GIT_SSH_COMMAND"]
    assert "IdentitiesOnly=yes" in cmd
    assert "StrictHostKeyChecking=accept-new" in cmd
    assert "/known_hosts" in cmd
    assert "StrictHostKeyChecking=no" not in cmd


def test_initial_status_is_unknown() -> None:
    assert SyncStatus.UNKNOWN.value == "unknown"
