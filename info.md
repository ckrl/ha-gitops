# HA GitOps

GitOps for Home Assistant configuration. Treat `/config/` as a Git working
directory: pull new YAML from the upstream repository, push local edits back,
and observe the sync state from the dashboard.

## Features

- Sync status sensor (`clean`, `modified`, `ahead`, `behind`, `diverged`,
  `unknown`).
- Buttons to trigger `pull` and `push` from the UI.
- Safe by default: `secrets.yaml` and HA runtime state are ignored and
  protected from accidental commits by an in-code panic guard.
- Authenticates with the upstream Git host over SSH.

## Prerequisites

- A `git` binary available on the host (Home Assistant OS / Container /
  Supervised include it; on Core install it manually).
- An SSH deploy key with write access to the upstream repository.

## Configuration

Add to `configuration.yaml`:

```yaml
ha_gitops:
  remote_url: "git@github.com:<owner>/<config-repo>.git"
  branch: master
  ssh_key_path: "/config/.ssh/id_ed25519"
```

See [`docs/architecture.md`](https://github.com/ckrl/ha-gitops/blob/master/docs/architecture.md)
for the full design and configuration reference.
