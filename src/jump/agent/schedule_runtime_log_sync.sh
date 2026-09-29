#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

stamp="${1:-$(ssh -n -o BatchMode=yes -o ConnectTimeout=5 dblog date +%Y%m%dT%H%M%SKST)}"
delay="${LACP_RUNTIME_LOG_SYNC_DELAY_SEC:-60}"
nodes="${LACP_RUNTIME_LOG_SYNC_NODES:-agent harness rag inference1 inference2 inference3}"
agent_python="${LACP_AGENT_PYTHON:-/home/lacp/proxy-jump/bin/python}"

args=()
for node in ${nodes}; do
  args+=(--node "${node}")
done

(
  sleep "${delay}"
  cd /home/lacp/agent
  "${agent_python}" sync_runtime_logs_to_dblog.py "${args[@]}" --stamp "${stamp}" --execute
) > "/tmp/lacp_runtime_log_sync_${stamp}.out" 2> "/tmp/lacp_runtime_log_sync_${stamp}.err" &

echo "runtime_log_sync_scheduled=${stamp}"
echo "runtime_log_sync_delay_sec=${delay}"
