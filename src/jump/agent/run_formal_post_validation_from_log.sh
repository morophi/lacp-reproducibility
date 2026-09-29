#!/usr/bin/env bash
set -euo pipefail

stage="${1:?Usage: run_formal_post_validation_from_log.sh STAGE LOG_PATH OUTPUT_DIR}"
log_path="${2:?Usage: run_formal_post_validation_from_log.sh STAGE LOG_PATH OUTPUT_DIR}"
output_dir="${3:?Usage: run_formal_post_validation_from_log.sh STAGE LOG_PATH OUTPUT_DIR}"

mkdir -p "${output_dir}"
agent_python="${LACP_AGENT_PYTHON:-/home/lacp/proxy-jump/bin/python}"

mapfile -t run_ids < <(
  awk '/stage_run_done run_id=/ {
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^run_id=/) {
        sub(/^run_id=/, "", $i)
        print $i
      }
    }
  }' "${log_path}" | sort -u
)

if [ "${#run_ids[@]}" -eq 0 ]; then
  echo "post_validation_no_completed_run_ids log=${log_path}" >&2
  exit 2
fi

for run_id in "${run_ids[@]}"; do
  echo "post_validation_start stage=${stage} run_id=${run_id}"
  "${agent_python}" -u /home/lacp/agent/post_validate_formal_run.py \
    --stage "${stage}" \
    --run-id "${run_id}" \
    --harness-host harness \
    --expected-turns 30 \
    --output-dir "${output_dir}"
  echo "post_validation_done stage=${stage} run_id=${run_id}"
done
