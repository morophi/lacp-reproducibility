USE lacp_db;

SELECT 'turn_node_logs' AS table_name, run_id, turn_no, node,
       generation_quality_ready, analysis_eligible, exclude_from_causal_trigger,
       JSON_EXTRACT(quality_gate, '$.usable_as_quality_outcome') AS usable_as_quality_outcome
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
WHERE run_id LIKE 'db_writer_smoke_%'
ORDER BY t.id DESC
LIMIT 3;

SELECT 'intervention_logs' AS table_name, run_id, turn_no, node,
       rag_injected, sc_policy_applied, trigger_mode
FROM intervention_logs i
JOIN turn_node_logs t ON t.id = i.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id
WHERE run_id LIKE 'db_writer_smoke_%'
ORDER BY i.id DESC
LIMIT 3;

SELECT 'metric_logs' AS table_name, run_id, turn_no, node,
       lms_value, lms_token_count, ma_assert,
       generation_quality_ready, analysis_eligible, exclude_from_causal_trigger
FROM metric_logs m
JOIN turn_node_logs t ON t.id = m.turn_node_log_id
JOIN experiment_runs r ON r.id = t.experiment_run_id
WHERE run_id LIKE 'db_writer_smoke_%'
ORDER BY m.id DESC
LIMIT 3;
