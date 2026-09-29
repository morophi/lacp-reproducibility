-- Formal Run B retry #1/#2 reject marker.
-- Date: 2026-06-24 KST
-- Purpose: preserve rows while marking retry data generated before harness
-- service reload as rejected evidence.
-- No purge, delete, truncate, or auto-increment reset is performed here.

USE lacp_db_final;

SET @reject_code = 'RUN_B_RETRY_REJECT_20260624_STALE_HARNESS_PROCESS';
SET @reject_reason = CONCAT(
  @reject_code,
  ': run_b_retry_#1 and run_b_retry_#2 were generated while the deployed ',
  'harness source/config contained the abs trigger transform, but the running ',
  'lacp-harness.service process had not yet been restarted and still served ',
  'the old directional/MA trigger logic. run_b_retry_#1 was incorrectly marked ',
  'accepted with under-triggered SC evidence; run_b_retry_#2 failed after ',
  'harness restart during the batch. Rows are retained as audit evidence and ',
  'excluded from accepted Run B analysis.'
);

SELECT
  'before_update' AS phase,
  run_id,
  acceptance_status,
  failure_reason
FROM experiment_runs
WHERE run_id IN (
  'run_b_retry_#1_20260624T160338KST',
  'run_b_retry_#2_20260624T162351KST'
)
ORDER BY run_id;

UPDATE experiment_runs
SET
  acceptance_status = 'rejected',
  failure_reason = @reject_reason,
  completed_at = CURRENT_TIMESTAMP()
WHERE run_id IN (
  'run_b_retry_#1_20260624T160338KST',
  'run_b_retry_#2_20260624T162351KST'
);

SELECT ROW_COUNT() AS updated_experiment_runs;

SELECT
  'after_update' AS phase,
  run_id,
  acceptance_status,
  failure_reason
FROM experiment_runs
WHERE run_id IN (
  'run_b_retry_#1_20260624T160338KST',
  'run_b_retry_#2_20260624T162351KST'
)
ORDER BY run_id;
