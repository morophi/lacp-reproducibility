# Revision Note: Thermal Decay Validation for Rev8.1

Date: 2026-05-26

## Summary

A second thermal-only validation run was performed to strengthen the empirical
basis for the rev8 thermal safeguard. The script was revised to collect
inference-node temperatures in parallel, then the cooldown observation window
was extended to 60 seconds.

## Validation Run

```text
run_id = thermal_only_5turn_cooldown60_parallel_20260526T170010
mode = thermal_only_direct_inference
nodes = inference1, inference2, inference3
turns = 5
thermal_interval_sec = 1.0
observed_average_sample_interval = approximately 1.004 sec
cooldown_sec = 60.0
inference_requests = 15
inference_failures = 0
```

## Results

```text
inference1: 72.0 C -> 51.875 C, drop 20.125 C
inference2: 69.0 C -> 52.25 C,  drop 16.75 C
inference3: 73.0 C -> 52.125 C, drop 20.875 C
```

## Interpretation

The cooldown series showed an early-fast and late-slow cooling profile. Linear
fits were visually plausible over short windows, but quadratic and
exponential-style fits reduced residual error by approximately one to two
orders of magnitude. Therefore, the cooldown behavior should not be documented
as a simple linear function.

This supports the following experimental controls:

```text
□ Full-speed fan operation as the default defensive state.
□ Turn-level barrier for A/B/C synchronization.
□ Five-turn cooldown as an operational validity safeguard.
□ Parallel thermal sampling for run-control evidence.
□ Thermal event logging independent from causal metric rows.
```

## Files Updated

```text
experiment/lacp_experiment_guideline_rev5.6.md
experiment/lacp_node_checklist_v10.5.md
experiment/harness_file_structure_and_db_flow_rev3.1.md
experiment/lacp_ijibc_rev8.1.docx
revision_notes/20260526_thermal_decay_validation.md
```
