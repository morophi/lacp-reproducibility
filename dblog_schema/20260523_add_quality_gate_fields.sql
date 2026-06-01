-- Add Harness quality-gate and logprob-audit fields introduced after
-- qwen3-nothink OpenAI-compatible endpoint validation.
--
-- These columns preserve raw/clean response audit state and keep contaminated
-- generation outputs as quality outcomes while preventing them from becoming
-- causal trigger inputs.

USE lacp_db;

ALTER TABLE turn_node_logs
  ADD COLUMN IF NOT EXISTS run_mode VARCHAR(32) NULL AFTER condition_name,
  ADD COLUMN IF NOT EXISTS trigger_mode VARCHAR(128) NULL AFTER policy_hash,
  ADD COLUMN IF NOT EXISTS trigger_source_nodes JSON NULL AFTER trigger_reasons,
  ADD COLUMN IF NOT EXISTS previous_turn_used_for_trigger INT NULL AFTER threshold_snapshot,
  ADD COLUMN IF NOT EXISTS endpoint_mode VARCHAR(64) NULL AFTER thinking_disabled_requested,
  ADD COLUMN IF NOT EXISTS response_text_raw_hash CHAR(64) NULL AFTER endpoint_mode,
  ADD COLUMN IF NOT EXISTS thinking_tag_present TINYINT NULL AFTER response_text_raw_hash,
  ADD COLUMN IF NOT EXISTS empty_thinking_shell TINYINT NULL AFTER thinking_tag_present,
  ADD COLUMN IF NOT EXISTS thinking_content_present TINYINT NULL AFTER empty_thinking_shell,
  ADD COLUMN IF NOT EXISTS cleaning_applied TINYINT NULL AFTER thinking_content_present,
  ADD COLUMN IF NOT EXISTS cleaning_allowed TINYINT NULL AFTER cleaning_applied,
  ADD COLUMN IF NOT EXISTS failed_TR TINYINT NULL AFTER cleaning_allowed,
  ADD COLUMN IF NOT EXISTS removed_prefix_chars INT NULL AFTER failed_TR,
  ADD COLUMN IF NOT EXISTS raw_logprobs_len INT NULL AFTER removed_prefix_chars,
  ADD COLUMN IF NOT EXISTS clean_logprobs_len INT NULL AFTER raw_logprobs_len,
  ADD COLUMN IF NOT EXISTS excluded_token_positions JSON NULL AFTER clean_logprobs_len,
  ADD COLUMN IF NOT EXISTS quality_gate JSON NULL AFTER excluded_token_positions,
  ADD COLUMN IF NOT EXISTS generation_quality_ready TINYINT NULL AFTER quality_gate,
  ADD COLUMN IF NOT EXISTS analysis_eligible TINYINT NULL AFTER generation_quality_ready,
  ADD COLUMN IF NOT EXISTS exclude_from_causal_trigger TINYINT NULL AFTER analysis_eligible,
  ADD COLUMN IF NOT EXISTS usable_as_quality_outcome TINYINT NULL AFTER exclude_from_causal_trigger,
  ADD COLUMN IF NOT EXISTS metric_status JSON NULL AFTER usable_as_quality_outcome,
  ADD COLUMN IF NOT EXISTS metrics_json JSON NULL AFTER metric_status;

ALTER TABLE intervention_logs
  ADD COLUMN IF NOT EXISTS run_mode VARCHAR(32) NULL AFTER scenario_id,
  ADD COLUMN IF NOT EXISTS trigger_mode VARCHAR(128) NULL AFTER policy_hash,
  ADD COLUMN IF NOT EXISTS trigger_source_nodes JSON NULL AFTER trigger_reasons,
  ADD COLUMN IF NOT EXISTS previous_turn_used_for_trigger INT NULL AFTER threshold_snapshot;

ALTER TABLE metric_logs
  ADD COLUMN IF NOT EXISTS run_mode VARCHAR(32) NULL AFTER scenario_id,
  ADD COLUMN IF NOT EXISTS condition_name VARCHAR(64) NULL AFTER run_mode,
  ADD COLUMN IF NOT EXISTS lms_value DOUBLE NULL AFTER node,
  ADD COLUMN IF NOT EXISTS lms_token_count INT NULL AFTER lms_value,
  ADD COLUMN IF NOT EXISTS theta_entropy DOUBLE NULL AFTER lms_token_count,
  ADD COLUMN IF NOT EXISTS ma_epist DOUBLE NULL AFTER ma_assert,
  ADD COLUMN IF NOT EXISTS ma_hedge DOUBLE NULL AFTER ma_epist,
  ADD COLUMN IF NOT EXISTS sent_count INT NULL AFTER ma_hedge,
  ADD COLUMN IF NOT EXISTS metric_status JSON NULL AFTER metrics_json,
  ADD COLUMN IF NOT EXISTS quality_gate JSON NULL AFTER metric_status,
  ADD COLUMN IF NOT EXISTS generation_quality_ready TINYINT NULL AFTER quality_gate,
  ADD COLUMN IF NOT EXISTS analysis_eligible TINYINT NULL AFTER generation_quality_ready,
  ADD COLUMN IF NOT EXISTS exclude_from_causal_trigger TINYINT NULL AFTER analysis_eligible,
  ADD COLUMN IF NOT EXISTS usable_as_quality_outcome TINYINT NULL AFTER exclude_from_causal_trigger;

CREATE INDEX IF NOT EXISTS idx_turn_node_quality_ready
  ON turn_node_logs (generation_quality_ready, analysis_eligible);

CREATE INDEX IF NOT EXISTS idx_turn_node_causal_exclusion
  ON turn_node_logs (exclude_from_causal_trigger);

CREATE INDEX IF NOT EXISTS idx_metric_causal_exclusion
  ON metric_logs (exclude_from_causal_trigger);
