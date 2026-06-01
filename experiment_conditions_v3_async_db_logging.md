# LACP Experiment Conditions v3: Async DB Logging Addendum

**Date:** 2026-05-27  
**Scope:** Operational experiment-condition addendum for Harness logging behavior.  
**Not for manuscript results:** This document records runtime evidence-writing conditions, not causal findings.

---

## 1. Purpose

This addendum updates the experiment execution conditions after replacing synchronous MariaDB writes on the `/turn` barrier with an asynchronous DB writer.

The change is an infrastructure-readiness measure. Its purpose is to prevent database persistence latency from becoming a material part of per-turn model-response timing while preserving the same evidence ledger.

---

## 2. Logging Policy

The Harness uses two evidence paths:

1. **Synchronous JSONL fallback**
   - JSONL remains the first write.
   - JSONL is still the durable local fallback if MariaDB is unavailable or delayed.
   - JSONL write remains part of the `/turn` path.

2. **Asynchronous MariaDB mirror**
   - MariaDB writes are queued after JSONL.
   - A background worker drains the queue using the existing normalized FK schema writer.
   - The DB writer still writes the same logical rows:
     - `experiment_runs`
     - `turn_node_logs`
     - `intervention_logs`
     - `metric_logs`
     - `rag_retrieval_logs`
     - `payload_audit_logs`

The normalized dblog schema and JSONL schema are not changed by this addendum.

---

## 3. Run-Boundary Flush Requirement

Every measured run must end with an explicit DB flush before row-count checks or downstream analysis.

Operational rule:

```text
send all turns
-> POST /flush
-> verify dblog row counts
-> export or analyze
```

The `scenario_sender.py` runtime path now calls Harness `/flush` after all turns are sent. This prevents a race in which the agent checks MariaDB before the async writer has drained queued rows.

If `/flush` fails, times out, or returns `ok=false`, the run is not analysis-ready even if JSONL exists.

---

## 4. Formal-Run Interpretation

Per-turn response latency should be interpreted as:

```text
node inference + prompt assembly + quality gate + metrics + JSONL enqueue + DB enqueue
```

It should no longer include full MariaDB transaction latency in the normal case.

Run-end latency includes any remaining DB queue drain time:

```text
run completion latency = final /turn completion + /flush duration
```

For formal reporting, keep model-response timing and DB flush timing separate.

---

## 5. Readiness Criteria

Before formal runs, the following must be true:

| Item | Required State |
|---|---|
| JSONL fallback | Enabled and writable |
| MariaDB async writer | Enabled |
| `/flush` endpoint | Returns `{"ok": true}` |
| row-count check | Runs after `/flush`, not before |
| DB cleanup after benchmark | Verified on all six data surfaces |
| worker error | No async writer error observed |

---

## 6. Current Readiness Decision

Based on synthetic, stage-like, and real smoke measurements on 2026-05-27, async MariaDB logging is no longer considered a formal-run blocker under the current inference latency regime.

This decision is conditional on:

- A/B/C inference latency remaining in the observed seconds-level range.
- MariaDB not showing lock contention or transport instability.
- `/flush` remaining successful at run boundaries.

If a future model or endpoint reduces turn latency to sub-50ms ranges, the async DB writer must be re-benchmarked because queue backlog can reappear when row production exceeds writer drain rate.

