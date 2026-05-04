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

**Git 2.35+ “dubious ownership”.** When `/config/.git` is not owned by the
same UID as the Home Assistant process (bind mounts, root-owned trees,
some NAS layouts), `git` exits with `detected dubious ownership` unless the
directory is marked safe. `GitManager` does **not** run
`git config --global --add safe.directory` (that would violate the rule of
never touching the host’s global gitconfig). Instead every subprocess sets
`GIT_CONFIG_KEY_n=safe.directory` / `GIT_CONFIG_VALUE_n=<resolved /config>`
(merged with any pre-existing `GIT_CONFIG_COUNT` from the environment) so
only integration-spawned git invocations trust the configured working tree.

### 4.3 SSH authentication

The default layout is **`<config>/.ha_gitops/`** (on HA OS / Container the
config directory is usually mounted as `/config`; on HA Core it may be
`~/.homeassistant` or another path — `hass.config.path()` is the source of
truth). In the Config Flow, an **empty** SSH key field selects
`<config>/.ha_gitops/id_ed25519`. A **relative** path (e.g.
`.ha_gitops/id_ed25519`) is always resolved **under the config directory**, not
relative to the supervisor process cwd. An **absolute** path is used as-is
(after `~` expansion).

Example paths when the config directory is `/config`:

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
│   button.ha_gitops_pull/fetch/push  sensor.ha_gitops_*  │
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
│       ├── button.py            # ButtonEntity: pull, fetch, push
│       ├── repairs.py           # RepairsFlow: fix reload after pull (issue_registry)
│       ├── config_flow.py       # UI Config Flow (MVP)
│       ├── services.yaml        # service descriptors
│       ├── strings.json         # UI strings (en)
│       ├── brand/               # integration images (HA 2026.3+ local brands API)
│       │   └── icon.png         # square icon (HACS / Settings → Integrations)
│       │                        # pre-release: rescale/replace for larger/crisper asset (see §12)
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
  "iot_class": "cloud_polling",
  "config_flow": true
}
```

`iot_class` is **`cloud_polling`**: status polling and git operations reach the
**remote** over the network (SSH), so Home Assistant treats the integration as
**needing internet / outbound connectivity** (not a purely local-LAN device).

`requirements` is empty in the MVP — the integration depends on the
`git` binary, which is not a Python dependency. `config_flow` is **true** so
onboarding runs through the UI (see §6). Release adds `"GitPython>=3.1"` behind
the same `GitManager` API.

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

## 6. Configuration

### 6.0 Config Flow (MVP)

Onboarding is **Settings → Devices & services → Add integration → HA GitOps**.
Only **one** config entry is allowed (single `/config` working tree).

The first-run form (`config_flow.py` + `strings.json`) collects:

| Key / UI field                         | Purpose                                                                  |
| -------------------------------------- | ------------------------------------------------------------------------ |
| `repo_url`                             | SSH remote, e.g. `git@github.com:owner/ha-config.git`                    |
| `branch`                               | Remote branch (default `main`)                                           |
| `git_author_name` / `git_author_email` | Commit metadata; passed via per-call `git -c user.name/email=…`          |
| `ssh_key_path`                         | Private ED25519 key path; **empty** uses `/config/.ha_gitops/id_ed25519` |

During the final step the flow runs `GitManager.initialize()` against the live
`/config` tree. Failures surface as form errors; successful completion creates
the config entry and loads `sensor` + `button` platforms.

`scan_interval` is stored on the config entry (default **300** seconds).

**Reconfiguration:** Settings → **HA GitOps** → **Configure** opens the
**Options flow** (`async_get_options_flow`): the same fields as the initial
form plus `scan_interval`. Submit runs `GitManager.initialize()` again,
persists updates to `entry.data`, and `async_reload`s the config entry so
`GitManager` and entity scan intervals pick up new values.

Entities share one **device registry** entry (`DeviceEntryType.SERVICE`) so
Pull, Fetch, Push, and Sync status appear together on the integration device page.

**Release** adds an SSH key generator, explicit “Test connection”, and HTTPS auth.

### 6.1 Greenfield vs brownfield

**Greenfield** — the remote is empty (or not yet created) and `GitManager.initialize()`
creates `/config/.git`, wires `origin`, writes the managed `.gitignore` block,
and optionally checks out `origin/<branch>` when the remote already has an
initial commit pushed from another machine.

**Brownfield** — the remote **already contains commits** (for example you
initialized the repo and pushed from a laptop) and the Home Assistant host
already has a populated `/config` with YAML. The goal is **one linear history**
shared with that remote, not a second unrelated root commit on the appliance.

#### SSH when operating `git` manually on the host

The integration forces `IdentitiesOnly=yes` and a dedicated key file (§4.3).
Interactive shells on the same host do **not** automatically use
`/config/.ha_gitops/id_ed25519` — they follow OpenSSH defaults (`~/.ssh/…`).
Either:

- pass `GIT_SSH_COMMAND` on each invocation:

  ```bash
  export GIT_SSH_COMMAND='ssh -i /config/.ha_gitops/id_ed25519 \
    -o UserKnownHostsFile=/config/.ha_gitops/known_hosts \
    -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes'
  ```

- or add a `Host github.com` stanza in **the SSH user’s** `~/.ssh/config` with
  the same `IdentityFile` and `IdentitiesOnly yes`.

The GitHub account that owns the **public** half of that key must have read
(and write, for push) access to `repo_url` — collaborator, org membership, or a
repo deploy key.

#### Brownfield mistake: `git init` + first commit on HA while `origin` already has history

If the remote already has commits and you run `git init` on `/config`, stage
YAML, and `git commit`, you create a **second root commit** unrelated to the
remote graph. `git push` is then **non-fast-forward**; `git pull` without an
explicit strategy refuses to merge the two unrelated lines of history.

**Prevention (recommended):** before making the first local commit on the HA
host, connect the working tree to the existing remote and align with its tip
(for example `git remote add` + `git fetch` + check out or reset to
`origin/<branch>` per your backup policy), **or** only ever push the first
commits from one machine and let `ha_gitops` initialize the appliance without
hand-rolling a competing root commit.

**Recovery when remote should win** (you have no unique work in the local root
commit you care to keep, or you have a backup): after `git fetch origin`, reset
the current branch hard to the remote tip, for example
`git reset --hard origin/master` (replace `master` with your branch). This
**discards** the orphan local commit and any uncommitted changes in the
working tree — verify backups first.

**Recovery when both sides must be kept:** use a one-time explicit merge of
unrelated histories (Git prints the exact hint), resolve conflicts, then return
to fast-forward-only pulls for day-to-day use. Expect a merge commit and
possible conflict resolution in YAML.

#### Brownfield checklist (manual `git` on the appliance)

1. Confirm `git` is on `PATH` (§11).
2. Install the deploy key: private key under `/config/.ha_gitops/`, mode `600`;
   public key on the GitHub identity that has access to the repo.
3. Use `GIT_SSH_COMMAND` or `~/.ssh/config` so **every** `git fetch`/`pull`/`push`
   from a shell uses that key (`IdentitiesOnly=yes`).
4. Do **not** create a competing root commit: align with `origin/<branch>`
   before or instead of hand-rolling `git init` + `git commit` when the remote
   is non-empty.
5. Set upstream once: `git push -u origin <branch>` or
   `git branch --set-upstream-to=origin/<branch> <branch>` so bare `git pull`
   knows the default merge ref.

---

## 7. Entities

### 7.1 Buttons

#### `button.ha_gitops_pull`

- **Action**: `git fetch` + `git merge --ff-only origin/<branch>`.
- **Success with changes**: status sensor refreshed; **persistent notification**
  with a Markdown link to My Home Assistant →
  `homeassistant.reload_core_config`, plus a truncated list of changed paths; an
  **`issue_registry`** entry (`pulled_config_reload`, fixable) appears under
  **Settings → System → Repairs** — the fix flow runs **`homeassistant.reload_core_config`**
  on confirm (still no silent auto-restart).
- **Reload policy**: **MVP** — no automatic full **restart** of Home Assistant;
  reload of **core configuration** is offered only via the link and the optional
  Repairs fix (user-initiated). **Release** — optional opt-in to **automatic**
  reload/restart after pull in options; default remains manual.
- **Conflict / diverged**: status `error`/`diverged`, notification with
  details, **no merge applied**.
- **No changes**: status `clean`, silent success.

#### `button.ha_gitops_push`

A single atomic action from the user's perspective:

```
git add <root *.yaml>    (via _get_yaml_files, secrets excluded)
git add .gitignore       (when the file exists — tracks the managed block
                          from §4.4 and any user edits next to it)
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

