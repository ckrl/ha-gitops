# Architecture

This is the public design-of-record for `ha_gitops`. The `.cursor/rules/`
under this repository, the docstrings, and the tests cite paragraph
numbers from this document. Numbering matches the original internal
specification so future cross-references stay stable.

---

## 1. Problem

Home Assistant configuration lives as YAML files under `/config/*.yaml`.
Out of the box these files are not version controlled: an accidental
edit, a botched device replacement, or a faulty automation can be hard
to roll back, compare across instances, or audit over time.

## 2. Solution

`ha_gitops` is a HACS custom integration that wires the HA configuration
directory to a remote git repository and exposes idempotent `pull` /
`push` operations through HA buttons plus a synchronization status
sensor. SSH is the supported authentication scheme for the MVP; HTTPS
and a UI Config Flow come in a later release.

## 3. Non-goals

- Synchronizing `.storage/`, `.cloud/`, `core_*` or any other Home
  Assistant runtime state.
- Including `secrets.yaml` in the repository — this is a hard policy,
  not a configurable option.
- Auto-merge on conflicts. Pulls are fast-forward only; conflicts
  surface as a `diverged` status with a notification asking the user to
  intervene manually.
- Integration with Home Assistant Backup.
- Driving multiple repositories from a single HA instance (out of scope
  for the MVP).

---

## 4. Architecture

### 4.1 Config dir is the git working tree

`/config/` itself becomes the git working directory. This is the standard
GitOps practice for Home Assistant and avoids an extra staging directory
that would have to be kept in sync with the live config.

Consequences:

- `.git/` lives in `/config/` — Home Assistant ignores it.
- `.gitignore` is created and maintained by the integration in
  `/config/.gitignore`.
- SSH keys and other integration internals live in `/config/.ha_gitops/`,
  which is excluded from the repository.

### 4.2 Git backend

| Option                   | MVP / Release                                          |
| ------------------------ | ------------------------------------------------------ |
| `subprocess` + `git` CLI | **MVP** — full control, no Python dependency           |
| `gitpython`              | **Release** — same `GitManager` API, friendlier errors |
| `dulwich` / `pygit2`     | rejected — SSH/install complexity in the HA runtimes   |

The migration from subprocess to GitPython does not change the public
`GitManager` API (see §8.1).

### 4.3 SSH authentication

`/config/.ha_gitops/` holds the integration's SSH material:

```
/config/.ha_gitops/
├── id_ed25519          # private key, chmod 600
├── id_ed25519.pub      # public key (shown in UI in Release)
└── known_hosts         # managed known_hosts file
```

Git operations run with the following environment:

```
GIT_SSH_COMMAND="ssh -i /config/.ha_gitops/id_ed25519
                     -o UserKnownHostsFile=/config/.ha_gitops/known_hosts
                     -o StrictHostKeyChecking=accept-new
                     -o IdentitiesOnly=yes"
```

`StrictHostKeyChecking=accept-new` accepts new hosts on first contact
and refuses changed keys afterwards. `IdentitiesOnly=yes` prevents the
ssh agent or the host's `~/.ssh/config` from injecting unrelated
identities.

### 4.4 Managed .gitignore

The integration creates and appends a marked block to `/config/.gitignore`
on first initialization. The block is identified by a marker line so
the file can be edited freely outside the block — re-running
`initialize()` is idempotent.

```gitignore
# ha-gitops: managed exclusions — do not remove

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
```

### 4.5 Component diagram

```
┌──────────────────────────────────────────────────────────┐
│                    Home Assistant Core                   │
│                                                          │
│   button.ha_gitops_pull / push      sensor.ha_gitops_*   │
│                       │                    │             │
│                       └────────┬───────────┘             │
│                                │                         │
│                          GitManager                      │
│                       (git_manager.py)                   │
│                                │                         │
│                  asyncio.create_subprocess_exec          │
└────────────────────────────────┼─────────────────────────┘
                                 │  GIT_SSH_COMMAND
                          ┌──────▼──────┐
                          │  git CLI    │
                          └──────┬──────┘
                                 │  SSH
                          ┌──────▼──────────────┐
                          │  Remote git host    │
                          │  (GitHub / GitLab / │
                          │   self-hosted)      │
                          └─────────────────────┘
```

---

## 5. Repository layout

### 5.1 File structure

```
ha-gitops/
├── custom_components/
│   └── ha_gitops/
│       ├── __init__.py          # async_setup, platform forwarding
│       ├── manifest.json        # HACS manifest
│       ├── const.py             # DOMAIN, CONF_*, defaults, SyncStatus
│       ├── git_manager.py       # GitManager — single git entry point
│       ├── sensor.py            # SensorEntity: ha_gitops_status
│       ├── button.py            # ButtonEntity: pull, push
│       ├── config_flow.py       # UI Config Flow (Release)
│       ├── services.yaml        # service descriptors
│       ├── strings.json         # UI strings (en)
│       └── translations/        # localized strings
├── tests/
│   ├── conftest.py
│   ├── test_initialize.py
│   ├── test_status.py
│   └── test_operations.py
├── docs/
│   └── architecture.md          # this document
├── hacs.json                    # HACS metadata
├── README.md
├── LICENSE
├── pyproject.toml               # dev deps, ruff/black/mypy/pytest config
└── .github/workflows/
    ├── validate.yml             # hassfest + HACS + ruff + black + pytest
    └── release.yml              # tagged releases
```

