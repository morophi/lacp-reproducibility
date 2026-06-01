# Security and Publication Notes

Do not commit credentials, SSH keys, Tailscale state, raw private logs, or
machine-local dumps.

## Secrets

The following values must be provided outside Git:

- `LACP_DB_PASSWORD`
- Harness local environment file: `/home/morophi/harness/.env.local`
- SSH private keys and node aliases
- sudo passwords or operator passwords
- Tailscale node keys or status JSON

Config files may contain environment placeholders such as:

```text
${LACP_DB_PASSWORD}
```

The Harness config loader expands environment variables when reading config
files.

## Before Publishing

Run a secret scan before pushing:

```bash
rg -n "password|--password|private-key-marker|node-key-marker|secret|token|<known-secret-pattern>" .
```

Any hit in source or documentation must be reviewed. Hits inside ignored
conversation exports or private local artifacts must stay untracked.

## Artifact Policy

Keep these out of Git:

- ChromaDB data directories
- Raw JSONL E2E and thermal logs
- Pre-formal scratch JSONL under `.node_sync_logs`
- Pre-formal Markdown and theta artifacts should be reviewed before commit
- Conversation exports
- Office drafts and generated review documents
- Local network diagnostics
- Node-local `.env.local` files

Use summaries, manifests, hashes, and documented reproduction commands instead.
