"""Constants for the ha_gitops integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "ha_gitops"

CONF_REPO_URL: Final = "repo_url"
CONF_BRANCH: Final = "branch"
CONF_SSH_KEY_PATH: Final = "ssh_key_path"
CONF_GIT_AUTHOR_NAME: Final = "git_author_name"
CONF_GIT_AUTHOR_EMAIL: Final = "git_author_email"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_BRANCH: Final = "main"
DEFAULT_SSH_DIR: Final = ".ha_gitops"
DEFAULT_SSH_KEY_FILENAME: Final = "id_ed25519"
DEFAULT_KNOWN_HOSTS_FILENAME: Final = "known_hosts"
DEFAULT_AUTHOR_NAME: Final = "Home Assistant"
DEFAULT_AUTHOR_EMAIL: Final = "homeassistant@local"
DEFAULT_SCAN_INTERVAL: Final = 300  # seconds

DATA_MANAGER: Final = "manager"
DATA_SCAN_INTERVAL: Final = "scan_interval"
DATA_LAST_RESULT: Final = "last_result"

PLATFORMS: Final = ("sensor", "button")


class SyncStatus(StrEnum):
    """Synchronization status reported by sensor.ha_gitops_status."""

    CLEAN = "clean"
    MODIFIED = "modified"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"
    ERROR = "error"
    UNKNOWN = "unknown"


GITIGNORE_MARKER: Final = "# ha-gitops: managed exclusions — do not remove"

GITIGNORE_TEMPLATE: Final = f"""{GITIGNORE_MARKER}

# Secrets — NEVER commit
secrets.yaml
secrets_backup.yaml
*.secrets.yaml

# SSH keys and integration internals
.ha_gitops/

# Home Assistant runtime state
.storage/
.cloud/
core_*
home-assistant_v2.db
home-assistant_v2.db-shm
home-assistant_v2.db-wal
home-assistant.log
home-assistant.log.1

# Temporary files
*.tmp
*.bak
*.pyc
__pycache__/
"""

CO_AUTHOR_TRAILER: Final = "Co-authored-by: HA GitOps <ha-gitops@noreply.github.com>"

SECRETS_FILENAMES: Final = ("secrets.yaml", "secrets_backup.yaml")
