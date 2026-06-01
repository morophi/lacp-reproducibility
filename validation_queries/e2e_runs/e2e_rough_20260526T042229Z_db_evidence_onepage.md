# LACP 3-Turn E2E Rough Smoke DB Evidence

Generated: 2026-05-26  
Run ID: `e2e_rough_20260526T042229Z`  
Run mode: `smoke`  
Scenario: `/home/morophi/agent/scenario/lacp_scenario_base_v2.json`  
Scenario hash: `025884c27aa9bdf041359862433b9d888a8e20c3e2bf61a2d4af3fcda6478979`

## 1. Execution Summary

| Item | Count / Status |
|---|---:|
| Requested turns | 3 |
| Completed turns | 3 |
| Nodes per turn | 3 |
| Expected node-turn rows | 9 |
| Actual JSONL rows | 9 |
| Agent turn acknowledgements | 3 / 3 |
| A/B/C completion coverage | 9 / 9 |
| Empty response rows | 0 / 9 |
| Thinking content rows | 0 / 9 |

## 2. dblog Persistence

| dblog table | Rows for run_id |
|---|---:|
| `turn_node_logs` | 9 |
| `intervention_logs` | 9 |
| `metric_logs` | 9 |
| Total persisted core rows | 27 |

## 3. Routing and Intervention Invariants

| Invariant | Count |
|---|---:|
| Node A RAG injected | 3 / 3 |
| Node B RAG injected | 3 / 3 |
| Node C RAG injected | 0 / 3 |
| Node A SC policy applied | 3 / 3 |
| Node B SC policy applied | 0 / 3 |
| Node C SC policy applied | 0 / 3 |
| RAG rows missing chunk ids | 0 |
| Sidecar prompt injection rows | 0 |

## 4. Response Length Evidence

| Turn | Node A chars | Node B chars | Node C chars | Turn total |
|---:|---:|---:|---:|---:|
| 1 | 459 | 449 | 185 | 1,093 |
| 2 | 619 | 792 | 360 | 1,771 |
| 3 | 693 | 763 | 375 | 1,831 |
| Total | 1,771 | 2,004 | 920 | 4,695 |

## 5. Metric Status

| Metric condition | Count |
|---|---:|
| MA available | 9 / 9 |
| LMS available | 0 / 9 |
| CDS available | 0 / 9 |
| Validator metric-complete rows | 0 / 9 |
| Validator status | `blocked` |

Metric completeness was blocked because smoke mode uses the native Ollama chat endpoint, which does not provide token-level logprobs for LMS, and the CDS reference embedding file was absent at `/home/morophi/harness/reference/reference_embedding.npy`.

## 6. Interpretation

This run demonstrates E2E path execution and persistence: Agent -> Harness -> RAG/A/B/C -> dblog. It is valid as rough execution evidence, not as metric-complete formal evidence.

Follow-up sync check after remote harness policy-field update:

| Run ID | Turns | `turn_node_logs` | `intervention_logs` | `metric_logs` | `history_eligible` in JSONL |
|---|---:|---:|---:|---:|---|
| `e2e_sync_check_20260526T0435Z` | 1 | 3 | 3 | 3 | true for A/B/C |
