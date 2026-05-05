# HA GitOps

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-41BDF5.svg)](https://www.home-assistant.io/)
[![Validate](https://github.com/ckrl/ha-gitops/actions/workflows/validate.yml/badge.svg)](https://github.com/ckrl/ha-gitops/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/ckrl/ha-gitops?include_prereleases&sort=semver)](https://github.com/ckrl/ha-gitops/releases)

English | [Русский](./README_ru.md)

<p align="center">
  <img src="custom_components/ha_gitops/brand/icon.png" alt="HA GitOps icon" width="128" />
</p>

**HA GitOps** turns your Home Assistant `/config` directory into a real Git working tree
and lets you `pull`, `fetch`, `push`, and observe sync state from the Home Assistant UI —
without a custom add-on, an external editor, or shell access.

It is a HACS custom integration: configured entirely from **Settings → Devices & services**,
authenticated over SSH, safe by default (`secrets.yaml` and Home Assistant runtime state are
never committed), and fully tested under `pytest-homeassistant-custom-component`.

---

## Table of contents

- [Why this integration](#why-this-integration)
- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Setup walkthrough](#setup-walkthrough)
- [Entities and services](#entities-and-services)
- [Sync status reference](#sync-status-reference)
- [Safety model](#safety-model)
- [Options and reconfiguration](#options-and-reconfiguration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Architecture and design](#architecture-and-design)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why this integration

YAML files under `/config/*.yaml` are not version controlled out of the box. A bad edit,
a botched device replacement, or an experimental automation can be hard to roll back,
compare across instances, or audit over time.

Existing options each leave gaps:

- **Studio Code Server / File Editor** — editors, not version control.
- **Git pull add-on** — pull only, no push, no UI sensors, add-on (not integration), limited config.
- **Manual `git` over SSH** — works, but invisible to Home Assistant; no dashboard signal,
  no notifications, no per-machine button, no guard against committing `secrets.yaml`.

`ha_gitops` is the missing native piece: a small HACS integration that follows the
standard GitOps pattern (the config directory **is** the working tree), exposes Git as
first-class HA entities, and bakes in the safety rules you would otherwise have to enforce
by hand.

## Features

- **UI Config Flow** — add the integration from **Settings → Devices & services**; no
  `configuration.yaml` block needed. One instance per Home Assistant.
- **Smart auto-fill** — if `/config/.git` already exists, the setup form pre-fills the
  remote URL, active branch, `user.name`, `user.email`, and the default SSH key path.
- **SSH key management from the UI** — generate an ED25519 deploy-key pair directly from
  the integration; the public key is shown in a persistent notification ready to paste
  into GitHub / GitLab / Forgejo / your self-hosted server.
- **Test connection** — a one-click `git ls-remote origin` to validate auth and URL
  before you trust it.
- **Three buttons** — `Pull` (fast-forward only), `Fetch` (refresh remote refs only),
  `Push` (single atomic auto-commit + push).
- **Five diagnostic sensors** — sync status, local HEAD, remote HEAD, changed YAML count,
  and the timestamp of the last successful remote sync.
- **`ha_gitops.commit` service** — create a local commit (e.g. as a snapshot before an
  experiment) without pushing; supports an optional custom message.
- **Pull-aware Repairs flow** — when a pull brings in YAML changes, HA GitOps raises a
  Repairs item with a one-click "Reload core configuration" fix. Optionally auto-reload.
- **Adaptive commit messages** — subject built from the changed file list; body with a
  full diff-stat and a `Co-authored-by: HA GitOps` trailer for clear attribution.
- **Safe by default** — `secrets.yaml`, `secrets_backup.yaml`, `.storage/`, `.cloud/`,
  `core_*`, and the HA SQLite database are excluded by a managed `.gitignore` block,
  with an in-code panic guard that aborts a push if `secrets.yaml` ever ends up staged.
- **Non-blocking** — every Git call runs through GitPython on a worker thread; the HA
  event loop is never blocked by network I/O.
- **Localized** — English and Russian (`strings.json` + `translations/ru.json`).
- **Tested** — full `pytest` suite under `pytest-homeassistant-custom-component`,
  hassfest, HACS validation, and lint (ruff + black) gated by CI.

## How it works

```
┌──────────────────────── Home Assistant ────────────────────────┐
│                                                                │
│   Buttons               Sensors                Service         │
│   ─────────             ─────────              ─────────       │
│   button.pull           sensor.sync_status     ha_gitops.      │
│   button.fetch          sensor.local_commit       commit       │
│   button.push           sensor.remote_commit                   │
│                         sensor.changed_files                   │
│                         sensor.last_sync                       │
│            │                  │                  │             │
│            └────────┬─────────┴──────────────────┘             │
│                     ▼                                          │
│              ┌────────────────┐                                │
│              │  GitManager    │  (asyncio.to_thread)           │
│              └───────┬────────┘                                │
│                      │ GitPython                               │
│                      ▼                                         │
│              ┌────────────────┐                                │
│              │  git CLI       │  GIT_SSH_COMMAND               │
│              └───────┬────────┘                                │
└──────────────────────┼─────────────────────────────────────────┘
                       │   SSH (ED25519, isolated known_hosts)
                       ▼
              ┌────────────────┐
              │  Remote Git    │  GitHub / GitLab / Forgejo /
              │  repository    │  self-hosted
              └────────────────┘
```

The `/config` directory itself is the Git working tree: `.git/` lives in `/config/.git`,
the integration manages `/config/.gitignore`, and SSH key material lives in
`/config/.ha_gitops/` (excluded from the repo).

## Requirements

- **Home Assistant** `2024.1.0` or newer.
- **Python** `3.11+` (matches Home Assistant Core).
- **`git` binary** in the runtime environment. Available out of the box on Home Assistant OS,
  Supervised, and the official Container image. On bare HA Core / venv installs you may need
  to install it via your OS package manager.
- A **remote Git repository** (GitHub, GitLab, Forgejo, Bitbucket, self-hosted Gitea, plain
  SSH server — anything reachable over SSH).
- An **SSH key pair** with write access to that repository — either bring your own or let
  the integration generate one for you.

## Installation

### Option 1 — HACS (recommended)

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ckrl&repository=ha-gitops&category=integration)

1. Click the badge above (opens HACS in your Home Assistant with this repository pre-filled), **or** add it manually:
   - **HACS → Integrations → ⋮ → Custom repositories**
   - URL: `https://github.com/ckrl/ha-gitops`
   - Category: **Integration**
2. Install **HA GitOps**.
3. Restart Home Assistant.

### Option 2 — Manual

```bash
# from the host that runs Home Assistant
cd /config
mkdir -p custom_components
git clone https://github.com/ckrl/ha-gitops /tmp/ha-gitops
cp -r /tmp/ha-gitops/custom_components/ha_gitops custom_components/
```

Then restart Home Assistant.

### Add the integration to Home Assistant

After installation and restart:

[![Add integration to your Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ha_gitops)

The badge above opens **Add integration → HA GitOps** in your instance directly. The same flow is available manually under **Settings → Devices & services → Add integration → HA GitOps**.

## Setup walkthrough

1. **Settings → Devices & services → Add integration → HA GitOps.**
2. Fill in the form (existing values are pre-filled if `/config/.git` is already a Git repo):
   - **Git remote URL** — SSH form, e.g. `git@github.com:owner/ha-config.git`.
   - **Branch** — defaults to `main`.
   - **Git commit author name / email** — defaults `Home Assistant` / `homeassistant@local`.
   - **Private SSH key path** — leave empty for the integration default
     (`/config/.ha_gitops/id_ed25519`); absolute and `/config`-relative paths are accepted.
3. Submit. The integration runs `GitManager.initialize()` against `/config`:
   `git init` (if needed) → set the `origin` remote → write the managed `.gitignore`
   block → `git fetch origin`.
4. If you do not have a deploy key yet, open
   **Settings → Devices & services → HA GitOps → Configure → Generate SSH key**.
   The integration creates an ED25519 key pair and shows the public key in a persistent
   notification — paste it into your Git host's deploy keys.
5. Validate everything via **Configure → Test connection** (runs `git ls-remote origin`).
6. Use **Pull / Fetch / Push** from the integration's device page; watch the
   `Sync status` sensor for state.

> **Tip.** A typical bootstrap is: create the empty repo on the Git host, generate the SSH
> key from the integration, add the public key as a deploy key with write access, then
> press **Push** to upload your current `/config` YAML.

## Entities and services

All entities are grouped on a single **HA GitOps** device. Sensors carry the
`diagnostic` category; buttons carry the `config` category.

### Sensors

| Entity | Type | Description |
| --- | --- | --- |
| `sensor.ha_gitops_sync_status` | enum | Current sync state — see [reference below](#sync-status-reference). Attributes include `last_operation`, `last_operation_time`, `last_error`, `local_commit`, `remote_commit`, `changed_files_count`, `changed_files`, `last_sync`. |
| `sensor.ha_gitops_commit_local` | text | Short hash of local `HEAD`. Attributes: `full_hash`, `message`, `author`, `timestamp`. |
| `sensor.ha_gitops_commit_remote` | text | Short hash of `origin/<branch>`. Attributes: same as above. |
| `sensor.ha_gitops_changed_files` | numeric | Count of root-level YAML files with working-tree changes. Attribute `files`: list of `{name, status}`. |
| `sensor.ha_gitops_last_sync` | timestamp | When the last successful remote-touching operation finished. |

### Buttons

| Entity | Action |
| --- | --- |
| `button.pull` | `git fetch origin` + fast-forward merge of `origin/<branch>` only. Never rebases or auto-merges. On YAML changes: persistent notification + Repairs item with one-click "Reload core configuration", or automatic reload if enabled in options. |
| `button.fetch` | `git fetch origin` only — refreshes remote refs without touching the working tree. Useful to update `Sync status` without applying anything. |
| `button.push` | Stages root-level `*.yaml` (excluding `secrets.yaml`) and `.gitignore`, commits if anything changed, then pushes. If there is nothing to commit but a previous local commit failed to reach the remote, only the push step runs. If there is genuinely nothing to do, it is a clean no-op. |

### Services

| Service | Purpose |
| --- | --- |
| `ha_gitops.commit` | Stage and commit using the same rules as Push, but **without pushing**. Optional `message` field overrides the adaptive commit message — useful for snapshots before risky changes. |

## Sync status reference

| Value | Meaning | Recommended action |
| --- | --- | --- |
| `clean` | Local `HEAD` matches `origin/<branch>`; no uncommitted YAML changes. | None — you are in sync. |
| `modified` | Tracked YAML files have uncommitted changes. | Press **Push** when ready. |
| `ahead` | Local commits are not yet on the remote. | Press **Push**. |
| `behind` | Remote has new commits, fast-forward possible. | Press **Pull**. |
| `diverged` | Local and remote histories have diverged — fast-forward is impossible. | Resolve manually (rebase / merge / reset over SSH). |
| `error` | The last Git operation failed. See `last_error` attribute and HA logs. | Address the error and retry. |
| `unknown` | Repository not initialized yet, or initial probe is still running. | Wait, or check setup. |

## Safety model

`ha_gitops` is opinionated about what must **never** end up in your repository:

- **Secrets are never committed.** `.gitignore` excludes `secrets.yaml`,
  `secrets_backup.yaml`, and `*.secrets.yaml`. An additional in-code **panic guard**
  walks the staged set before every `git commit` and aborts the operation if any
  secrets file slipped through.
- **HA runtime state is never committed.** `.storage/`, `.cloud/`, `core_*`,
  `home-assistant_v2.db*`, and `home-assistant.log*` are excluded.
- **Pulls are fast-forward only.** Conflicts surface as `diverged` and require
  human intervention; the integration does not auto-merge or auto-rebase.
- **SSH key material is isolated.** Default key path is `/config/.ha_gitops/id_ed25519`,
  permissions `0600`, and `/config/.ha_gitops/` is gitignored. A dedicated `known_hosts`
  file is maintained per integration (`StrictHostKeyChecking=accept-new`) — no host keys
  are written to the user's `~/.ssh`.
- **Host gitconfig is never touched.** "Dubious ownership" (Git 2.35+) and per-commit
  identity are handled via `GIT_CONFIG_KEY_*` / `GIT_CONFIG_VALUE_*` and `-c
  user.name=… -c user.email=…` — no global `git config` writes.
- **No auto-push.** Every push is explicit (button or service). Schedule it from a HA
  automation if you need to.

## Options and reconfiguration

**Settings → Devices & services → HA GitOps → Configure** opens an action menu:

- **Settings** — change the remote URL, branch, author identity, SSH key path, the
  status-sensor poll interval (`30…86400 s`, default `300 s`), and toggle
  **Automatically reload core configuration after a pull that changes YAML**.
- **Generate SSH key** — create an ED25519 key pair at the chosen path. Aborts if a
  non-empty private key already exists. On success the public key is delivered via a
  persistent notification.
- **Test connection** — runs `git ls-remote origin` and reports success/failure.

## Troubleshooting

### Setup fails with "Could not initialize the Git repository"

Open Home Assistant logs (filter by `custom_components.ha_gitops`) and check:

- **SSH key permissions** — must be `0600` and readable by the HA process.
- **Deploy key access** — the public key must be added on the Git host with **write**
  access if you intend to push.
- **Remote URL** — SSH form (`git@host:owner/repo.git`); HTTPS is not supported in MVP.
- **Branch name** — must exist on the remote, or be the branch you intend to create on
  the first push.
- **`git` binary** — `which git` on the HA host; install if missing.

### "detected dubious ownership" on Git 2.35+

`HA GitOps` already passes `safe.directory` for `/config` to every Git invocation it
spawns. If you see this error from outside the integration (e.g. a manual `git status`
in a shell add-on), mark the directory safe in that shell only:

```bash
git config --global --add safe.directory /config
```

### Pull succeeded, but my YAML changes are not applied

Home Assistant only loads YAML at startup or via an explicit reload. Either:

- Open **Settings → System → Repairs** and run the "HA GitOps: configuration updated
  from Git" fix (calls `homeassistant.reload_core_config`), **or**
- Enable **Automatically reload core configuration after a pull** in the integration
  options, **or**
- Restart Home Assistant manually.

### Push is rejected: "remote has new changes"

The remote is ahead of your local branch. Press **Pull** first, resolve any
`diverged` state if needed, then **Push** again.

### Sensor shows `unknown` after a long fetch

Status updates are bound to the sensor's `scan_interval` (default 5 min). Press
**Fetch** to refresh remote refs immediately, or shorten the poll interval in options.

### Entity IDs do not change after I update the integration

Home Assistant pins `entity_id` to a stable `unique_id` in `core.entity_registry`.
Since `unique_id` is intentionally stable across versions, old `entity_id`s are
preserved. Rename them in **Settings → Devices & services → HA GitOps**.

## Development

This repository is **not** a packaged Python project — the integration lives in
`custom_components/ha_gitops/` and is loaded by Home Assistant at runtime. The
`pyproject.toml` only declares the dev environment.

```bash
# uv-based workflow (matches CI)
uv sync --extra dev

# Lint and format
uv run ruff check .
uv run black --check .

# Tests (with coverage)
uv run pytest -v --cov=custom_components/ha_gitops --cov-report=term-missing
```

CI runs on every push and PR (`.github/workflows/validate.yml`):

- **hassfest** — Home Assistant manifest validator
- **HACS validation** — `category: integration`
- **Lint** — `ruff` + `black --check`
- **Tests** — `pytest` matrix on Python 3.11 and 3.12

The full architectural design-of-record (numbered to match docstring references) lives
in [`docs/architecture.md`](./docs/architecture.md). The `.cursor/rules/` directory
captures conventions for IDE-side AI assistance.

## Architecture and design

For the deep dive — component diagram, `GitManager` public API, commit-message format,
status detection algorithm, error taxonomy, and security trade-offs — see
[`docs/architecture.md`](./docs/architecture.md).

Key design decisions in one paragraph: `/config` itself is the Git working tree (no
staging copy, no shadow directory). Git operations go through GitPython, which in turn
shells out to the system `git` binary; calls happen on a worker thread so the HA event
loop stays responsive. SSH is the only auth scheme in MVP, with a key path and
`known_hosts` file owned by the integration. Pulls are fast-forward only; pushes are a
single atomic auto-commit + push with an adaptive commit message and a
`Co-authored-by: HA GitOps` trailer for clear attribution.

## Roadmap

Planned for future releases (tracked in `docs/architecture.md` §12):

- HTTPS authentication with token storage via HA credential storage.
- Multi-branch support and per-entry branch switching.
- "Force pull" as an explicit, high-friction action for diverged states.
- HACS Default Store submission once the API surface and entity contract are frozen.

Out of scope (intentional non-goals):

- Synchronizing `.storage/`, `.cloud/`, `core_*` or any other HA runtime state.
- Including `secrets.yaml` in the repository — this is a hard policy.
- Auto-merge on conflicts.
- Driving multiple repositories from a single HA instance.

## Contributing

Issues and pull requests are welcome at
[github.com/ckrl/ha-gitops](https://github.com/ckrl/ha-gitops).

Before opening a PR:

1. Skim [`docs/architecture.md`](./docs/architecture.md) — the public `GitManager` API
   and entity contract are tracked there.
2. Run `ruff`, `black --check`, and `pytest` locally; CI will run the same.
3. Keep changes within the documented design or propose an architecture amendment in
   the same PR.

## License

[MIT](./LICENSE) © Constantine Krylov