### 5.2 manifest.json

Required fields:

```json
{
  "domain": "ha_gitops",
  "name": "HA GitOps",
  "version": "X.Y.Z",
  "documentation": "https://github.com/<owner>/ha-gitops",
  "issue_tracker": "https://github.com/<owner>/ha-gitops/issues",
  "requirements": [],
  "dependencies": [],
  "codeowners": ["@<owner>"],
  "iot_class": "local_push",
  "config_flow": false
}
```

`requirements` is empty in the MVP — the integration depends on the
`git` binary, which is not a Python dependency. Release adds
`"GitPython>=3.1"` and flips `config_flow` to `true`.

### 5.3 hacs.json

```json
{
  "name": "HA GitOps",
  "filename": "ha_gitops.zip",
  "content_in_root": false,
  "hide_default_branch": false,
  "homeassistant": "2024.1.0"
}
```

---

## 6. Configuration (YAML, MVP)

```yaml
# configuration.yaml
ha_gitops:
  repo_url: "git@github.com:username/ha-config.git"
  branch: "main"
  ssh_key_path: "/config/.ha_gitops/id_ed25519" # optional
  git_author_name: "Home Assistant"             # optional
  git_author_email: "homeassistant@local"       # optional
  scan_interval: 300                            # seconds between status fetches
```

Release adds a UI Config Flow that drives the same options plus an
SSH key generator and a "Test connection" step.

---

## 7. Entities

### 7.1 Buttons

#### `button.ha_gitops_pull`

- **Action**: `git fetch` + `git merge --ff-only origin/<branch>`.
- **Success with changes**: status sensor refreshed, persistent
  notification "Config updated; reload Home Assistant to apply".
- **Conflict / diverged**: status `error`/`diverged`, notification with
  details, **no merge applied**.
- **No changes**: status `clean`, silent success.

#### `button.ha_gitops_push`

A single atomic action from the user's perspective:

```
git add <yaml files>     (via _get_yaml_files, secrets excluded)
   │
git diff --cached --quiet?
 ├── NO  (changes staged) → git commit  →  git push origin <branch>
 └── YES (nothing staged) → unpushed local commits?
                                ├── YES → git push origin <branch>
                                └── NO  → no-op, status clean
```

- **Success**: status sensor refreshed, log entry on success.
- **Push rejected (remote ahead)**: error rewritten to "Pull first.",
  status `error`, notification.
- **Network error**: status `error`, notification.

#### `button.ha_gitops_fetch` (Release)

Refreshes remote tracking refs without modifying the working tree.

### 7.2 Status sensor — `sensor.ha_gitops_status`

| State      | Condition                                              |
| ---------- | ------------------------------------------------------ |
| `clean`    | Local HEAD equals remote HEAD; no working changes      |
| `modified` | Uncommitted or untracked YAML changes present          |
| `ahead`    | Local commits not yet pushed                           |
| `behind`   | Remote commits not yet pulled                          |
| `diverged` | Histories diverged — manual action required           |
| `error`    | Last operation failed                                  |
| `unknown`  | Repository not initialized or remote unreachable       |

Attributes: `last_operation`, `last_operation_time` (ISO),
`last_error`, `local_commit` (short hash), `remote_commit`.

Release adds `sensor.ha_gitops_local_commit`,
`sensor.ha_gitops_remote_commit`, `sensor.ha_gitops_changed_files`,
`sensor.ha_gitops_last_sync`.

---

## 8. GitManager

### 8.1 Public API

`GitManager` is the single entry point for every git interaction. The
public surface is stable across the MVP-to-Release backend migration.

```python
class GitManager:
    def __init__(self, config_dir, repo_url, branch, ssh_key_path,
                 author_name, author_email): ...

    # Lifecycle
    async def initialize(self) -> None: ...

    # Operations (return GitResult)
    async def push(self) -> GitResult: ...
    async def pull(self) -> GitResult: ...
    async def fetch(self) -> GitResult: ...
    async def commit(self, message: str | None = None) -> GitResult: ...

    # Inspection
    async def get_status(self) -> SyncStatus: ...
    async def get_local_commit(self) -> CommitInfo | None: ...
    async def get_remote_commit(self) -> CommitInfo | None: ...
    async def get_changed_files(self) -> list[FileChange]: ...

    # SSH (Release)
    async def generate_ssh_key(self) -> str: ...
    async def test_connection(self) -> bool: ...
```

Internal helpers (`_run_git`, `_build_ssh_env`, `_get_yaml_files`,
`_stage_yaml_files`, `_build_commit_message`, `_author_args`,
`_classify_push_error`) are free to evolve.

