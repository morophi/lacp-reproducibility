# LACP Results Readiness Addendum: Async DB Writer Check

**Date:** 2026-05-27  
**Purpose:** Record the readiness decision for asynchronous MariaDB logging before formal runs.  
**Manuscript status:** Do not include these benchmark tables in the paper results. This is an experiment-operations and validity note.

---

## 1. Question

After moving MariaDB writes behind an async queue, does DB persistence introduce meaningful jitter into actual measured turns or formal run execution?

---

## 2. Measurement Layers

Three layers were checked.

| Layer | Inference Nodes | What It Tests |
|---|---:|---|
| synthetic logger | No | enqueue latency, DB drain, flush accumulation |
| stage-like runner | No | real `ExperimentRunner` path with fake node responses |
| real smoke | Yes | actual `/turn` latency and run-end `/flush` under A/B/C inference |

---

## 3. Synthetic Logger Results

Async composite burst showed that DB cost is moved, not eliminated:

| Mode | Turn Gap | Enqueue p95/row | Flush | Max Queue |
|---|---:|---:|---:|---:|
| async composite burst | 0ms | under 0.2ms | about 0.95s | 89 |
| async composite paced | 20ms | under 0.2ms | 0.28-0.44s | 31-37 |
| async composite paced | 50ms | about 0.24ms | 27-28ms | 5-7 |
| async composite paced | 100ms | about 0.37ms | 27-29ms | 2 |

Interpretation:

```text
Async DB write is safe only when writer drain rate exceeds row production rate.
Under realistic turn gaps, backlog collapses quickly.
Under zero-gap burst, cost appears at flush.
```

---

## 4. Stage-Like Runner Results

The `ExperimentRunner.handle_turn()` path was executed with fake node responses.

| Mode | Fake Node Latency | Condition | Mean /turn | p95 /turn | Flush | Max Queue |
|---|---:|---|---:|---:|---:|---:|
| async | 0ms | CR | 1.70ms | 2.25ms | 1016ms | 89 |
| async | 0ms | Run B | 1.77ms | 2.52ms | 1022ms | 89 |
| async | 50ms | CR | 52.13ms | 52.57ms | 33ms | 5 |
| async | 50ms | Run B | 52.94ms | 54.32ms | 35ms | 5 |
| async | 100ms | CR | 102.19ms | 102.64ms | 34ms | 3 |
| async | 100ms | Run B | 102.71ms | 104.19ms | 35ms | 2 |
| sync | 0ms | CR | 37.88ms | 44.45ms | about 0ms | 0 |
| sync | 0ms | Run B | 38.59ms | 44.77ms | about 0ms | 0 |
| sync | 50ms | CR | 88.23ms | 94.17ms | about 0ms | 0 |
| sync | 50ms | Run B | 90.79ms | 95.17ms | about 0ms | 0 |

Interpretation:

```text
Synchronous DB writes add roughly 35-40ms to each turn barrier.
Async DB writes remove that barrier cost when even modest per-turn work is present.
```

---

## 5. Real Smoke Results

After Node A transport was restored, real A/B/C inference smoke was executed.

| Run | Turns | Condition | Turn Latency | Flush |
|---|---:|---|---:|---:|
| smoke | 1 | CR | 10.64s | 140ms |
| smoke | 1 | Run B | 20.59s | 81ms |
| smoke | 2 | CR | mean 4.84s, p95 6.27s | 43ms |
| smoke | 2 | Run B | mean 17.13s, p95 17.44s | 66ms |
| smoke | 5 | CR | mean 8.51s, median 6.87s, p95 13.31s | 65ms |

Interpretation:

```text
In actual inference conditions, DB flush remained below 150ms and did not show accumulating backlog.
```

---

## 6. Cleanup

Benchmark rows were removed after measurement.

Confirmed zero matching rows for benchmark prefixes on:

```text
experiment_runs
v_turn_node_logs
v_intervention_logs
v_metric_logs
v_rag_retrieval_logs
v_payload_audit_logs
```

---

## 7. Readiness Decision

**Decision:** Async DB logging is not a current formal-run blocker.

Rationale:

- Real turn latency is seconds-level.
- Async DB flush stayed in the 43-140ms range during real smoke.
- Stage-like tests showed the writer drains reliably once per-turn work is at least 50ms.
- Synchronous DB logging would add approximately 35-40ms per turn barrier; async removes this barrier contribution.

---

## 8. Conditions for Recheck

Re-run this readiness check if any of the following changes:

- model endpoint latency drops into sub-50ms turn intervals,
- MariaDB schema or indexes change,
- DB host or network path changes,
- queue size or flush timeout changes,
- benchmark `/flush` exceeds 500ms repeatedly,
- row-count checks fail after successful `/flush`,
- or Harness logs show async writer warnings.

---

## 9. Paper Boundary

This addendum should support experiment operations and auditability only.

Recommended manuscript-level wording, if needed in methods:

```text
Runtime evidence was written to local JSONL synchronously and mirrored to MariaDB through an asynchronous writer flushed at run boundaries.
```

Do not include the operational jitter benchmark table in the paper results unless reviewers specifically ask for infrastructure timing validation.

