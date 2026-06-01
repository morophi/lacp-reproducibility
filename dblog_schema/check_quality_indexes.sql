USE lacp_db;

SHOW INDEX FROM turn_node_logs
  WHERE Key_name IN ('idx_turn_node_quality_ready', 'idx_turn_node_causal_exclusion');

SHOW INDEX FROM metric_logs
  WHERE Key_name IN ('idx_metric_causal_exclusion');
