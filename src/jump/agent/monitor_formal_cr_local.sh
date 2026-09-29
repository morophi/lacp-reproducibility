#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <log_path> <status_path> <monitor_path>" >&2
  exit 2
fi

log_path="$1"
status_path="$2"
monitor_path="$3"

mkdir -p "$(dirname "$monitor_path")"

{
  echo "monitor_start=$(date -Is)"
  echo "log=${log_path}"
  echo "status=${status_path}"
} > "$monitor_path"

last_turn=""
while true; do
  if [ -f "$log_path" ]; then
    current_turn="$(
      grep -o 'ack turn=[0-9]\\+' "$log_path" 2>/dev/null |
        tail -1 |
        sed 's/ack turn=//' || true
    )"
    if [ -n "$current_turn" ] && [ "$current_turn" != "$last_turn" ]; then
      echo "progress=$(date -Is) ack_turn=${current_turn}" >> "$monitor_path"
      last_turn="$current_turn"
    fi
  fi

  if [ -f "$status_path" ]; then
    status_value="$(cat "$status_path" 2>/dev/null || true)"
    echo "status_seen=$(date -Is) status=${status_value}" >> "$monitor_path"
    if [ -f "$log_path" ]; then
      run_id="$(grep -o 'stage_run_start run_id=[^ ]*' "$log_path" | tail -1 | sed 's/stage_run_start run_id=//' || true)"
      db_check="$(grep 'db_check ok' "$log_path" | tail -1 || true)"
      done_line="$(grep 'stage_run_done' "$log_path" | tail -1 || true)"
      thermal_done="$(grep 'thermal_log_done' "$log_path" | tail -1 || true)"
      echo "run_id=${run_id}" >> "$monitor_path"
      echo "db_check=${db_check}" >> "$monitor_path"
      echo "stage_done=${done_line}" >> "$monitor_path"
      echo "thermal_done=${thermal_done}" >> "$monitor_path"
    fi
    echo "monitor_done=$(date -Is)" >> "$monitor_path"
    exit 0
  fi

  sleep 15
done
