# DB-Disabled Harness Stage Rehearsal Report: tr

> This artifact is a DB-disabled Harness stage rehearsal report. It is not a DB-free direct inference readiness gate, not a formal stage run, and not formal experimental evidence. It is excluded from CR, CR2, Run B, CF, statistical testing, official threshold estimation, effect-size estimation, and causal interpretation.

- Status: `PASS`
- Created UTC: `20260601T063629Z`
- Rehearsal type: `db_disabled_harness_stage_rehearsal`
- Target formal stage: `TR`
- Formal stage executed: `False`
- Formal stage replacement: `False`
- Formal evidence: `False`
- Stage runner argument: `tr`
- Condition: `run_b`
- Run mode: `smoke`
- DB write policy: `disabled via temporary Harness config`
- Evidence boundary: `rehearsal artifact; not formal evidence`
- Evidence target: `Markdown report; JSONL scratch ignored by Git`
- Harness /turn usage: `temporary DB-disabled Harness only`
- Formal analysis inclusion: `excluded`
- Harness URL used: `http://10.1.1.110:9010`
- Scenario: `/home/morophi/agent/scenario/lacp_30turn_civil_complaint_v1.json`
- Run IDs: `preformal_tr_20260601T063458Z_rep01`

## Scope

- Rehearse the target formal stage orchestration path through a temporary DB-disabled Harness.
- Verify A/B/C dispatch and turn barrier completion.
- Verify JSONL scratch capture and experimental DB zero-row boundary.
- Verify cleanup of the temporary Harness and request inference runner unload/settle after rehearsal.

## Explicit Non-Claims

- This is not the DB-free direct inference readiness gate; that gate does not call Harness `/turn`.
- This is not formal TR and does not replace formal TR.
- This does not claim formal MariaDB write-path validity because DB writes are intentionally disabled.
- This does not claim formal quality-analysis readiness, threshold validity, effect size, or causal interpretation.

## Route Probe Interpretation

- Expected status: `405`
- Reason: `/turn` is POST-only; a GET returning 405 confirms the temporary Harness is reachable and the route exists.

## Rehearsal Metadata

```json
{
  "db_write_enabled": false,
  "db_zero_rows_verified": true,
  "expected_route_probe_status": 405,
  "formal_evidence": false,
  "formal_stage_executed": false,
  "formal_stage_replacement": false,
  "generation_quality_ready_interpretation": "Not required for this orchestration rehearsal. Rows may be marked false because of truncation_risk while still proving dispatch, response, logprobs, routing, scratch capture, and DB-zero boundaries.",
  "generation_quality_ready_rows": "2/6",
  "harness_turn_called": true,
  "harness_turn_scope": "temporary DB-disabled Harness only",
  "quality_claim": "path/orchestration readiness only; formal quality-analysis readiness is not claimed",
  "rehearsal_type": "db_disabled_harness_stage_rehearsal",
  "route_probe_interpretation": "POST-only /turn route is reachable when GET returns 405",
  "runner_unload_requested_after_rehearsal": true,
  "settle_completed_after_rehearsal": true,
  "target_formal_stage": "TR"
}
```

## Gate Results

| Step | Status | Return code |
| --- | --- | --- |
| `prepare:db_disabled_config` | PASS | 0 |
| `prepare:clear_temp_port` | PASS | 0 |
| `prepare:start_temp_harness` | PASS | 0 |
| `verify:temp_harness_route` | PASS | 0 |
| `execute:stage_runner_db_disabled` | PASS | 0 |
| `fetch:jsonl:preformal_tr_20260601T063458Z_rep01` | PASS | 0 |
| `verify:dblog_zero_rows` | PASS | 0 |
| `cleanup:inference_runner_unload_keep_alive_0` | PASS | 0 |
| `cleanup:inference_runner_settle` | PASS | 0 |
| `cleanup:stop_temp_harness` | PASS | 0 |

## Quality Flag Interpretation

`generation_quality_ready` is reported for transparency but is not the pass/fail criterion for this rehearsal. The pass claim is limited to path/orchestration readiness, A/B/C completion, scratch artifact capture, and DB-zero boundary. Rows marked not generation-quality-ready are still useful here when response text, logprobs, and path-ready signals exist; they remain excluded from formal quality analysis.

## JSONL Summary

