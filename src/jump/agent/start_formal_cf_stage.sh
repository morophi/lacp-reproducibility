#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before starting formal counterfactual stage.}"

export LACP_DB_NAME="${LACP_DB_NAME:-lacp_db_final}"
if [ "$LACP_DB_NAME" != "lacp_db_final" ]; then
  echo "LACP_DB_NAME must be lacp_db_final, got $LACP_DB_NAME" >&2
  exit 2
fi
export LACP_AGENT_PYTHON="${LACP_AGENT_PYTHON:-/home/lacp/proxy-jump/bin/python}"
if [ ! -x "$LACP_AGENT_PYTHON" ]; then
  echo "LACP_AGENT_PYTHON is not executable: $LACP_AGENT_PYTHON" >&2
  exit 2
fi
"$LACP_AGENT_PYTHON" -c 'import pymysql' >/dev/null

stage="${1:?Usage: start_formal_cf_stage.sh cf_a|cf_b|cf_c|cf_d|cf_e|cf_f}"
case "${stage}" in
  cf_a|cf_b|cf_c|cf_d|cf_e|cf_f) ;;
  *)
    echo "invalid counterfactual stage: ${stage}" >&2
    exit 2
    ;;
esac

"$LACP_AGENT_PYTHON" /home/lacp/agent/check_formal_cf_design_readiness.py \
  --stage "${stage}" \
  --node-config-path /home/lacp/harness/config/node_config.yaml \
  --scenario /home/lacp/agent/scenario/lacp_cf_scenario_v1.json \
  --run-experiment-stage /home/lacp/agent/run_experiment_stage.py

mkdir -p \
  /home/lacp/agent/validation_queries/formal_cf_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(ssh -n -o BatchMode=yes -o ConnectTimeout=5 dblog date +%Y%m%dT%H%M%SKST)"
log="/home/lacp/agent/validation_queries/formal_cf_logs/formal_${stage}_${stamp}.log"
status="/home/lacp/agent/validation_queries/formal_cf_logs/formal_${stage}_${stamp}.status"
post_status="/home/lacp/agent/validation_queries/formal_cf_logs/formal_${stage}_${stamp}.post_validation.log"

echo "stage=${stage}"
echo "log=${log}"
echo "status=${status}"
echo "post_validation=${post_status}"

nohup bash -lc "
  cd /home/lacp/agent
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  export LACP_DB_NAME=\"\${LACP_DB_NAME}\"
  export LACP_AGENT_PYTHON=\"\${LACP_AGENT_PYTHON}\"
  \"\${LACP_AGENT_PYTHON}\" -u run_experiment_stage.py \
    --stage ${stage} \
    --harness-url http://harness:9000 \
    --harness-host harness \
    --theta-path /home/lacp/harness/config/theta_config.json \
    --node-config-path /home/lacp/harness/config/node_config.yaml \
    --model-name qwen3-nothink \
    --thermal-log \
    --thermal-output-dir /home/lacp/agent/validation_queries/formal_thermal \
    --thermal-cooldown-sec 60 \
    --node-local-thermal-log \
    --node-local-thermal-dir /home/lacp/lacp_node_thermal \
    --node-local-thermal-interval-sec 2 \
    --pre-run-unload-runners \
    --pre-run-settle-sec 20 \
    --pre-run-readiness-probe \
    --pre-run-readiness-timeout-sec 90 \
    --pre-run-readiness-max-tokens 64 \
    --pre-run-post-readiness-unload \
    --pre-run-post-readiness-settle-sec 10 \
    --segment-every 5 \
    --segment-unload-runners \
    --segment-settle-sec 10 \
    --segment-cooldown-sec 60
  rc=\$?
  echo \$rc > '${status}.stage'
  echo \$rc > '${status}'
  if [ \"\$rc\" -eq 0 ]; then
    /home/lacp/agent/run_formal_post_validation_from_log.sh \
      ${stage} '${log}' /home/lacp/agent/validation_queries/formal_post_validation \
      > '${post_status}' 2>&1
    post_rc=\$?
    echo \$post_rc > '${status}.post'
    if [ \"\$post_rc\" -ne 0 ]; then
      echo \$post_rc > '${status}'
      /home/lacp/agent/schedule_runtime_log_sync.sh formal_${stage}_${stamp}_post_rc\${post_rc} || true
      exit \$post_rc
    fi
  fi
  echo \$rc > '${status}'
  /home/lacp/agent/schedule_runtime_log_sync.sh formal_${stage}_${stamp}_rc\${rc} || true
  exit \$rc
" > "${log}" 2>&1 &

echo "pid=$!"
