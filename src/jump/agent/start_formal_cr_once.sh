#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before starting formal CR.}"

if [ "${ALLOW_SOFT_CR_LAUNCHER:-}" != "1" ]; then
  cat >&2 <<'EOF'
start_formal_cr_once.sh is the legacy soft-readiness CR launcher.
For the official FlashAttention-off + cooldown60 formal CR chain, use:
  /home/lacp/agent/start_formal_cr1_once.sh

To intentionally run this soft-gate launcher, set:
  ALLOW_SOFT_CR_LAUNCHER=1
EOF
  exit 2
fi
export LACP_AGENT_PYTHON="${LACP_AGENT_PYTHON:-/home/lacp/proxy-jump/bin/python}"
if [ ! -x "$LACP_AGENT_PYTHON" ]; then
  echo "LACP_AGENT_PYTHON is not executable: $LACP_AGENT_PYTHON" >&2
  exit 2
fi
"$LACP_AGENT_PYTHON" -c 'import pymysql' >/dev/null

mkdir -p \
  /home/lacp/agent/validation_queries/formal_cr_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(ssh -n -o BatchMode=yes -o ConnectTimeout=5 dblog date +%Y%m%dT%H%M%SKST)"
log="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr_${stamp}.log"
status="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr_${stamp}.status"

echo "log=${log}"
echo "status=${status}"

nohup bash -lc "
  cd /home/lacp/agent
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  export LACP_AGENT_PYTHON=\"\${LACP_AGENT_PYTHON}\"
  \"\${LACP_AGENT_PYTHON}\" -u run_experiment_stage.py \
    --stage cr \
    --repetitions 1 \
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
    --segment-cooldown-sec 60 \
    --no-failed-db-purge
  rc=\$?
  echo \$rc > '${status}'
  /home/lacp/agent/schedule_runtime_log_sync.sh formal_cr_${stamp}_rc\${rc} || true
  exit \$rc
" > "${log}" 2>&1 &

echo "pid=$!"
