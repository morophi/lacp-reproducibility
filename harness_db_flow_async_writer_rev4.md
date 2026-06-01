# LACP Harness DB Flow rev4: Async MariaDB Writer

**Date:** 2026-05-27  
**Scope:** Harness file/data-flow guide for asynchronous dblog persistence.  
**Supersedes for logging flow:** the synchronous DB-write description in earlier harness DB flow notes.

---

## 1. Runtime Flow

The Harness runtime still owns the full experiment-control path:

```text
Agent scenario sender
-> Harness POST /turn
-> ExperimentRunner.handle_turn()
-> intervention planning
-> prompt construction
-> A/B/C inference
-> quality gate
-> metrics
-> JSONL write
-> MariaDB enqueue
-> HTTP /turn response
```

MariaDB transaction execution now happens after enqueue, in a background writer thread.

---

## 2. Logger Classes

The relevant logger classes are:

| Class | Responsibility |
|---|---|
| `JSONLLogger` | Appends local JSONL evidence synchronously |
| `MariaDBLogger` | Performs normalized FK-schema upserts using PyMySQL |
| `AsyncMariaDBLogger` | Queue-backed wrapper around `MariaDBLogger` |
| `CompositeLogger` | Writes JSONL first, then DB or async DB |

`MariaDBLogger` remains the source of truth for SQL mapping. The async wrapper does not change row contents or table mapping.

---

## 3. Async Writer Semantics

`AsyncMariaDBLogger.log_turn()` places `(run_id, row)` onto a bounded queue.

The worker thread then calls the existing `MariaDBLogger.log_turn()` method, which performs:

```text
experiment_runs upsert/cache lookup
-> turn_node_logs upsert
-> intervention_logs upsert
-> metric_logs upsert
-> payload_audit_logs upsert
-> optional rag_retrieval_logs upsert
-> commit
```

Operational consequence:

- `/turn` waits for JSONL write and queue insertion.
- `/turn` does not wait for the MariaDB transaction unless the queue is full.
- `/flush` waits until all previously queued DB writes are complete.

---

## 4. Queue and Flush

Configuration fields in `node_config.yaml`:

```yaml
logging:
  db:
    enabled: true
    async_enabled: true
    async_queue_maxsize: 1000
    async_flush_timeout_s: 30
```

Harness exposes:

```text
POST /flush?timeout=30
```

Expected response:

```json
{"ok": true}
```

The agent sender calls `/flush` after a scenario finishes. Stage scripts must run dblog row-count checks only after that flush succeeds.

---

## 5. Failure Behavior

JSONL is still written first. Therefore:

- DB failure does not erase local evidence.
- Async worker failure is surfaced on `/flush` or `close()`.
- A failed `/flush` blocks analysis readiness.

If async worker failure occurs:

1. Preserve JSONL artifacts.
2. Do not treat MariaDB row counts as complete.
3. Inspect Harness logs for async writer warnings.
4. Re-run DB sync or replay only if the run policy permits it.

---

## 6. Benchmark Scripts

The following benchmark scripts are now part of the operations toolkit:

| Script | Node inference needed | Purpose |
|---|---:|---|
| `verify_remote/logger_overhead_benchmark.py` | No | Synthetic row enqueue/write/flush measurement |
| `verify_remote/stage_like_logger_benchmark.py` | No | Full `ExperimentRunner` path with fake node client |
| `verify_remote/real_turn_latency_benchmark.py` | Yes | Real `/turn` latency and `/flush` measurement |

Benchmark rows use synthetic prefixes such as:

```text
logger_%
stage_like_logger_%
real_logger_bench_%
```

Benchmark cleanup must delete matching `experiment_runs` rows and confirm FK cascade leaves all dependent views at zero matching rows.

---

## 7. Cleanup Verification Pattern

After benchmark cleanup, confirm zero rows on all six surfaces:

```sql
SELECT COUNT(*) FROM experiment_runs WHERE run_id LIKE '<prefix>%';
SELECT COUNT(*) FROM v_turn_node_logs WHERE run_id LIKE '<prefix>%';
SELECT COUNT(*) FROM v_intervention_logs WHERE run_id LIKE '<prefix>%';
SELECT COUNT(*) FROM v_metric_logs WHERE run_id LIKE '<prefix>%';
SELECT COUNT(*) FROM v_rag_retrieval_logs WHERE run_id LIKE '<prefix>%';
SELECT COUNT(*) FROM v_payload_audit_logs WHERE run_id LIKE '<prefix>%';
```

Expected result:

```text
0
0
0
0
0
0
```

---

## 8. Operational Decision

The current DB flow is accepted for short formal readiness smoke because real inference latency provides sufficient time for the background writer to drain.

The async writer should be revisited if:

- inference latency drops below the observed seconds-level range,
- MariaDB lock contention appears,
- `/flush` duration grows materially,
- queue full blocking is observed,
- or formal row-count checks intermittently fail after flush.

