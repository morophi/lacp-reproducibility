# LACP Experiment Reproducibility Repository

This repository is the source-of-truth package for the LACP multi-node
experiment harness. It contains the code, schema, scripts, runbooks, and
evidence summaries needed to audit and reproduce the experiment workflow.

The live system is distributed across several nodes: `jump`, `harness`, `rag`,
`dblog`, and three inference nodes. This repository intentionally keeps the
canonical source in one place and treats node directories as deployment targets.

## Current Fixed Decisions

- Formal retrieval payload constraint: `top_k = 3`
- LMS-capable inference endpoint: OpenAI-compatible chat completions
- Model family used in the validated path: `qwen3-nothink`
- Harness owns intervention control, metrics, independent histories, and DB logging
- Agent/jump owns scenario replay only
- RAG node returns raw chunks only; it does not summarize or apply SC policy
- dblog stores experiment evidence

## Main Directories

- `runtime_impl/agent`: scenario replay and formal stage orchestration
- `runtime_impl/harness`: Harness runtime, metrics, policy, node clients, config
- `inference_nodes`: Per-node inference Modelfile and small node helpers
- `scripts`: ingest, retrieval validation, freeze, preflight, and E2E helpers
- `dblog_schema`: DB schema and migration checks
- `validation_queries`: scenario and validation fixtures
- `verify_remote`: remote verification helpers and selected small fixtures
- `revision_notes`: dated change notes

Large logs, vector databases, virtual environments, conversation exports, and
machine-specific network dumps are excluded from Git. See `SECURITY.md` and
`REPO_TARGETS.md` before publishing or pushing.

## Quick Orientation

1. Read `REPO_TARGETS.md` for node-to-repo mapping.
2. Read `REPRODUCIBILITY.md` for the reproducibility boundary and run order.
3. Read `NODE_SYNC.md` for allowlist-based node change detection and sync.
4. Read `PREFORMAL_RUNBOOK.md` for DB-free Markdown evidence rehearsals.
5. Configure secrets through environment variables or private deployment files.
6. Use `runtime_impl` and `scripts` as canonical source; deploy copies to nodes.

This repo is meant to make the experiment auditable. It is not intended to
include raw private logs or machine-local state.