#### `button.ha_gitops_fetch`

- **Action**: `git fetch origin` only — updates `origin/*` refs; **does not**
  merge, rebase, or change the working tree / `HEAD`.
- **Success**: silent (no persistent notification); status sensor reflects new
  remote comparison on its next poll.
- **Failure** (e.g. network, auth): `GitError` → persistent notification
  "HA GitOps: fetch failed" with a short message; status may show `error` on
  the next sensor update depending on `get_status()` outcome.

#### `repairs.py` (integration platform)

`async_create_fix_flow` dispatches issue `pulled_config_reload` to
`PulledConfigReloadRepairFlow` (confirm → `homeassistant.reload_core_config`);
other issue IDs fall back to the generic `ConfirmRepairFlow`. Strings live under
`strings.json` → `issues.pulled_config_reload` (title, description, `fix_flow`).

### 7.2 Service `ha_gitops.commit`

Registered when the config entry loads (`__init__.py`); removed on unload.
Calls `GitManager.commit(message=...)`: same staging and secrets guard as Push
(§8 / `_stage_yaml_files`), **no** `git push`. Optional service data field `message`
(string, max 7200 chars): if omitted or whitespace-only, the adaptive subject/body
from §8.3 is used; otherwise the supplied string is passed as the single
`git commit -m` argument. On `GitError`, the service raises `HomeAssistantError`
with a sanitized message for automations/UI.

