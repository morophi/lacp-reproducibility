-- LACP dblog auditability migration.
-- Purpose: make stage/runtime chain/corpus/status and trigger eligibility
-- queryable without relying on run_id parsing or JSON-only inspection.
--
-- Safe application intent:
-- - Idempotent on MariaDB versions supporting ADD COLUMN IF NOT EXISTS.
-- - Adds nullable columns first so existing Harness writers are not broken.
-- - Backfills stage from run_mode only where stage is still NULL.
-- - Does not mark historical rows as accepted or failed.

USE lacp_db;

ALTER TABLE experiment_runs
  ADD COLUMN IF NOT EXISTS stage VARCHAR(32) NULL AFTER condition_name,
  ADD COLUMN IF NOT EXISTS corpus_hash CHAR(64) NULL AFTER run_mode,
  ADD COLUMN IF NOT EXISTS corpus_version VARCHAR(128) NULL AFTER corpus_hash,
  ADD COLUMN IF NOT EXISTS collection_name VARCHAR(256) NULL AFTER corpus_version,
  ADD COLUMN IF NOT EXISTS runtime_chain VARCHAR(64) NULL AFTER collection_name,
  ADD COLUMN IF NOT EXISTS acceptance_status VARCHAR(32) NULL AFTER runtime_chain,
  ADD COLUMN IF NOT EXISTS failure_reason TEXT NULL AFTER acceptance_status,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMP NULL AFTER theta_locked,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP NULL AFTER started_at,
  ADD INDEX IF NOT EXISTS idx_experiment_runs_stage (stage),
  ADD INDEX IF NOT EXISTS idx_experiment_runs_runtime_chain (runtime_chain),
  ADD INDEX IF NOT EXISTS idx_experiment_runs_acceptance_status (acceptance_status);

UPDATE experiment_runs
SET stage = run_mode
WHERE stage IS NULL
  AND run_mode IS NOT NULL;

ALTER TABLE intervention_logs
  ADD COLUMN IF NOT EXISTS trigger_eligible TINYINT NULL AFTER trigger_reasons,
  ADD COLUMN IF NOT EXISTS sc_triggered TINYINT NULL AFTER previous_turn_used_for_trigger,
  ADD COLUMN IF NOT EXISTS sc_trigger_reason VARCHAR(512) NULL AFTER sc_triggered,
  ADD COLUMN IF NOT EXISTS sc_trigger_rule_id VARCHAR(128) NULL AFTER sc_trigger_reason,
  ADD COLUMN IF NOT EXISTS sc_policy_anchor_chunk_ids JSON NULL AFTER sc_trigger_rule_id,
  ADD COLUMN IF NOT EXISTS sc_evidence_sufficiency VARCHAR(64) NULL AFTER sc_policy_anchor_chunk_ids,
  ADD COLUMN IF NOT EXISTS sc_response_mode VARCHAR(64) NULL AFTER sc_evidence_sufficiency,
  ADD COLUMN IF NOT EXISTS sc_verification_required JSON NULL AFTER sc_response_mode,
  ADD COLUMN IF NOT EXISTS sc_responsibility_boundary_applied TINYINT NULL AFTER sc_verification_required,
  ADD COLUMN IF NOT EXISTS sc_decision_payload JSON NULL AFTER sc_responsibility_boundary_applied;

ALTER TABLE rag_retrieval_logs
  ADD COLUMN IF NOT EXISTS sc_policy_applied TINYINT NOT NULL DEFAULT 0 AFTER turn_node_log_id,
  ADD COLUMN IF NOT EXISTS retrieved_chunk_ids_hash CHAR(64) NULL AFTER retrieved_chunk_ids;

ALTER TABLE payload_audit_logs
  ADD COLUMN IF NOT EXISTS final_prompt_chars INT NULL AFTER prompt_chars,
  ADD COLUMN IF NOT EXISTS rag_context_chars INT NULL AFTER final_prompt_chars,
  ADD COLUMN IF NOT EXISTS sc_block_chars INT NULL AFTER rag_context_chars,
  ADD COLUMN IF NOT EXISTS sc_block_hash CHAR(64) NULL AFTER sc_block_chars,
  ADD COLUMN IF NOT EXISTS prompt_contains_sc_marker TINYINT NULL AFTER sc_block_hash,
  ADD COLUMN IF NOT EXISTS retrieved_chunk_ids JSON NULL AFTER prompt_contains_sc_marker,
  ADD COLUMN IF NOT EXISTS retrieved_chunk_ids_hash CHAR(64) NULL AFTER retrieved_chunk_ids,
  ADD COLUMN IF NOT EXISTS collection_name VARCHAR(256) NULL AFTER retrieved_chunk_ids_hash,
  ADD COLUMN IF NOT EXISTS corpus_version VARCHAR(128) NULL AFTER collection_name,
  ADD COLUMN IF NOT EXISTS history_window_turns_configured INT NULL AFTER corpus_version,
  ADD COLUMN IF NOT EXISTS history_turns_used INT NULL AFTER history_window_turns_configured;

-- Recreate views from the canonical schema after applying this migration:
--   mariadb -u <user> < /home/lacp/lacp_db_schema.sql
