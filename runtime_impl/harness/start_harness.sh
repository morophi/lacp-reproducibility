#!/usr/bin/env bash
set -euo pipefail

HARNESS_HOME="${HARNESS_HOME:-/home/morophi/harness}"
ENV_FILE="${HARNESS_ENV_FILE:-$HARNESS_HOME/.env.local}"
PYTHON_BIN="${HARNESS_PYTHON:-/home/morophi/harness_venv/bin/python}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${LACP_DB_PASSWORD:-}" ]]; then
  echo "LACP_DB_PASSWORD must be set in $ENV_FILE or the process environment" >&2
  exit 2
fi

exec "$PYTHON_BIN" "$HARNESS_HOME/harness_server.py" \
  --config "$HARNESS_HOME/config/node_config.yaml" \
  --sc-policy "$HARNESS_HOME/config/sc_policy.yaml" \
  --theta "$HARNESS_HOME/config/theta_config.json" \
  --host "${HARNESS_HOST:-0.0.0.0}" \
  --port "${HARNESS_PORT:-9000}"
