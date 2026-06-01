USE lacp_db;

SET @run_id = 'tr_preflight_lms_formal_20260523T113931Z';

SELECT COUNT(*) AS turn_node_rows
FROM v_turn_node_logs
WHERE run_id = @run_id;

SELECT run_id, turn_no, node, endpoint_mode, rag_injected, sc_policy_applied,
       generation_quality_ready, analysis_eligible, exclude_from_causal_trigger,
       thinking_tag_present, empty_thinking_shell, thinking_content_present,
       cleaning_applied, failed_TR, raw_logprobs_len, clean_logprobs_len,
       JSON_EXTRACT(quality_gate, '$.invalid_reason') AS invalid_reason
FROM v_turn_node_logs
WHERE run_id = @run_id
ORDER BY turn_no, node;

SELECT COUNT(*) AS metric_rows
FROM v_metric_logs
WHERE run_id = @run_id;

SELECT run_id, turn_no, node, lms_value, lms_delta, lms_token_count,
       ma_assert, ma_epist, ma_hedge, generation_quality_ready, analysis_eligible,
       JSON_EXTRACT(metric_status, '$.warnings') AS warnings
FROM v_metric_logs
WHERE run_id = @run_id
ORDER BY turn_no, node;

SELECT COUNT(*) AS intervention_rows
FROM v_intervention_logs
WHERE run_id = @run_id;

SELECT run_id, turn_no, node, rag_injected, sc_policy_applied, trigger_mode,
       trigger_reasons, rag_chunk_ids
FROM v_intervention_logs
WHERE run_id = @run_id
ORDER BY turn_no, node;
