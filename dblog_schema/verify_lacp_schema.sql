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
