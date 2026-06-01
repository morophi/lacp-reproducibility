# Reproducibility Boundary

This project is a multi-node experiment system. Full reproduction requires
compatible machines, Ollama/Qwen inference endpoints, a RAG/Chroma service, a
MariaDB-compatible dblog node, and the fixed scenario input.

The repository supports reproducibility at three levels:

1. Audit reproduction: inspect protocol, code, schema, and evidence summaries.
2. Environment reproduction: provision equivalent nodes and deploy repo files.
3. Run reproduction: execute preflight, E2E, CR/CR2, Run B, and CF stages using
   local credentials and node addresses.

## Fixed Operational Envelope

- Retrieval payload: `top_k=3`
- Smoke generation budget: `run_modes.smoke.num_predict=256`
- Formal endpoint mode: OpenAI-compatible chat completions
- Thinking output: disabled, with empty think-shell stripping
- Thermal control: log inference-node temperatures and preserve cooldown policy
- DB writer: async logging enabled with explicit flush requirements

## Reproduction Order

1. Prepare secrets and node aliases outside Git.
2. Apply dblog schema from `dblog_schema`.
3. Build or restore the RAG collection according to `scripts/README.md`.
4. Deploy `runtime_impl/agent` to the jump node.
5. Deploy `runtime_impl/harness` to the harness node.
6. Deploy thermal helpers to inference and jump nodes.
7. Run connectivity and inference readiness checks.
8. Run E2E smoke only after readiness is clean.
9. Treat CR/CR2/Run B/CF as formal stages after the freeze gates pass.

## Required Private Inputs

These values must be supplied by the reproducer and must not be committed:

- `LACP_DB_PASSWORD`
- SSH aliases or equivalent host mapping
- Any node-local service credentials
- Local model files and ChromaDB data
- Full private DB contents or raw logs

## Evidence References

Curated summaries kept in the repo:

- `E2E_ISSUE_SAMPLING_SUMMARY_20260527.md`
- `SMOKE_EVIDENCE_TOPK3_20260527.md`
- `E2E_DB_EVIDENCE_ONEPAGE.md`
- `lacp_experiment_guideline_rev6.1_revise.md`

Raw generated logs are intentionally excluded from Git unless explicitly
curated and scrubbed.
