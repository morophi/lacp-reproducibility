#!/usr/bin/env bash
set -euo pipefail

cd /home/morophi/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before starting formal TR.}"

mkdir -p \
  /home/morophi/agent/validation_queries/formal_tr_logs \
  /home/morophi/agent/validation_queries/formal_thermal

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log="/home/morophi/agent/validation_queries/formal_tr_logs/formal_tr_${stamp}.log"
status="/home/morophi/agent/validation_queries/formal_tr_logs/formal_tr_${stamp}.status"

echo "log=${log}"
echo "status=${status}"

nohup bash -lc "
  cd /home/morophi/agent
  export LACP_DB_PASSWORD='${LACP_DB_PASSWORD}'
  python3 -u run_experiment_stage.py \
    --stage tr \
    --thermal-log \
    --thermal-output-dir /home/morophi/agent/validation_queries/formal_thermal \
    --thermal-cooldown-sec 30 \
    --node-local-thermal-log \
    --node-local-thermal-dir /home/morophi/lacp_node_thermal \
    --node-local-thermal-interval-sec 2 \
    --segment-every 5 \
    --segment-unload-runners \
    --segment-settle-sec 10 \
    --segment-cooldown-sec 30
  echo \$? > '${status}'
" > "${log}" 2>&1 &

echo "pid=$!"
