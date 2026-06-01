# Revision Note: Harness Eligibility Separation Policy

Date: 2026-05-25

## Purpose

This revision records the Harness policy update that separates analysis
eligibility, trigger eligibility, and history eligibility. The change prevents
one exclusion decision from being over-applied to every downstream path.

## Summary

The Harness now treats exclusion as three separate decisions:

```text
analysis_eligible
  Controls causal/statistical analysis inclusion.

exclude_from_causal_trigger
  Controls whether a previous node-turn can influence later intervention
  trigger timing.

history_eligible
  Controls whether a response is appended to future node conversation history.
```

## Files Changed

```text
runtime_impl/harness/quality_gate.py
runtime_impl/harness/metrics.py
runtime_impl/harness/trigger_controller.py
runtime_impl/harness/experiment_runner.py
runtime_impl/harness/logger.py
runtime_impl/harness/tests/test_quality_gate.py
runtime_impl/harness/tests/test_trigger_controller.py
runtime_impl/harness/HARNESS_POLICY.md
dblog_schema/lacp_db_schema.sql
dblog_schema/20260525_add_eligibility_separation_fields.sql
harness_file_structure_and_db_flow.md
```

## Policy Decisions

### Analysis Eligibility

`analysis_eligible=false` means the row should not enter causal/statistical
analysis. It does not automatically remove the response from future
conversation history.

### Trigger Eligibility

Row-level trigger exclusion remains controlled by:

```text
exclude_from_causal_trigger=true
analysis_eligible=false
```

Metric-level trigger eligibility was added so missing logprobs disable LMS
trigger evidence without necessarily disabling CDS or MA trigger evidence.

```text
lms_trigger_eligible
cds_trigger_eligible
ma_trigger_eligible
overall_trigger_eligible=policy_dependent
```

### History Eligibility

`history_eligible=false` is limited to hard context failures. The current hard
history exclusion reasons are:

```text
infrastructure_invalid
empty_response
thinking_content_present
truncation_risk, in formal mode
language_contamination
intervention_contamination
```

Policy-anchor failure alone is not automatically history-ineligible. It remains
analysis/trigger-ineligible but can stay in history when the response is
otherwise coherent.

## Runtime Behavior Changes

Formal `failed_TR` no longer raises before logging. The row is now preserved in
JSONL and DB, then marked ineligible for analysis, trigger, and history where
appropriate.

`ExperimentRunner` appends node history only when `history_eligible=true`.
Hard-failure responses remain evidence but do not become future prompt context.

`TriggerController` masks only the metric families that are ineligible. For
example, missing logprobs mask `lms_delta` while leaving CDS and MA available if
their own eligibility flags are true.

## DB Changes

Added migration:

```text
dblog_schema/20260525_add_eligibility_separation_fields.sql
```

New `turn_node_logs` fields:

```text
history_eligible
history_exclusion_reason
metric_trigger_eligibility
```

New `metric_logs` field:

```text
metric_trigger_eligibility
```

## Verification

Commands run:

```powershell
python -m py_compile runtime_impl\harness\quality_gate.py runtime_impl\harness\metrics.py runtime_impl\harness\trigger_controller.py runtime_impl\harness\experiment_runner.py runtime_impl\harness\logger.py
```

Result:

```text
pass
```

Command run:

```powershell
python run_unit_tests_no_pytest.py
```

Working directory:

```text
C:\Users\morophi\OneDrive\문서\New project\runtime_impl\harness
```

Result:

```text
passed=31 failed=0
```

## Notes

The DB migration must be applied on the dblog node before running a Harness
version that writes the new eligibility columns to MariaDB. JSONL fallback will
include the new fields immediately because it writes the full row object.