```json
{
  "analysis_eligible": {
    "False": 4,
    "True": 2
  },
  "clean_logprobs_positive_rows": 6,
  "conditions": {
    "run_b": 6
  },
  "empty_thinking_shell_rows": 6,
  "errors": [],
  "node_b_sc_policy_prompt_mutation_rows": 0,
  "node_c_rag_contamination_rows": 0,
  "nodes": {
    "A": 2,
    "B": 2,
    "C": 2
  },
  "nonempty_response_text_rows": 6,
  "path_ready_rows": 6,
  "quality_ready": {
    "False": 4,
    "True": 2
  },
  "rag_injected": {
    "False": 2,
    "True": 4
  },
  "raw_logprobs_positive_rows": 6,
  "returned_count_not_topk3_rows": 0,
  "run_modes": {
    "smoke": 6
  },
  "runs": {
    "preformal_tr_20260601T063458Z_rep01": {
      "analysis_eligible": {
        "False": 4,
        "True": 2
      },
      "nodes": {
        "A": 2,
        "B": 2,
        "C": 2
      },
      "quality_ready": {
        "False": 4,
        "True": 2
      },
      "rag_injected": {
        "False": 2,
        "True": 4
      },
      "rows": 6,
      "sc_policy_applied": {
        "False": 4,
        "True": 2
      },
      "turns": [
        1,
        2
      ]
    }
  },
  "runtime_error_rows": 0,
  "sc_policy_applied": {
    "False": 4,
    "True": 2
  },
  "thinking_content_present_rows": 0,
  "total_rows": 6,
  "truncation_risk_rows": 4,
  "usable_as_quality_outcome_rows": 6
}
```

## Command Outputs

### prepare:db_disabled_config

- Status: `PASS`
- Return code: `0`

stdout:
```text
/tmp/lacp_preformal_node_config_9010.json
```

stderr:
```text
(empty)
```

### prepare:clear_temp_port

- Status: `PASS`
- Return code: `0`

stdout:
```text
(empty)
```

stderr:
```text
(empty)
```

### prepare:start_temp_harness

- Status: `PASS`
- Return code: `0`

stdout:
```text
(empty)
```

stderr:
```text
(empty)
```

### verify:temp_harness_route

- Status: `PASS`
- Return code: `0`

stdout:
```text
405
```

stderr:
```text
(empty)
```

### execute:stage_runner_db_disabled

- Status: `PASS`
- Return code: `0`

stdout:
```text
stage_plan stage=tr condition=run_b run_mode=smoke repetitions=1 turns_per_run=2 causal_evidence=False
stage_run_start run_id=preformal_tr_20260601T063458Z_rep01
scenario_id=lacp_30turn_civil_complaint_v1 turns=2/30 scenario_hash=8303dd12a5e488ea546114e074742ed272af928cdc836fa10057aabcf0b79369
send turn=1 endpoint=http://10.1.1.110:9010/turn
ack turn=1 nodes_completed=A,B,C
send turn=2 endpoint=http://10.1.1.110:9010/turn
ack turn=2 nodes_completed=A,B,C
log_flush ok
stage_run_done run_id=preformal_tr_20260601T063458Z_rep01
```

stderr:
```text
(empty)
```

### fetch:jsonl:preformal_tr_20260601T063458Z_rep01

- Status: `PASS`
- Return code: `0`

stdout:
```text
(empty)
```

stderr:
```text
(empty)
```

### verify:dblog_zero_rows

- Status: `PASS`
- Return code: `0`

stdout:
```text
{"experiment_runs": 0, "intervention_logs": 0, "metric_logs": 0, "payload_audit_logs": 0, "rag_retrieval_logs": 0, "turn_node_logs": 0}
```

stderr:
```text
(empty)
```

### cleanup:inference_runner_unload_keep_alive_0

- Status: `PASS`
- Return code: `0`

stdout:
```text
{"event": "unload_start", "timeout_s": 30.0}
{"node": "A", "host": "10.1.1.10", "ok": true, "status": 200, "elapsed_ms": 4.2, "bytes": 120}
{"node": "B", "host": "10.1.1.20", "ok": true, "status": 200, "elapsed_ms": 2.3, "bytes": 120}
{"node": "C", "host": "10.1.1.30", "ok": true, "status": 200, "elapsed_ms": 2.3, "bytes": 120}
```

stderr:
```text
(empty)
```

### cleanup:inference_runner_settle

- Status: `PASS`
- Return code: `0`

stdout:
```text
settle_sec=15.0
```

stderr:
```text
(empty)
```

### cleanup:stop_temp_harness

- Status: `PASS`
- Return code: `0`

stdout:
```text
(empty)
```

stderr:
```text
(empty)
```
