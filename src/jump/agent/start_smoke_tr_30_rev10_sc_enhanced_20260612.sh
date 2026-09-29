#!/usr/bin/env bash
set -euo pipefail

cd /home/lacp/agent

: "${LACP_DB_PASSWORD:?Set LACP_DB_PASSWORD before running smoke TR.}"

mkdir -p \
  /home/lacp/agent/validation_queries/smoke_tr_logs \
  /home/lacp/agent/validation_queries/formal_thermal

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
stage="run_b"
repetitions="1"
run_id_prefix="smoke_tr_run_b_30_rev10_sc_enhanced"
log="/home/lacp/agent/validation_queries/smoke_tr_logs/${run_id_prefix}_${stamp}.log"
status="/home/lacp/agent/validation_queries/smoke_tr_logs/${run_id_prefix}_${stamp}.status"

python3 - <<'PY'
import subprocess
import sys

CONFIG_PATH = "/home/lacp/harness/config/node_config.yaml"
EXPECTED_DB = "lacp_rev10_sc_enhanced_db"
EXPECTED_ROLES = {"A": "rag_sc", "B": "rag_only", "C": "baseline"}

# This is a read-only preflight contract check. The agent does not mutate
# harness-owned config; it fails early if the expected Rev9-10/Rev12 runtime
# contract is not currently installed on Harness.

def load_config(raw):
    try:
        import json

        return json.loads(raw)
    except Exception as json_exc:
        try:
            import yaml
        except Exception as yaml_exc:
            raise SystemExit(
                "preflight_failed: node_config is not JSON and PyYAML is unavailable "
                f"(json_error={json_exc}; yaml_import_error={yaml_exc})"
            )
        return yaml.safe_load(raw)

raw = subprocess.check_output(
    ["ssh", "-o", "BatchMode=yes", "harness", f"cat {CONFIG_PATH}"],
    text=True,
)
cfg = load_config(raw)
errors = []

nodes = cfg.get("nodes", {})
for node, role in EXPECTED_ROLES.items():
    actual = nodes.get(node, {}).get("role")
    if actual != role:
        errors.append(f"node {node} role expected {role}, got {actual}")

run_cfg = cfg.get("run", {})
if run_cfg.get("experiment_design") == "rag_response_shift_rev11":
    errors.append("run.experiment_design must not be rag_response_shift_rev11")
if run_cfg.get("active_nodes") not in (None, ["A", "B", "C"]):
    errors.append(f"run.active_nodes must be absent or ['A','B','C'], got {run_cfg.get('active_nodes')}")
if run_cfg.get("sc_enabled") is False:
    errors.append("run.sc_enabled must not be false")
if run_cfg.get("intervention_mode") == "fixed_rag_exposure":
    errors.append("run.intervention_mode must not be fixed_rag_exposure")

db_name = cfg.get("logging", {}).get("db", {}).get("database")
if db_name != EXPECTED_DB:
    errors.append(f"logging.db.database expected {EXPECTED_DB}, got {db_name}")

smoke_cfg = cfg.get("run_modes", {}).get("smoke", {})
if smoke_cfg.get("rag_top_k") != 3:
    errors.append(f"run_modes.smoke.rag_top_k expected 3, got {smoke_cfg.get('rag_top_k')}")
if smoke_cfg.get("history_window_turns") != 3:
    errors.append(
        f"run_modes.smoke.history_window_turns expected 3, got {smoke_cfg.get('history_window_turns')}"
    )

if errors:
    print("preflight_failed: harness node_config is not Rev9-10/Rev12 three-node SC-enhanced config", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    sys.exit(2)

print(
    "preflight_ok: A=rag_sc B=rag_only C=baseline db=lacp_rev10_sc_enhanced_db smoke_top_k=3 smoke_history=3"
)
PY

if [[ "${stage}" != "run_b" ]]; then
  echo "preflight_failed: smoke TR intervention check must run with stage=run_b, got ${stage}" >&2
  exit 2
fi
if [[ "${repetitions}" != "1" ]]; then
  echo "preflight_failed: smoke TR intervention check must run exactly one repetition, got ${repetitions}" >&2
  exit 2
fi

nohup bash -lc "
  cd /home/lacp/agent
  export LACP_DB_PASSWORD=\"\${LACP_DB_PASSWORD}\"
  python3 -u run_experiment_stage.py \
    --stage ${stage} \
    --run-mode smoke \
    --repetitions ${repetitions} \
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
  echo \$? > '${status}'
" > "${log}" 2>&1 &

echo "pid=$!"
echo "log=${log}"
echo "status=${status}"
