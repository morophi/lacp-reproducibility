# DB-Free Stage Rehearsal Report: tr

> This artifact is a DB-free pre-formal stage rehearsal report. It is not formal experimental evidence and is excluded from CR, CR2, Run B, CF, statistical testing, official threshold estimation, effect-size estimation, and causal interpretation.

- Status: `BLOCKED`
- Created UTC: `20260601T061459Z`
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
- Run IDs: `(none)`

## Gate Results

| Step | Status | Return code |
| --- | --- | --- |
| `prepare:db_disabled_config` | PASS | 0 |
| `prepare:clear_temp_port` | PASS | 0 |
| `prepare:start_temp_harness` | PASS | 0 |
| `verify:temp_harness_route` | BLOCKED | 7 |
| `cleanup:stop_temp_harness` | PASS | 0 |

## JSONL Summary

```json
{}
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

- Status: `BLOCKED`
- Return code: `7`

stdout:
```text
000
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
