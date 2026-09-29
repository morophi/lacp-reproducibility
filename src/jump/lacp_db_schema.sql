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
  run_id VARCHAR(128) NOT NULL,
  scenario_id VARCHAR(256) NOT NULL,
  scenario_hash CHAR(64) NULL,
  condition_name VARCHAR(64) NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
  source_file TEXT NULL,
  utterance_hash CHAR(64) NOT NULL,
  response_text MEDIUMTEXT NULL,
  response_hash CHAR(64) NULL,
  elapsed_ms DOUBLE NULL,
  rag_injected TINYINT NOT NULL DEFAULT 0,
  sc_policy_applied TINYINT NOT NULL DEFAULT 0,
  sc_policy_id VARCHAR(128) NULL,
  policy_hash CHAR(64) NULL,
  trigger_reasons JSON NULL,
  threshold_snapshot JSON NULL,
  rag_chunk_ids JSON NULL,
  prompt_hash CHAR(64) NOT NULL,
  model_name VARCHAR(128) NULL,
  model_digest VARCHAR(256) NULL,
  temperature DOUBLE NULL,
  seed INT NULL,
  thinking_disabled_requested TINYINT NOT NULL DEFAULT 1,
  raw_response_keys JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_turn_node (run_id, turn_no, node),
  INDEX idx_turn_node_run_turn (run_id, turn_no),
  INDEX idx_turn_node_node (node),
  INDEX idx_turn_node_prompt_hash (prompt_hash),
  CONSTRAINT chk_turn_node_node CHECK (node IN ('A', 'B', 'C')),
  CONSTRAINT chk_turn_node_c_no_intervention CHECK (
    node <> 'C' OR (rag_injected = 0 AND sc_policy_applied = 0)
  ),
  CONSTRAINT chk_turn_node_b_no_sc CHECK (
    node <> 'B' OR sc_policy_applied = 0
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS intervention_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  scenario_id VARCHAR(256) NOT NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
  rag_injected TINYINT NOT NULL DEFAULT 0,
  sc_policy_applied TINYINT NOT NULL DEFAULT 0,
  sc_policy_id VARCHAR(128) NULL,
  policy_hash CHAR(64) NULL,
  trigger_reasons JSON NULL,
  threshold_snapshot JSON NULL,
  rag_chunk_ids JSON NULL,
  prompt_hash CHAR(64) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_intervention_turn_node (run_id, turn_no, node),
  INDEX idx_intervention_run_turn (run_id, turn_no),
  INDEX idx_intervention_policy_hash (policy_hash),
  CONSTRAINT chk_intervention_node CHECK (node IN ('A', 'B', 'C')),
  CONSTRAINT chk_intervention_c_no_intervention CHECK (
    node <> 'C' OR (rag_injected = 0 AND sc_policy_applied = 0)
  ),
  CONSTRAINT chk_intervention_b_no_sc CHECK (
    node <> 'B' OR sc_policy_applied = 0
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS metric_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  scenario_id VARCHAR(256) NOT NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
  lms_delta DOUBLE NULL,
  cds DOUBLE NULL,
  ma_assert DOUBLE NULL,
  srr DOUBLE NULL,
  sci DOUBLE NULL,
  metrics_json JSON NULL,
  metric_pipeline_version VARCHAR(128) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_metric_turn_node (run_id, turn_no, node),
  INDEX idx_metric_run_turn (run_id, turn_no),
  INDEX idx_metric_node (node),
  CONSTRAINT chk_metric_node CHECK (node IN ('A', 'B', 'C'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rag_retrieval_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  scenario_id VARCHAR(256) NOT NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
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
  INDEX idx_rag_run_turn (run_id, turn_no),
  INDEX idx_rag_node (node),
  CONSTRAINT chk_rag_node CHECK (node IN ('A', 'B'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payload_audit_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id VARCHAR(128) NOT NULL,
  scenario_id VARCHAR(256) NOT NULL,
  turn_no INT NOT NULL,
  node VARCHAR(8) NOT NULL,
  prompt_hash CHAR(64) NOT NULL,
  payload_hash CHAR(64) NULL,
  message_count INT NULL,
  prompt_chars INT NULL,
  rag_injected TINYINT NOT NULL DEFAULT 0,
  sc_policy_applied TINYINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_payload_turn_node (run_id, turn_no, node),
  INDEX idx_payload_prompt_hash (prompt_hash),
  CONSTRAINT chk_payload_node CHECK (node IN ('A', 'B', 'C')),
  CONSTRAINT chk_payload_c_no_intervention CHECK (
    node <> 'C' OR (rag_injected = 0 AND sc_policy_applied = 0)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
