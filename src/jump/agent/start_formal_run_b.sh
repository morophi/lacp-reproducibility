#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before starting formal Run B.}"

export LACP_DB_NAME="${LACP_DB_NAME:-lacp_db_final}"
if [ "$LACP_DB_NAME" != "lacp_db_final" ]; then
  echo "LACP_DB_NAME must be lacp_db_final, got $LACP_DB_NAME" >&2
  exit 2
fi
export RUN_B_BATCH_SIZE="${RUN_B_BATCH_SIZE:-5}"
export RUN_B_REPETITION_START_INDEX="${RUN_B_REPETITION_START_INDEX:-1}"
export RUN_B_RUN_ID_PREFIX="${RUN_B_RUN_ID_PREFIX:-run_b_repetition_#x}"
case "$RUN_B_BATCH_SIZE" in
  ''|*[!0-9]*)
    echo "RUN_B_BATCH_SIZE must be a positive integer, got $RUN_B_BATCH_SIZE" >&2
    exit 2
    ;;
esac
case "$RUN_B_REPETITION_START_INDEX" in
  ''|*[!0-9]*)
    echo "RUN_B_REPETITION_START_INDEX must be a positive integer, got $RUN_B_REPETITION_START_INDEX" >&2
    exit 2
    ;;
esac
if [ "$RUN_B_BATCH_SIZE" -lt 1 ] || [ "$RUN_B_BATCH_SIZE" -gt 5 ]; then
  echo "RUN_B_BATCH_SIZE must be between 1 and 5 for gated Run B batches, got $RUN_B_BATCH_SIZE" >&2
  exit 2
fi
if [ "$RUN_B_REPETITION_START_INDEX" -lt 1 ] || [ "$RUN_B_REPETITION_START_INDEX" -gt 30 ]; then
  echo "RUN_B_REPETITION_START_INDEX must be between 1 and 30, got $RUN_B_REPETITION_START_INDEX" >&2
  exit 2
fi
run_b_batch_end=$((RUN_B_REPETITION_START_INDEX + RUN_B_BATCH_SIZE - 1))
if [ "$run_b_batch_end" -gt 30 ]; then
  echo "Run B batch exceeds repetition #30: start=$RUN_B_REPETITION_START_INDEX size=$RUN_B_BATCH_SIZE end=$run_b_batch_end" >&2
  exit 2
fi
export LACP_AGENT_PYTHON="${LACP_AGENT_PYTHON:-/home/lacp/proxy-jump/bin/python}"
if [ ! -x "$LACP_AGENT_PYTHON" ]; then
  echo "LACP_AGENT_PYTHON is not executable: $LACP_AGENT_PYTHON" >&2
  exit 2
fi
"$LACP_AGENT_PYTHON" -c 'import pymysql' >/dev/null

mkdir -p \
  /home/lacp/agent/validation_queries/formal_run_b_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(ssh -n -o BatchMode=yes -o ConnectTimeout=5 dblog date +%Y%m%dT%H%M%SKST)"
batch_label="rep${RUN_B_REPETITION_START_INDEX}_to_${run_b_batch_end}"
log="/home/lacp/agent/validation_queries/formal_run_b_logs/formal_run_b_${batch_label}_${stamp}.log"
status="/home/lacp/agent/validation_queries/formal_run_b_logs/formal_run_b_${batch_label}_${stamp}.status"
post_status="/home/lacp/agent/validation_queries/formal_run_b_logs/formal_run_b_${batch_label}_${stamp}.post_validation.log"
theta_check_status="/home/lacp/agent/validation_queries/formal_run_b_logs/formal_run_b_${batch_label}_${stamp}.theta_locked_check.log"
design_check_status="/home/lacp/agent/validation_queries/formal_run_b_logs/formal_run_b_${batch_label}_${stamp}.design_readiness_check.log"

echo "log=${log}"
echo "status=${status}"
echo "post_validation=${post_status}"
echo "theta_locked_check=${theta_check_status}"
echo "design_readiness_check=${design_check_status}"
echo "run_b_batch_start=${RUN_B_REPETITION_START_INDEX}"
echo "run_b_batch_size=${RUN_B_BATCH_SIZE}"
echo "run_b_batch_end=${run_b_batch_end}"
echo "run_id_prefix=${RUN_B_RUN_ID_PREFIX}"
if [ "$run_b_batch_end" -lt 30 ]; then
  next_start=$((run_b_batch_end + 1))
  echo "next_batch_after_review=RUN_B_RUN_ID_PREFIX=${RUN_B_RUN_ID_PREFIX} RUN_B_REPETITION_START_INDEX=${next_start} RUN_B_BATCH_SIZE=${RUN_B_BATCH_SIZE} LACP_DB_PASSWORD=<set> ./start_formal_run_b.sh"
else
  echo "next_batch_after_review=complete"
fi

/home/lacp/agent/check_theta_locked.py \
  --harness-host harness \
  --theta-path /home/lacp/harness/config/theta_config.json \
  > "${theta_check_status}" 2>&1

/home/lacp/agent/check_formal_run_b_design_readiness.py \
  --node-config-path /home/lacp/harness/config/node_config.yaml \
  --run-mode formal \
  > "${design_check_status}" 2>&1

nohup bash -lc "
  cd /home/lacp/agent
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  export LACP_DB_NAME=\"\${LACP_DB_NAME}\"
  export LACP_AGENT_PYTHON=\"\${LACP_AGENT_PYTHON}\"
  \"\${LACP_AGENT_PYTHON}\" -u run_experiment_stage.py \
    --stage run_b \
    --run-id-prefix \"\${RUN_B_RUN_ID_PREFIX}\" \
    --repetitions \"\${RUN_B_BATCH_SIZE}\" \
    --repetition-start-index \"\${RUN_B_REPETITION_START_INDEX}\" \
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
  echo \$rc > '${status}.stage'
  echo \$rc > '${status}'
  if [ \"\$rc\" -eq 0 ]; then
    /home/lacp/agent/run_formal_post_validation_from_log.sh \
      run_b '${log}' /home/lacp/agent/validation_queries/formal_post_validation \
      > '${post_status}' 2>&1
    post_rc=\$?
    echo \$post_rc > '${status}.post'
    if [ \"\$post_rc\" -ne 0 ]; then
      echo \$post_rc > '${status}'
      /home/lacp/agent/schedule_runtime_log_sync.sh formal_run_b_${batch_label}_${stamp}_post_rc\${post_rc} || true
      exit \$post_rc
    fi
  fi
  echo \$rc > '${status}'
  /home/lacp/agent/schedule_runtime_log_sync.sh formal_run_b_${batch_label}_${stamp}_rc\${rc} || true
  exit \$rc
" > "${log}" 2>&1 &

echo "pid=$!"
