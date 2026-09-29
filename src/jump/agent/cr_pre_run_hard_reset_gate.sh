#!/usr/bin/env bash
set -euo pipefail

NODES=("inference-a" "inference-b" "inference-c")
MODEL="${LACP_MODEL_NAME:-qwen3-nothink}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=8)
SUDO_PASSWORD="${LACP_NODE_SUDO_PASSWORD:-}"

if [ -z "$SUDO_PASSWORD" ] && [ -f /home/lacp/.lacp_node_sudo_password ]; then
  SUDO_PASSWORD="$(cat /home/lacp/.lacp_node_sudo_password)"
fi

if [ -z "$SUDO_PASSWORD" ]; then
  echo "LACP_NODE_SUDO_PASSWORD unavailable for CR pre-run hard reset" >&2
  exit 2
fi

echo "cr_pre_run_hard_reset_gate_start"
echo "cr_pre_run_hard_reset_gate_nodes=${NODES[*]}"

for host in "${NODES[@]}"; do
  echo "hard_reset_start host=${host}"
  ssh "${SSH_OPTS[@]}" "$host" "printf '%s\n' '$SUDO_PASSWORD' | sudo -S systemctl restart ollama >/tmp/lacp_ollama_restart.stdout 2>/tmp/lacp_ollama_restart.stderr"
  ssh "${SSH_OPTS[@]}" "$host" "systemctl is-active ollama"
  echo "hard_reset_done host=${host}"
done

echo "hard_reset_settle_start seconds=8"
sleep 8
echo "hard_reset_settle_done"

for host in "${NODES[@]}"; do
  echo "hard_reset_unload_start host=${host}"
  curl -fsS -X POST "http://${host}:11434/api/generate" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":0}" >/dev/null
  echo "hard_reset_unload_done host=${host}"
done

echo "hard_reset_empty_check_start"
for host in "${NODES[@]}"; do
  body="$(curl -fsS "http://${host}:11434/api/ps")"
  echo "hard_reset_api_ps host=${host} body=${body}"
  if [ "$body" != '{"models":[]}' ]; then
    echo "hard reset /api/ps not empty on ${host}: ${body}" >&2
    exit 3
  fi
done

echo "cr_pre_run_hard_reset_gate_done"
