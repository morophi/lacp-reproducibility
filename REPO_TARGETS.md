# Repository Targets and Node Mapping

The GitHub repository should be managed as one canonical repo. Remote nodes are
deployment targets, not independent source-of-truth repositories.

## Git Status Audit

Checked on 2026-06-01:

| Node | Git repo found | Recommended role |
| --- | --- | --- |
| Local workspace | No `.git` before initialization | Canonical source-of-truth repo |
| `jump` | None | Agent deployment target |
| `harness` | None | Harness deployment target |
| `rag` | None | RAG/Chroma service and ingest deployment target |
| `dblog` | None | DB schema/logging target |
| `inference1` | None | Ollama inference target |
| `inference2` | None | Ollama inference target |
| `inference3` | None | Ollama inference target |

## Deployment Mapping

| Repo path | Node target | Remote path | Notes |
| --- | --- | --- | --- |
| `runtime_impl/agent/*.py` | `jump` | `/home/morophi/agent/` | Scenario replay and stage orchestration |
| `runtime_impl/agent/scenario/*` or selected fixtures | `jump` | `/home/morophi/agent/scenario/` | Immutable scenario input |
| `runtime_impl/harness/*` | `harness` | `/home/morophi/harness/` | Harness runtime |
| `runtime_impl/harness/config/*.yaml` | `harness` | `/home/morophi/harness/config/` | Use private env/local secret values at deploy time |
| `runtime_impl/harness/config/*.json` | `harness` | `/home/morophi/harness/config/` | Theta/reference config |
| `runtime_impl/harness/reference/*` | `harness` | `/home/morophi/harness/reference/` | Fixed CDS reference artifacts; large binaries stay out of Git |
| `scripts/01_*` to `scripts/15_*` | local/RAG | project or RAG ingest path | Corpus build and retrieval validation |
| `scripts/16_*` to `scripts/25_*` | local/jump/harness as needed | stage-specific | Freeze, preflight, and E2E helpers |
| `dblog_schema/*.sql` | `dblog` | operator-selected SQL path | Schema and migration checks |
| `inference_nodes/<node>/Modelfile` | inference nodes | `/home/morophi/Modelfile` | Ollama model template for qwen3-nothink |
| `inference_nodes/<node>/node_temp.py` | inference nodes | `/home/morophi/node_temp.py` | Thermal readout helper |
| `node_temp.py` | inference nodes | `/home/morophi/node_temp.py` | Shared copy of thermal readout helper |
| `jump_temp_monitor.py` | `jump` | `/home/morophi/jump_temp_monitor.py` | Temperature monitor wrapper |
| `runtime_impl/agent/scenario/*` | `jump` | `/home/morophi/agent/scenario/` | Scenario fixtures captured from the active node |
| `runtime_impl/*/*benchmark*.py` and smoke/check helpers | selected nodes | node-local helper paths | Reproducibility helpers, not formal run outputs |

## Do Not Track

- Virtual environments: `.venv`, `harness_venv`, `RAG`, inference venvs
- ChromaDB runtime data: `chromadb_data`
- Raw conversation exports
- SSH keys and node-specific `.ssh` material
- Tailscale status JSON and network adapter dumps
- Raw thermal/E2E JSONL logs except curated summaries
- Plaintext DB or sudo passwords

## Current Consistency Notes

- `top_k=3` is now reflected in source configs for formal RAG and counterfactual paths.
- `jump` stage runner was updated to support `cf_a` through `cf_f`.
- Remote deployment copies should be regenerated from this repo after changes.
