USE lacp_db;
SELECT COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema = 'lacp_db'
  AND table_name IN (
    'experiment_runs',
    'turn_node_logs',
    'intervention_logs',
    'metric_logs',
    'rag_retrieval_logs',
    'payload_audit_logs'
  );
SHOW TABLES;
SHOW COLUMNS FROM turn_node_logs;
SHOW COLUMNS FROM intervention_logs;
SHOW COLUMNS FROM metric_logs;
SHOW COLUMNS FROM experiment_runs;
SHOW COLUMNS FROM rag_retrieval_logs;
SHOW COLUMNS FROM payload_audit_logs;

SELECT
  TABLE_NAME,
  SUM(COLUMN_NAME = 'quality_gate') AS has_quality_gate,
  SUM(COLUMN_NAME = 'generation_quality_ready') AS has_generation_quality_ready,
  SUM(COLUMN_NAME = 'analysis_eligible') AS has_analysis_eligible,
  SUM(COLUMN_NAME = 'exclude_from_causal_trigger') AS has_exclude_from_causal_trigger,
  SUM(COLUMN_NAME = 'usable_as_quality_outcome') AS has_usable_as_quality_outcome
FROM information_schema.columns
WHERE table_schema = 'lacp_db'
  AND TABLE_NAME IN ('turn_node_logs', 'metric_logs')
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;

SELECT
  TABLE_NAME,
  SUM(COLUMN_NAME = 'stage') AS has_stage,
  SUM(COLUMN_NAME = 'corpus_hash') AS has_corpus_hash,
  SUM(COLUMN_NAME = 'corpus_version') AS has_corpus_version,
  SUM(COLUMN_NAME = 'collection_name') AS has_collection_name,
  SUM(COLUMN_NAME = 'runtime_chain') AS has_runtime_chain,
  SUM(COLUMN_NAME = 'acceptance_status') AS has_acceptance_status,
  SUM(COLUMN_NAME = 'failure_reason') AS has_failure_reason
FROM information_schema.columns
WHERE table_schema = 'lacp_db'
  AND TABLE_NAME = 'experiment_runs'
GROUP BY TABLE_NAME;

SELECT
  TABLE_NAME,
  SUM(COLUMN_NAME = 'trigger_eligible') AS has_trigger_eligible,
  SUM(COLUMN_NAME = 'sc_triggered') AS has_sc_triggered,
  SUM(COLUMN_NAME = 'sc_decision_payload') AS has_sc_decision_payload
FROM information_schema.columns
WHERE table_schema = 'lacp_db'
  AND TABLE_NAME = 'intervention_logs'
GROUP BY TABLE_NAME;

SELECT
  TABLE_NAME,
  SUM(COLUMN_NAME = 'retrieved_chunk_ids_hash') AS has_retrieved_chunk_ids_hash,
  SUM(COLUMN_NAME = 'collection_name') AS has_collection_name,
  SUM(COLUMN_NAME = 'corpus_version') AS has_corpus_version
FROM information_schema.columns
WHERE table_schema = 'lacp_db'
  AND TABLE_NAME IN ('rag_retrieval_logs', 'payload_audit_logs')
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;
