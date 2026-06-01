# DB-Free Stage Rehearsal Report: tr

> This artifact is a DB-free pre-formal stage rehearsal report. It is not formal experimental evidence and is excluded from CR, CR2, Run B, CF, statistical testing, official threshold estimation, effect-size estimation, and causal interpretation.

- Status: `PASS`
- Created UTC: `20260601T061716Z`
- Stage: `tr`
- Condition: `run_b`
- Run mode: `smoke`
- DB write policy: `disabled via temporary Harness config`
- Evidence boundary: `rehearsal artifact; not formal evidence`
- Evidence target: `Markdown report; JSONL scratch ignored by Git`
- Harness /turn usage: `temporary DB-disabled Harness only`
- Formal analysis inclusion: `excluded`
- Harness URL used: `http://10.1.1.110:9010`
- Scenario: `/home/morophi/agent/scenario/lacp_30turn_civil_complaint_v1.json`
- Run IDs: `preformal_tr_20260601T061600Z_rep01`

## Gate Results

| Step | Status | Return code |
| --- | --- | --- |
| `prepare:db_disabled_config` | PASS | 0 |
| `prepare:clear_temp_port` | PASS | 0 |
| `prepare:start_temp_harness` | PASS | 0 |
| `verify:temp_harness_route` | PASS | 0 |
| `execute:stage_runner_db_disabled` | PASS | 0 |
| `fetch:jsonl:preformal_tr_20260601T061600Z_rep01` | PASS | 0 |
| `verify:dblog_zero_rows` | PASS | 0 |
| `cleanup:stop_temp_harness` | PASS | 0 |

## JSONL Summary

```json
{
  "analysis_eligible": {
    "False": 4,
    "True": 2
  },
  "conditions": {
    "run_b": 6
  },
  "errors": [],
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
  "run_modes": {
    "smoke": 6
  },
  "runs": {
    "preformal_tr_20260601T061600Z_rep01": {
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
  "sc_policy_applied": {
    "False": 4,
    "True": 2
  },
  "total_rows": 6
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
stage_run_start run_id=preformal_tr_20260601T061600Z_rep01
scenario_id=lacp_30turn_civil_complaint_v1 turns=2/30 scenario_hash=8303dd12a5e488ea546114e074742ed272af928cdc836fa10057aabcf0b79369
send turn=1 endpoint=http://10.1.1.110:9010/turn
ack turn=1 nodes_completed=A,B,C
send turn=2 endpoint=http://10.1.1.110:9010/turn
ack turn=2 nodes_completed=A,B,C
log_flush ok
stage_run_done run_id=preformal_tr_20260601T061600Z_rep01
```

stderr:
```text
(empty)
```

### fetch:jsonl:preformal_tr_20260601T061600Z_rep01

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
