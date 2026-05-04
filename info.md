# HA GitOps

![HA GitOps icon](https://github.com/ckrl/ha-gitops/raw/master/custom_components/ha_gitops/brand/icon.png)

GitOps for Home Assistant configuration. Treat `/config/` as a Git working
directory: pull new YAML from the upstream repository, push local edits back,
and observe the sync state from the dashboard.

## Features

- **UI configuration** — add the integration under **Settings → Devices &
  services → Add integration** (no `configuration.yaml` block required).
- Sync status sensor (`clean`, `modified`, `ahead`, `behind`, `diverged`,
  `unknown`).
- Buttons to trigger `pull` and `push` (grouped on the integration **device**
  page with the status sensor).
- Safe by default: `secrets.yaml` and HA runtime state are ignored and
  protected from accidental commits by an in-code panic guard.
- Authenticates with the upstream Git host over SSH.

## Prerequisites

- A `git` binary available on the host (Home Assistant OS / Container /
  Supervised include it; on Core install it manually).
- An SSH deploy key with write access to the upstream repository (private key
  on the HA host, e.g. under `/config/.ha_gitops/`).

## Configuration

1. Open **Settings → Devices & services → Add integration** and choose **HA
   GitOps**.
2. Enter the **Git remote URL** (SSH), **branch**, **git author name/email**, and
   optionally a **path to the private SSH key** (leave empty to use the default
   `/config/.ha_gitops/id_ed25519`).

See [`docs/architecture.md`](https://github.com/ckrl/ha-gitops/blob/master/docs/architecture.md)
for the full design and operational details.
