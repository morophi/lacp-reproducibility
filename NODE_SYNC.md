# Node Change Sync

This repository is the canonical source of truth. Remote nodes stay inside the
closed network and are treated as deployment/runtime targets.

`scripts/node_sync_watch.py` watches only the allowlisted files in
`node_sync_targets.json`.

## Modes

Detect changed allowlisted files without copying:

```powershell
python scripts\node_sync_watch.py detect
```

Preview a sync operation:

```powershell
python scripts\node_sync_watch.py sync
```

Copy changed allowlisted files into this repo:

```powershell
python scripts\node_sync_watch.py sync --apply
```

Copy, scan, commit, and push:

```powershell
python scripts\node_sync_watch.py sync --apply --commit --push
```

## Safety Rules

- The default `sync` mode is dry-run.
- Only allowlisted paths are inspected or copied.
- ChromaDB data, virtual environments, logs, conversation exports, SSH material,
  Tailscale state, and DB dumps are excluded.
- A secret scan is run before automatic commits.
- Extra local-only secret patterns can be supplied with
  `LACP_SECRET_SCAN_PATTERNS`, separated by semicolons.
- GitHub is updated only from the local PC repo, not from remote nodes.

## Recommended Rollout

1. Run `detect` manually after node edits.
2. Run `sync --apply` and review `git diff`.
3. Enable `--commit --push` after the allowlist has proven stable.
