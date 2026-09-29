#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before starting Run B readiness.}"
: "${LACP_DB_NAME:?Set LACP_DB_NAME before starting Run B readiness.}"

if [[ "${LACP_DB_NAME}" != "lacp_db_final" ]]; then
  echo "preflight_failed: LACP_DB_NAME must be lacp_db_final, got ${LACP_DB_NAME}" >&2
  exit 2
fi

export PYTHONPATH="/home/lacp/agent/vendor:${PYTHONPATH:-}"

mkdir -p \
  /home/lacp/agent/validation_queries/run_b_readiness_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_id_prefix="readiness_run_b_ragdb_30_20260615"
log="/home/lacp/agent/validation_queries/run_b_readiness_logs/${run_id_prefix}_${stamp}.log"
status="/home/lacp/agent/validation_queries/run_b_readiness_logs/${run_id_prefix}_${stamp}.status"
post_status="/home/lacp/agent/validation_queries/run_b_readiness_logs/${run_id_prefix}_${stamp}.post_validation.log"
db_check="/home/lacp/agent/validation_queries/run_b_readiness_logs/${run_id_prefix}_${stamp}.db_check.json"
evidence_dir="/home/lacp/agent/validation_queries/run_b_readiness_evidence/${run_id_prefix}_${stamp}"
evidence_tar="/home/lacp/agent/validation_queries/run_b_readiness_logs/${run_id_prefix}_${stamp}.evidence.tar.gz"

echo "log=${log}"
echo "status=${status}"
echo "post_validation=${post_status}"
echo "db_check=${db_check}"
echo "evidence_dir=${evidence_dir}"
echo "evidence_tar=${evidence_tar}"

nohup bash -lc "
  set -euo pipefail
  cd /home/lacp/agent
  export PYTHONPATH='/home/lacp/agent/vendor:'\"\${PYTHONPATH:-}\"
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  export LACP_DB_NAME=\"\${LACP_DB_NAME}\"

  python3 -u run_experiment_stage.py \
    --stage run_b \
    --run-mode smoke \
    --repetitions 1 \
    --full-scenario \
    --run-id-prefix ${run_id_prefix} \
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
      run_b '${log}' /home/lacp/agent/validation_queries/formal_post_validation \
      > '${post_status}' 2>&1
    post_rc=\$?
    echo \$post_rc > '${status}.post'
    if [ \"\$post_rc\" -ne 0 ]; then
      echo \$post_rc > '${status}'
      exit \$post_rc
    fi
  fi

  run_id=\$(awk '/stage_run_done run_id=/ {for (i=1; i<=NF; i++) if (\$i ~ /^run_id=/) {sub(/^run_id=/, \"\", \$i); print \$i}}' '${log}' | tail -1)
  if [ -z \"\$run_id\" ]; then
    echo 'db_check_failed: missing completed run_id' >&2
    echo 3 > '${status}'
    exit 3
  fi
  python3 /home/lacp/agent/verify_run_b_readiness_db.py \"\$run_id\" > '${db_check}'
  cat '${db_check}'

  test -s '${log}'
  test -s '${post_status}'
  test -s '${db_check}'

  mkdir -p '${evidence_dir}'
  cp -p '${log}' '${evidence_dir}/run.log'
  cp -p '${post_status}' '${evidence_dir}/post_validation.log'
  cp -p '${db_check}' '${evidence_dir}/db_check.json'
  {
    echo 'run_id='\"\$run_id\"
    echo 'log=${log}'
    echo 'post_validation=${post_status}'
    echo 'db_check=${db_check}'
    echo 'created_at_utc='\"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  } > '${evidence_dir}/manifest.txt'
  tar -C '${evidence_dir}' -czf '${evidence_tar}' .
  test -s '${evidence_tar}'

  /home/lacp/agent/schedule_runtime_log_sync.sh '${stamp}_runtime' || true
  echo 0 > '${status}'
  exit 0
" > "${log}" 2>&1 &

echo "pid=$!"
