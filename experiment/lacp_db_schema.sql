-- LACP experiment DB schema for Harness runtime logging.
-- Purpose: persist run metadata, per-node turn responses, intervention flags,
-- prompt/policy hashes, RAG chunk ids, and metric outputs produced by Harness.
-- Scenario Agent does not write these tables; Harness is the sole runtime writer.

CREATE DATABASE IF NOT EXISTS lacp_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE lacp_db;

CREATE TABLE IF NOT EXISTS experiment_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL UNIQUE,
  scenario_id VARCHAR(256) NOT NULL,
  scenario_hash CHAR(64) NULL,
  condition_name VARCHAR(64) NULL,
  run_mode VARCHAR(32) NULL,
  source_file TEXT NULL,
  harness_version VARCHAR(128) NULL,
  node_config_hash CHAR(64) NULL,
  sc_policy_id VARCHAR(128) NULL,
  policy_hash CHAR(64) NULL,
  theta_source VARCHAR(128) NULL,
  theta_locked TINYINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_experiment_runs_scenario (scenario_id),
  INDEX idx_experiment_runs_condition (condition_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS turn_node_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  experiment_run_id BIGINT NOT NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
  utterance_hash CHAR(64) NOT NULL,
  response_text MEDIUMTEXT NULL,
  response_hash CHAR(64) NULL,
  elapsed_ms DOUBLE NULL,
  model_name VARCHAR(128) NULL,
  model_digest VARCHAR(256) NULL,
  temperature DOUBLE NULL,
  seed INT NULL,
  thinking_disabled_requested TINYINT NOT NULL DEFAULT 1,
  endpoint_mode VARCHAR(64) NULL,
  response_text_raw_hash CHAR(64) NULL,
  thinking_tag_present TINYINT NULL,
  empty_thinking_shell TINYINT NULL,
  thinking_content_present TINYINT NULL,
  cleaning_applied TINYINT NULL,
  cleaning_allowed TINYINT NULL,
  failed_TR TINYINT NULL,
  removed_prefix_chars INT NULL,
  raw_logprobs_len INT NULL,
  clean_logprobs_len INT NULL,
  excluded_token_positions JSON NULL,
  quality_gate JSON NULL,
  generation_quality_ready TINYINT NULL,
  analysis_eligible TINYINT NULL,
  exclude_from_causal_trigger TINYINT NULL,
  -- History eligibility is separate from analysis and trigger eligibility:
  -- a row can be excluded from statistical analysis while still remaining a
  -- valid conversational context, and hard failures can be stored without
  -- being fed into the next turn.
  history_eligible TINYINT NULL,
  history_exclusion_reason VARCHAR(512) NULL,
  usable_as_quality_outcome TINYINT NULL,
  metric_status JSON NULL,
  -- Metric-specific trigger eligibility records cases where, for example,
  -- missing logprobs disables LMS triggers but leaves MA/CDS policy-eligible.
  metric_trigger_eligibility JSON NULL,
  metrics_json JSON NULL,
  raw_response_keys JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_turn_node (experiment_run_id, turn_no, node),
  INDEX idx_turn_node_run_turn (experiment_run_id, turn_no),
  INDEX idx_turn_node_node (node),
  CONSTRAINT fk_turn_node_experiment_run
    FOREIGN KEY (experiment_run_id) REFERENCES experiment_runs(id)
    ON DELETE CASCADE,
  CONSTRAINT chk_turn_node_node CHECK (node IN ('A', 'B', 'C'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS intervention_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  turn_node_log_id BIGINT NOT NULL,
  rag_injected TINYINT NOT NULL DEFAULT 0,
  sc_policy_applied TINYINT NOT NULL DEFAULT 0,
  sc_policy_id VARCHAR(128) NULL,
  policy_hash CHAR(64) NULL,
  trigger_mode VARCHAR(128) NULL,
  trigger_reasons JSON NULL,
  trigger_source_nodes JSON NULL,
  threshold_snapshot JSON NULL,
  previous_turn_used_for_trigger INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_intervention_turn_node (turn_node_log_id),
  INDEX idx_intervention_policy_hash (policy_hash),
  CONSTRAINT fk_intervention_turn_node
    FOREIGN KEY (turn_node_log_id) REFERENCES turn_node_logs(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS metric_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  turn_node_log_id BIGINT NOT NULL,
  lms_value DOUBLE NULL,
  lms_token_count INT NULL,
  theta_entropy DOUBLE NULL,
  lms_delta DOUBLE NULL,
  cds DOUBLE NULL,
  ma_assert DOUBLE NULL,
  ma_epist DOUBLE NULL,
  ma_hedge DOUBLE NULL,
  sent_count INT NULL,
  srr DOUBLE NULL,
  sci DOUBLE NULL,
  metrics_json JSON NULL,
  metric_status JSON NULL,
  quality_gate JSON NULL,
  generation_quality_ready TINYINT NULL,
  analysis_eligible TINYINT NULL,
  exclude_from_causal_trigger TINYINT NULL,
  -- Stored with metric logs so trigger audits can distinguish LMS availability
  -- from MA/CDS availability without reopening the larger metrics_json blob.
  metric_trigger_eligibility JSON NULL,
  usable_as_quality_outcome TINYINT NULL,
  metric_pipeline_version VARCHAR(128) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_metric_turn_node (turn_node_log_id),
  CONSTRAINT fk_metric_turn_node
    FOREIGN KEY (turn_node_log_id) REFERENCES turn_node_logs(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_retrieval_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  turn_node_log_id BIGINT NOT NULL,
  query_hash CHAR(64) NOT NULL,
  collection_name VARCHAR(256) NULL,
  top_k INT NULL,
  returned_count INT NULL,
  rag_context_chars INT NULL,
  retrieval_method VARCHAR(64) NULL,
  table_exposure TINYINT NULL,
  retrieved_chunk_ids JSON NULL,
  chunk_lengths JSON NULL,
  block_type_distribution JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rag_turn_node (turn_node_log_id),
  INDEX idx_rag_query_hash (query_hash),
  CONSTRAINT fk_rag_turn_node
    FOREIGN KEY (turn_node_log_id) REFERENCES turn_node_logs(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payload_audit_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  turn_node_log_id BIGINT NOT NULL,
  prompt_hash CHAR(64) NOT NULL,
  payload_hash CHAR(64) NULL,
  message_count INT NULL,
  prompt_chars INT NULL,
  rag_injected TINYINT NOT NULL DEFAULT 0,
  sc_policy_applied TINYINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_payload_turn_node (turn_node_log_id),
  INDEX idx_payload_prompt_hash (prompt_hash),
  CONSTRAINT fk_payload_turn_node
    FOREIGN KEY (turn_node_log_id) REFERENCES turn_node_logs(id)
    ON DELETE CASCADE,
  CONSTRAINT chk_payload_flags_boolean CHECK (
    rag_injected IN (0, 1) AND sc_policy_applied IN (0, 1)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE VIEW v_turn_node_logs AS
SELECT
  r.run_id,
  r.scenario_id,
  r.scenario_hash,
  r.condition_name,
  r.run_mode,
  r.source_file,
  p.rag_injected,
  p.sc_policy_applied,
  p.prompt_hash,
  p.payload_hash,
  p.message_count,
  p.prompt_chars,
  i.sc_policy_id,
  i.policy_hash,
  i.trigger_mode,
  i.trigger_reasons,
  i.trigger_source_nodes,
  i.threshold_snapshot,
  i.previous_turn_used_for_trigger,
  g.retrieved_chunk_ids AS rag_chunk_ids,
  g.rag_context_chars,
  g.collection_name,
  g.top_k,
  g.returned_count,
  t.*
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
LEFT JOIN payload_audit_logs p ON p.turn_node_log_id = t.id
LEFT JOIN intervention_logs i ON i.turn_node_log_id = t.id
LEFT JOIN rag_retrieval_logs g ON g.turn_node_log_id = t.id;

CREATE OR REPLACE VIEW v_intervention_logs AS
SELECT
  r.run_id,
  r.scenario_id,
  r.condition_name,
  r.run_mode,
  t.turn_no,
  t.node,
  p.prompt_hash,
  g.retrieved_chunk_ids AS rag_chunk_ids,
  g.rag_context_chars,
  i.*
FROM intervention_logs i
JOIN turn_node_logs t ON t.id = i.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id
LEFT JOIN payload_audit_logs p ON p.turn_node_log_id = t.id
LEFT JOIN rag_retrieval_logs g ON g.turn_node_log_id = t.id;

CREATE OR REPLACE VIEW v_metric_logs AS
SELECT
  r.run_id,
  r.scenario_id,
  r.condition_name,
  r.run_mode,
  t.turn_no,
  t.node,
  m.*
FROM metric_logs m
JOIN turn_node_logs t ON t.id = m.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id;

CREATE OR REPLACE VIEW v_rag_retrieval_logs AS
SELECT
  r.run_id,
  r.scenario_id,
  r.condition_name,
  r.run_mode,
  t.turn_no,
  t.node,
  g.*
FROM rag_retrieval_logs g
JOIN turn_node_logs t ON t.id = g.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id;

CREATE OR REPLACE VIEW v_payload_audit_logs AS
SELECT
  r.run_id,
  r.scenario_id,
  r.condition_name,
  r.run_mode,
  t.turn_no,
  t.node,
  p.*
FROM payload_audit_logs p
JOIN turn_node_logs t ON t.id = p.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id;
