# Revision Note: Paper Rev8 Thermal Barrier Control

Date: 2026-05-26

## Summary

Paper rev8 introduces a mandatory thermal safeguard and turn-level
synchronization policy for the LACP experiment. The update was made after
thermal-only direct inference probing showed that a short five-turn load can
raise inference-node temperatures from the high-40 C range to approximately
69-74 C.

## Reason for Major Update

The experiment uses three on-premises inference nodes running concurrently.
Without explicit synchronization and cooldown control, node-level completion
time differences and thermal accumulation may introduce uncontrolled variation
into TR, CR, CR2, CF, and CF-F runs.

The update therefore formalizes two controls:

1. Turn-level barrier
   - Harness dispatches the same turn to Nodes A, B, and C.
   - Harness waits until all three nodes complete and logs are persisted.
   - Only then can the next turn begin.

2. Five-turn cooldown
   - After every five completed turns, Harness records thermal snapshots.
   - Harness pauses dispatch for 30 seconds.
   - Harness records post-cooldown thermal snapshots before resuming.

## Evidence Basis

Thermal-only direct inference probe:

```text
run_id = thermal_only_5turn_20260526T063544Z
mode = thermal_only_direct_inference
nodes = inference1, inference2, inference3
turns = 5
cooldown_observation = 10 seconds
inference_requests = 15
inference_failures = 0
```

Observed maximum temperatures:

```text
inference1: initial 48.375 C, peak 74.0 C, cooldown-end 67.5 C
inference2: initial 49.5 C,   peak 69.0 C, cooldown-end 64.0 C
inference3: initial 49.375 C, peak 74.0 C, cooldown-end 67.375 C
```

Interpretation:

```text
Full-speed fan operation is a minimum defensive condition for formal RUN stages.
Cooldown is required to reduce node instability and data-loss risk.
Thermal control is an operational validity control, not a causal treatment.
```

## Files Synchronized

```text
experiment/lacp_ijibc_rev8.docx
experiment/lacp_experiment_guideline_rev5.5.md
experiment/lacp_node_checklist_v10.4.md
experiment/harness_file_structure_and_db_flow_rev3.md
revision_notes/20260526_rev8_thermal_barrier_control.md
```

## Policy Status

The policy is mandatory for TR, CR, CR2, CF, and CF-F unless explicitly disabled
for a separate diagnostic-only run. If disabled, the reason must be recorded in
the run metadata and the run must not be compared as a formal causal run unless
the same setting is applied symmetrically across all conditions.

## Open Implementation Tasks

```text
□ Add thermal_policy config to Harness.
□ Enforce turn-level barrier in ExperimentRunner if not already explicit.
□ Add five-turn cooldown hook after turn_no % 5 == 0.
□ Add thermal snapshot collection for inference1/2/3.
□ Add JSONL fallback rows for cooldown_start and cooldown_end.
□ Decide whether to add dedicated thermal_event_logs DB migration.
□ Exclude thermal event rows from metric completeness checks.
```
