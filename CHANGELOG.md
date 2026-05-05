# Changelog

All notable changes to **HA GitOps** are documented here.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

Versioning policy:

- **Major** — breaking changes to the public surface: `GitManager` API, entity
  `unique_id` schema, service signatures, config-entry schema (without an
  automatic migration), or removal of a documented feature.
- **Minor** — backwards-compatible new features (additional entities, new
  options-flow steps, new services, new translations).
- **Patch** — backwards-compatible bug fixes, internal refactors, documentation,
  CI, and translation updates.

## [Unreleased]

_Nothing yet._

---

## [1.0.1] — 2026-05-05

### Added

- Extend brand asset set with logo and retina versions of logo and icon

---

## [1.0.0] — 2026-05-05

First stable public release. The feature set described below is the complete
scope of the 1.0.0 line; all prior `0.1.x` builds were pre-release development
iterations and are not separately documented.

### Added

#### Setup and configuration

- **UI Config Flow** — add the integration from **Settings → Devices &
  services**; no `configuration.yaml` block required. One config entry per
  Home Assistant instance (single `/config` tree).
- **Smart auto-fill** — if `/config/.git` already exists, the setup form
  pre-fills the remote URL, active branch, `user.name`, `user.email`, and the
  default SSH key path.
- **Options flow** with an action menu:
  - **Settings** — change the remote URL, branch, author identity, SSH key
    path, status sensor poll interval (`30 … 86400 s`, default `300 s`), and
    toggle auto-reload after pull.
  - **Generate SSH key** — create an ED25519 key pair at the chosen path
    (refuses to overwrite a non-empty existing key); the public key is
    delivered via a persistent notification.
  - **Test connection** — runs `git ls-remote origin` and reports the result.
- **Localization** — full English and Russian UI strings
  (`strings.json` + `translations/ru.json`).

#### Entities

- **Buttons (`config` category)**:
  - `button.pull` — `git fetch` + fast-forward merge of `origin/<branch>`;
    raises a Repairs item with a one-click _Reload core configuration_ fix
    when YAML changes are merged. Optional automatic reload via the
    integration option.
  - `button.fetch` — `git fetch origin` only; refreshes remote refs without
    touching the working tree.
  - `button.push` — single atomic auto-commit + push for root-level YAML
    changes; correctly handles the "nothing to commit but a previous commit
    failed to reach the remote" case.
- **Diagnostic sensors**:
  - `sensor.ha_gitops_sync_status` — current state
    (`clean` / `modified` / `ahead` / `behind` / `diverged` / `error` /
    `unknown`) with rich attributes (`last_operation`, `last_operation_time`,
    `last_error`, `last_sync`, `local_commit`, `remote_commit`,
    `changed_files_count`, `changed_files`).
  - `sensor.ha_gitops_commit_local` — short hash of local `HEAD` with full
    commit metadata.
  - `sensor.ha_gitopss_commit_remote` — short hash of `origin/<branch>` with
    full commit metadata.
  - `sensor.ha_gitops_changed_files` — count of root-level YAML files with
    working-tree changes; per-file `{name, status}` list as attribute.
  - `sensor.ha_gitops_last_sync` — timestamp (HA `timestamp` device class) of
    the last successful remote-touching operation.

#### Services

- **`ha_gitops.commit`** — stage allowed YAML and `.gitignore` (same rules as
  Push, secrets-guarded) and create a local commit **without pushing**;
  optional `message` overrides the adaptive commit message template.

#### Git backend

- **GitPython-based `GitManager`** running every Git invocation through
  `asyncio.to_thread` so the Home Assistant event loop is never blocked.
- **Adaptive commit messages** — subject built from the changed file list
  (`Update: <files>` with overflow handling for ≥4 files); body with a full
  `M/A/D` diff-stat, ISO-8601 timestamp, and integration version footer; trailer
  `Co-authored-by: HA GitOps <ha-gitops@noreply.github.com>` for clear
  attribution in GitHub / GitLab UIs.
- **Auto-managed `.gitignore`** — managed block with a magic marker
  (`# ha-gitops: managed exclusions — do not remove`); the block is staged
  alongside YAML on every push so the rules propagate to remote.