### 8.2 Status algorithm

```
1. fetch origin (soft — network errors degrade to a warning, not an error)
2. git status --porcelain               → if non-empty: "modified"
3. local  = git rev-parse HEAD
   remote = git rev-parse origin/<branch>
   ├── local  not found                 → "unknown"
   ├── remote not found                 → "unknown"
   └── local == remote                  → "clean"
4. base = git merge-base HEAD origin/<branch>
   ├── base == remote                   → "ahead"
   ├── base == local                    → "behind"
   └── otherwise                        → "diverged"
```

### 8.3 Commit message format

#### Subject (adaptive)

| Files | Subject                                            |
| ----- | -------------------------------------------------- |
| 1     | `Update: automations.yaml`                         |
| 2–3   | `Update: automations.yaml, scripts.yaml`           |
| 4+    | `Update: automations.yaml, scripts.yaml (+N more)` |

Always English. No `chore:` / `fix:` Conventional Commits prefix —
unnecessary noise for a home configuration.

#### Body

```
Changed files (N):
  M  automations.yaml
  A  new_scene.yaml
  D  old_script.yaml

Timestamp: 2026-05-01T10:30:00+03:00
Pushed via: HA GitOps v0.1.0
```

Status letters use `git diff --name-status` conventions
(`M`/`A`/`D`/`R`).

#### Trailer

```
Co-authored-by: HA GitOps <ha-gitops@noreply.github.com>
```

#### Author / committer

The configured `git_author_name` / `git_author_email` are passed through
per-call `-c user.name=…` / `-c user.email=…` flags so the host's
global `git config` is never touched.

---

## 9. Edge cases

| Scenario                              | Behaviour                                                       |
| ------------------------------------- | --------------------------------------------------------------- |
| `git` binary missing                  | Setup fails with a clear error, HA not affected                 |
| Remote unreachable                    | Status `error`, retried on the next scan interval               |
| Conflict during pull                  | Status `diverged`, no merge applied, notification               |
| Push rejected (remote ahead)          | Error rewritten to "Pull first.", notification                  |
| SSH key missing or invalid            | Setup error with remediation hint                               |
| Empty commit (nothing to push)        | No-op, status stays `clean`                                     |
| HA restart mid-operation              | Operation aborts, status refreshes on the next scan             |
| User deleted the `.gitignore` block   | Block recreated on the next operation, warning logged           |
| `secrets.yaml` ends up staged         | Panic guard: unstage, abort, error notification (see §10.1)     |

---

## 10. Security

### 10.1 secrets.yaml — double protection

1. **`.gitignore`** — `secrets.yaml`, `secrets_backup.yaml`,
   `*.secrets.yaml` are part of the managed block (§4.4).
2. **In-code filter** — `_get_yaml_files()` excludes secrets-named
   files before staging.
3. **Pre-push panic guard** — `git diff --cached --name-only` is
   checked; if a secrets-named file appears in the index it is
   unstaged with `git reset HEAD <file>`, the operation aborts, and the
   user is notified.

There is no flag to opt secrets in. Ever.

### 10.2 SSH keys

- Stored under `/config/.ha_gitops/`, mode `600`, ED25519 only.
- `.ha_gitops/` is in the managed `.gitignore` block.
- Private key contents are never logged, never returned through HA
  service calls, and never exposed as sensor attributes.
- The host's global `~/.ssh/config` and ssh-agent are isolated by
  `IdentitiesOnly=yes` (see §4.3).

### 10.3 Sanitized logging

- Git error messages are surfaced with stderr trimmed and key paths
  redacted.
- Persistent notifications carry short human-readable text, never raw
  stderr dumps or credentials.
- DEBUG logs may include argv but never `GIT_SSH_COMMAND` / env.

### 10.4 HTTPS authentication (Release)

- Tokens are stored through HA's credential storage, not in
  `configuration.yaml`.
- The remote URL on disk does not embed credentials; `http.extraheader`
  is set per call.

---

## 11. Compatibility

| Environment                | git available?           |
| -------------------------- | ------------------------ |
| HA OS (HassOS)             | yes                      |
| HA Supervised              | yes                      |
| HA Container (Docker)      | depends on the image — documented in README           |
| HA Core (venv)             | depends on host          |

Required Python: **3.11+**. Required HA: **2024.1+**.

---

## 12. Release roadmap (high-level)

The MVP ships with the YAML-only configuration and the operations
above. The first stable release adds, in order of priority:

1. UI Config Flow with SSH key generation and a "Test connection" step.
2. Backend migration from subprocess to GitPython behind the same API.
3. Additional sensors: `local_commit`, `remote_commit`,
   `changed_files`, `last_sync`.
4. `ha_gitops.commit` service for manual commits with a custom
   message.
5. `button.ha_gitops_fetch`.
6. Persistent notification with a "Reload configuration" action after
   a non-empty pull (auto-reload remains opt-in only).
7. Localization: en + ru.
