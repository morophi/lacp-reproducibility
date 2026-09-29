USE lacp_db;

-- Stage/run-mode distribution.
SELECT COALESCE(stage, run_mode) AS stage_or_mode,
       run_mode,
       condition_name,
       COUNT(*) AS run_count,
       MIN(created_at) AS earliest,
       MAX(created_at) AS latest
FROM experiment_runs
GROUP BY COALESCE(stage, run_mode), run_mode, condition_name
ORDER BY stage_or_mode, condition_name;

-- Node C should not receive RAG.
SELECT r.run_id, t.turn_no, t.node,
       i.rag_injected, g.retrieved_chunk_ids, g.returned_count
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
LEFT JOIN intervention_logs i ON i.turn_node_log_id = t.id
LEFT JOIN rag_retrieval_logs g ON g.turn_node_log_id = t.id
WHERE t.node = 'C'
  AND (i.rag_injected = 1 OR g.returned_count > 0 OR g.retrieved_chunk_ids IS NOT NULL);

-- Turns should normally have exactly A/B/C rows.
SELECT r.run_id, t.turn_no, COUNT(DISTINCT t.node) AS node_count
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
GROUP BY r.run_id, t.turn_no
HAVING node_count <> 3;

-- Metric completeness.
SELECT r.run_id, t.turn_no, t.node
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
LEFT JOIN metric_logs m ON m.turn_node_log_id = t.id
WHERE m.id IS NULL;

-- Payload/intervention flag disagreement.
SELECT r.run_id, t.turn_no, t.node,
       p.rag_injected AS p_rag, p.sc_policy_applied AS p_sc,
       i.rag_injected AS i_rag, i.sc_policy_applied AS i_sc
FROM turn_node_logs t
JOIN experiment_runs r ON r.id = t.experiment_run_id
LEFT JOIN payload_audit_logs p ON p.turn_node_log_id = t.id
LEFT JOIN intervention_logs i ON i.turn_node_log_id = t.id
WHERE p.rag_injected <> i.rag_injected
   OR p.sc_policy_applied <> i.sc_policy_applied;

-- Runtime-chain migration audit. NULLs are expected until Harness writes this
-- field or an operator performs a deliberate backfill.
SELECT COALESCE(runtime_chain, 'UNSET') AS runtime_chain,
       COALESCE(acceptance_status, 'UNSET') AS acceptance_status,
       COUNT(*) AS run_count
FROM experiment_runs
GROUP BY COALESCE(runtime_chain, 'UNSET'), COALESCE(acceptance_status, 'UNSET')
ORDER BY runtime_chain, acceptance_status;
