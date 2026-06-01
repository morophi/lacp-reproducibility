# Pre-Formal MD Evidence Runbook

Purpose: validate each formal stage without writing rehearsal rows into dblog.
The temporary Harness uses DB-disabled logging and records the audit result as a
Git-trackable Markdown artifact.

## Boundary

- Official evidence DB remains reserved for formal observations.
- Pre-formal rehearsal writes no dblog rows.
- Rehearsal outcomes are written under `validation_queries/preformal_md/`.
- Scratch JSONL copies are stored under `.node_sync_logs/` and ignored by Git.

## Per-Stage Commands

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

Default pre-formal scope is intentionally small:

- `tr`: 1 repetition, 2 turns
- all other stages: 1 repetition, 1 turn

Use `--repetitions` and `--max-turns` only when a larger rehearsal is required.

## Pass Criteria

- Temporary Harness route returns HTTP 405 for `GET /turn`.
- Stage runner completes against the DB-disabled Harness.
- JSONL fallback rows are fetched and summarized.
- CR2 produces a pre-formal theta config from JSONL evidence.
- Run B/CF use the CR2-derived pre-formal theta config.
- dblog row count for generated pre-formal run ids is zero.
- Generated Markdown status is `PASS`.
