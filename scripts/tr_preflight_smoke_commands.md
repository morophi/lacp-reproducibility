# LACP TR Preflight Warm-Up Smoke Commands

Purpose: run only the first 1-2 immutable citizen turns through the real
Agent -> Harness -> A/B/C -> DB path. This warms the inference nodes and checks
Harness/DB column mapping without modifying the 30-turn scenario JSON.

## 0. Variables

```bash
export TR_RUN_ID="tr_preflight_$(date -u +%Y%m%dT%H%M%SZ)"
export SCENARIO="/home/morophi/agent/scenario/lacp_30turn_civil_complaint_v1.json"
export HARNESS_URL="http://10.1.1.110:9000"
export LACP_DB_PASSWORD="<set locally>"
```

## 1. Start Harness Server

Run on the harness node:

```bash
cd /home/morophi/harness
PYTHONPATH=/home/morophi/harness /home/morophi/harness_venv/bin/python harness_server.py \
  --config /home/morophi/harness/config/node_config.yaml \
  --sc-policy /home/morophi/harness/config/sc_policy.yaml \
  --theta /home/morophi/harness/config/theta_config.json
```

Health check from iMac or jump:

```bash
curl -s http://10.1.1.110:9000/turn
```

Expected for GET is not success; this only confirms the port responds. POST is
the real runtime path.

## 2. Send First 2 Turns From Agent/Jump

Run on the jump / agent node:

```bash
cd /home/morophi/agent
python3 run_scenario.py \
  --scenario "$SCENARIO" \
  --run-id "$TR_RUN_ID" \
  --condition run_b \
  --run-mode smoke \
  --harness-url "$HARNESS_URL" \
  --max-turns 2
```

Use `--run-mode smoke` for this preflight because it intentionally forces Run B
intervention and warms RAG/SC paths. Formal mode can be checked separately
after this succeeds.

## 3. Verify DB Rows On dblog

Run on dblog:

```bash
mysql -umorophi --password="${LACP_DB_PASSWORD}" lacp_db -e "
SELECT run_id, turn_no, node, endpoint_mode, rag_injected, sc_policy_applied,
       generation_quality_ready, analysis_eligible, exclude_from_causal_trigger,
       raw_logprobs_len, clean_logprobs_len, JSON_EXTRACT(quality_gate, '$.invalid_reason') AS invalid_reason
FROM v_turn_node_logs
WHERE run_id='${TR_RUN_ID}'
ORDER BY turn_no, node;

SELECT run_id, turn_no, node, lms_value, lms_delta, lms_token_count,
       ma_assert, ma_epist, ma_hedge, generation_quality_ready, analysis_eligible
FROM v_metric_logs
WHERE run_id='${TR_RUN_ID}'
ORDER BY turn_no, node;

SELECT run_id, turn_no, node, rag_injected, sc_policy_applied, trigger_mode,
       trigger_reasons, rag_chunk_ids
FROM v_intervention_logs
WHERE run_id='${TR_RUN_ID}'
ORDER BY turn_no, node;
"
```

Expected row count:

```text
turn_node_logs: 6 rows
metric_logs: 6 rows
intervention_logs: 6 rows
```

Expected invariants:

```text
Node A: sc_policy_applied=1 in smoke Run B when RAG chunks are returned
Node B: sc_policy_applied=0
Node C: rag_injected=0 and sc_policy_applied=0
raw_logprobs_len > clean_logprobs_len when empty think shell is stripped
lms_value is not NULL for OpenAI-compatible endpoint rows
```

## 4. Optional Formal First-Turn Check

Formal mode turn 1 should not trigger RAG/SC by default because there is no
previous completed metric source.

```bash
export FORMAL_RUN_ID="tr_preflight_formal_$(date -u +%Y%m%dT%H%M%SZ)"
cd /home/morophi/agent
python3 run_scenario.py \
  --scenario "$SCENARIO" \
  --run-id "$FORMAL_RUN_ID" \
  --condition run_b \
  --run-mode formal \
  --harness-url "$HARNESS_URL" \
  --max-turns 1
```

Expected:

```text
Node A/B/C all respond.
Node A/B/C rag_injected=0 for turn 1 unless bootstrap_first_turn=true.
Node C remains rag_injected=0 and sc_policy_applied=0.
LMS/logprob fields are populated through qwen3-nothink OpenAI-compatible endpoint.
```
