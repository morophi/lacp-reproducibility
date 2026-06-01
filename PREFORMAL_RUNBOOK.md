# Pre-Formal Readiness and Rehearsal Runbook

Purpose: keep formal dblog evidence clean while still proving that the runtime
envelope is ready before formal data generation.

## Boundary

- Official evidence DB remains reserved for formal observations.
- Level 0 readiness does not call Harness `/turn`.
- Level 1 stage rehearsal may call only a temporary DB-disabled Harness `/turn`.
- Pre-formal artifacts are not formal experimental evidence.
- Pre-formal artifacts are excluded from threshold estimation, effect-size
  estimation, statistical testing, and causal interpretation.
- Pre-formal artifacts are written under `validation_queries/preformal_md/`.
- Scratch JSONL copies are stored under `.node_sync_logs/` and ignored by Git.

## Level 0: DB-Free Readiness Gate

Run this before any DB-free stage rehearsal:

```powershell
python scripts\26_dbfree_readiness_gate_md.py --execute
```

This gate checks endpoint availability, actual first-turn payload feasibility,
formal logprobs availability, response completeness, and runner cleanup without
writing to dblog or invoking Harness `/turn`.

## Level 1: DB-Free Stage Rehearsal

Run these one stage at a time. Review the generated Markdown before proceeding
to the corresponding formal DB-writing run.

```powershell
python scripts\26_preformal_stage_md.py --stage tr
python scripts\26_preformal_stage_md.py --stage cr
python scripts\26_preformal_stage_md.py --stage cr2
python scripts\26_preformal_stage_md.py --stage run_b
python scripts\26_preformal_stage_md.py --stage cf_a
python scripts\26_preformal_stage_md.py --stage cf_b
python scripts\26_preformal_stage_md.py --stage cf_c
python scripts\26_preformal_stage_md.py --stage cf_d
python scripts\26_preformal_stage_md.py --stage cf_e
python scripts\26_preformal_stage_md.py --stage cf_f
```

CR2 pre-formal is a gate for later pre-formal stages. It writes:

- `validation_queries/preformal_md/preformal_theta_config.json`
- `validation_queries/preformal_md/preformal_cr2_calibration.json`

Pre-formal `run_b` and `cf_*` stages automatically upload this pre-formal theta
file into the temporary DB-disabled Harness. If the pre-formal theta file is
missing, those stages are blocked.

The pre-formal theta file is a stage-dependency rehearsal artifact only. It is
not an official threshold estimate.

Default pre-formal scope is intentionally small:

- `tr`: 1 repetition, 2 turns
- all other stages: 1 repetition, 1 turn

Use `--repetitions` and `--max-turns` only when a larger rehearsal is required.

## Pass Criteria

- Level 0 readiness Markdown status is `PASS`.
- Temporary Harness route returns HTTP 405 for `GET /turn`.
- Stage runner completes against the DB-disabled Harness.
- JSONL fallback rows are fetched and summarized.
- CR2 produces a pre-formal theta config from JSONL evidence.
- Run B/CF use the CR2-derived pre-formal theta config.
- dblog row count for generated pre-formal run ids is zero.
- Generated Markdown status is `PASS`.