### 7.3 Status sensor — `sensor.ha_gitops_status`

| State      | Condition                                         |
| ---------- | ------------------------------------------------- |
| `clean`    | Local HEAD equals remote HEAD; no working changes |
| `modified` | Uncommitted or untracked YAML changes present     |
| `ahead`    | Local commits not yet pushed                      |
| `behind`   | Remote commits not yet pulled                     |
| `diverged` | Histories diverged — manual action required       |
| `error`    | Last operation failed                             |
| `unknown`  | Repository not initialized or remote unreachable  |

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

| Scenario                                                             | Behaviour                                                                                                      |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `git` binary missing                                                 | Setup fails with a clear error, HA not affected                                                                |
| Remote unreachable                                                   | Status `error`, retried on the next scan interval                                                              |
| Conflict during pull                                                 | Status `diverged`, no merge applied, notification                                                              |
| Push rejected (remote ahead)                                         | Error rewritten to "Pull first.", notification                                                                 |
| SSH key missing or invalid                                           | Setup error with remediation hint                                                                              |
| Empty commit (nothing to push)                                       | No-op, status stays `clean`                                                                                    |
| HA restart mid-operation                                             | Operation aborts, status refreshes on the next scan                                                            |
| User deleted the `.gitignore` block                                  | Block recreated on the next operation, warning logged                                                          |
| `secrets.yaml` ends up staged                                        | Panic guard: unstage, abort, error notification (see §10.1)                                                    |
| HA host: `git init` + root commit while `origin` already has commits | Unrelated histories — push rejected (non-FF), pull needs explicit merge strategy; see §6.1 brownfield recovery |
| Git “dubious ownership” on `/config`                                 | Mitigated per §4.2 via `GIT_CONFIG_*` `safe.directory` on every git subprocess (no global gitconfig)           |

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

| Environment           | git available?                              |
| --------------------- | ------------------------------------------- |
| HA OS (HassOS)        | yes                                         |
| HA Supervised         | yes                                         |
| HA Container (Docker) | depends on the image — documented in README |
| HA Core (venv)        | depends on host                             |

Required Python: **3.11+**. Required HA: **2024.1+**.

---

## 12. Release roadmap (high-level)

**Pre-release (branding):** replace or re-export `custom_components/ha_gitops/brand/icon.png`
at a **larger** resolution (e.g. **512×512** minimum for crisp UI scales) or supply
separate `logo.png` for wide layouts — current asset is functional but may look
small until the frontend cache refreshes.

The MVP ships with a **UI Config Flow** (§6.0), the `sensor` / `button`
entities, and the git operations above. **`ha_gitops.commit`** (§7.2) ships from v0.1.1 onward; **`button.ha_gitops_fetch`**
(§7.1) from v0.1.3 onward; **post-pull Repairs + My link** (§7.1 Pull / `repairs.py`) from v0.1.5 onward.
The first stable release continues with the following, **in this priority order** (highest first):

1. Additional sensors: `local_commit`, `remote_commit`, `changed_files`,
   `last_sync`.
2. SSH key generation in the flow, explicit “Test connection”, and extending the
   options flow (e.g. **automatic** `reload_core_config` / restart after pull as **opt-in** only).
3. Backend migration from subprocess to GitPython behind the same API.
4. Localization: en + ru.
