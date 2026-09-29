#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

pw="${LACP_DB_PASSWORD:-}"

if [ -z "$pw" ]; then
  pw="$(
    ssh -o BatchMode=yes -o ConnectTimeout=5 harness 'for f in /proc/[0-9]*/environ; do
      line=$(strings "$f" 2>/dev/null | grep "^LACP_DB_PASSWORD=" | head -n 1 || true)
      if [ -n "$line" ]; then
        printf "%s" "${line#LACP_DB_PASSWORD=}"
        exit 0
      fi
    done'
  )"
fi

if [ -z "$pw" ]; then
  echo "LACP_DB_PASSWORD unavailable from harness process environment" >&2
  exit 2
fi
export LACP_DB_PASSWORD="$pw"
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

mkdir -p \
  /home/lacp/agent/validation_queries/formal_cr_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(ssh -n -o BatchMode=yes -o ConnectTimeout=5 dblog date +%Y%m%dT%H%M%SKST)"
log="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr1_${stamp}.log"
status="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr1_${stamp}.status"
monitor="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr1_${stamp}.monitor"
meta="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr1_${stamp}.meta"
post_status="/home/lacp/agent/validation_queries/formal_cr_logs/formal_cr1_${stamp}.post_validation.log"

cat > "$meta" <<META
stamp=${stamp}
run_id_prefix=cr_1st
log=${log}
status=${status}
monitor=${monitor}
launcher=/home/lacp/agent/start_formal_cr1_once.sh
META

echo "log=${log}"
echo "status=${status}"
echo "monitor=${monitor}"
echo "meta=${meta}"
echo "post_validation=${post_status}"

nohup bash -lc "
  cd /home/lacp/agent
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  export LACP_DB_NAME=\"\${LACP_DB_NAME}\"
  export LACP_AGENT_PYTHON=\"\${LACP_AGENT_PYTHON}\"
  /home/lacp/agent/cr_pre_run_hard_reset_gate.sh
  \"\${LACP_AGENT_PYTHON}\" -u run_experiment_stage.py \
    --stage cr \
    --run-id-prefix cr_1st \
    --repetitions 1 \
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
  echo \$rc > '${status}.stage'
  echo \$rc > '${status}'
  if [ \"\$rc\" -eq 0 ]; then
    /home/lacp/agent/run_formal_post_validation_from_log.sh \
      cr '${log}' /home/lacp/agent/validation_queries/formal_post_validation \
      > '${post_status}' 2>&1
    post_rc=\$?
    echo \$post_rc > '${status}.post'
    if [ \"\$post_rc\" -ne 0 ]; then
      echo \$post_rc > '${status}'
      /home/lacp/agent/schedule_runtime_log_sync.sh formal_cr1_${stamp}_post_rc\${post_rc} || true
      exit \$post_rc
    fi
  fi
  echo \$rc > '${status}'
  /home/lacp/agent/schedule_runtime_log_sync.sh formal_cr1_${stamp}_rc\${rc} || true
  exit \$rc
" > "${log}" 2>&1 &

run_pid="$!"
echo "pid=${run_pid}"

if [ -x /home/lacp/agent/monitor_formal_cr_local.sh ]; then
  nohup /home/lacp/agent/monitor_formal_cr_local.sh "$log" "$status" "$monitor" \
    > "${monitor}.stdout" 2> "${monitor}.stderr" &
  echo "monitor_pid=$!"
else
  echo "monitor_warning=/home/lacp/agent/monitor_formal_cr_local.sh missing or not executable" >&2
fi