- **Fast-forward-only pulls** — diverged histories surface as the `diverged`
  status; the integration never auto-merges or auto-rebases.

#### Notifications and Repairs

- **Persistent notification on pull with changes** — includes a
  My Home Assistant link to `homeassistant.reload_core_config` and the list of
  changed files.
- **Repairs flow** (`pulled_config_reload`) — one-click
  _Reload core configuration_ fix from **Settings → System → Repairs**.
- **Opt-in automatic reload after pull** — when enabled in options, the
  integration calls `homeassistant.reload_core_config` itself and skips the
  Repairs item for that pull.

#### Project infrastructure

- HACS custom-repository compatibility (`hacs.json`, `manifest.json`,
  `iot_class: cloud_polling`).
- Brand icon at `custom_components/ha_gitops/brand/icon.png`.
- Architectural design-of-record at [`docs/architecture.md`](./docs/architecture.md);
  numbering kept stable so docstrings and `.cursor/rules/` can cite paragraph IDs.
- English and Russian READMEs with feature reference, status table, safety
  model, troubleshooting, and development sections.
- Public `GitManager` API contract (constructor, `initialize`, `push`, `pull`,
  `fetch`, `commit`, `get_status`, `generate_ssh_key`, `test_connection`,
  `async_get_inspection_snapshot`).

#### Continuous integration

- **hassfest** validation on every push and PR.
- **HACS validation** (`category: integration`), gated on public repository
  visibility.
- **Lint** — `ruff check` + `black --check`.
- **Tests** — `pytest` on Python 3.11 and 3.12 under
  `pytest-homeassistant-custom-component`, with coverage reporting.
- **Release workflow** — tag-driven (`v*.*.*`), verifies that the Git tag
  matches `manifest.json`, packages `ha_gitops.zip`, and creates a GitHub
  Release with auto-generated notes.

### Security

- **`secrets.yaml` is never committed.** Defense in depth: managed
  `.gitignore` block excludes `secrets.yaml`, `secrets_backup.yaml`, and
  `*.secrets.yaml`; an in-code panic guard verifies the staged set before
  every commit and aborts the operation if a secrets file slipped through.
- **Home Assistant runtime state is never committed.** `.storage/`, `.cloud/`,
  `core_*`, `home-assistant_v2.db*`, and `home-assistant.log*` are excluded by
  the managed `.gitignore` block.
- **SSH key material is isolated.** Default key path
  `/config/.ha_gitops/id_ed25519` is created with mode `0600`; the parent
  directory is in the managed `.gitignore`. SSH key contents are never logged
  or returned through Home Assistant APIs.
- **Per-integration `known_hosts`.** A dedicated
  `/config/.ha_gitops/known_hosts` is used with
  `StrictHostKeyChecking=accept-new` — accepts new hosts on first contact,
  rejects changed host keys (basic MITM protection). The user's `~/.ssh` is
  never touched.
- **No writes to the host's global `git config`.** `safe.directory` for
  `/config` (Git 2.35+ "dubious ownership" handling) and per-commit identity
  are passed via `GIT_CONFIG_KEY_*` / `GIT_CONFIG_VALUE_*` and `-c
user.name=… -c user.email=…` so only integration-spawned Git invocations are
  affected.
- **Pulls are fast-forward only.** Conflicts surface as `diverged`; the
  integration never auto-merges or auto-rebases without explicit user action.
- **No automatic push.** Every push is explicit (button or service call); the
  integration ships no internal scheduler.

### Known limitations

These are intentional non-goals for the 1.0.0 line and are tracked in
[`docs/architecture.md`](./docs/architecture.md) §3 / §12:

- HTTPS authentication is not supported — SSH only.
- A single Home Assistant instance can drive a single repository.
- A single config entry per Home Assistant; the integration always operates
  against `hass.config.path()` (the `/config` tree).
- Diverged histories require manual resolution over SSH; there is no in-UI
  "force pull" or conflict editor.
- Synchronization of `.storage/`, `.cloud/`, `core_*`, and other Home
  Assistant runtime state is permanently out of scope.

[Unreleased]: https://github.com/ckrl/ha-gitops/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/ckrl/ha-gitops/releases/tag/v1.0.1
[1.0.0]: https://github.com/ckrl/ha-gitops/releases/tag/v1.0.0
