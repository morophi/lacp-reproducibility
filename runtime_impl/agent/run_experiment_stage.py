#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run predeclared LACP experiment stages through Harness.

The agent node owns stage orchestration: run-id creation, repeated scenario
dispatch, and lightweight dblog row-count checks. Harness remains the per-turn
executor and evidence writer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from scenario_loader import load_scenario
from scenario_sender import send_scenario


DEFAULT_SCENARIO = "/home/morophi/agent/scenario/lacp_30turn_civil_complaint_v1.json"
DEFAULT_HARNESS_URL = "http://10.1.1.110:9000"
DEFAULT_DB_HOST = "10.1.1.130"
DEFAULT_DB_USER = "morophi"
DEFAULT_DB_PASSWORD = os.environ.get("LACP_DB_PASSWORD", "")
DEFAULT_DB_NAME = "lacp_db"
DEFAULT_HARNESS_HOST = "10.1.1.110"
DEFAULT_THETA_PATH = "/home/morophi/harness/config/theta_config.json"
DEFAULT_NODE_CONFIG_PATH = "/home/morophi/harness/config/node_config.yaml"
DEFAULT_ENTROPY_PERCENTILE = 0.70
DEFAULT_TRIGGER_PERCENTILE = 0.95


@dataclass(frozen=True)
class StageSpec:
    condition: str
    run_mode: str
    repetitions: int
    max_turns: Optional[int]
    run_id_prefix: str
    expected_nodes: int = 3
    causal_evidence: bool = True


STAGES = {
    "tr": StageSpec(
        condition="run_b",
        run_mode="smoke",
        repetitions=3,
        max_turns=2,
        run_id_prefix="tr",
        causal_evidence=False,
    ),
    "cr": StageSpec(
        condition="cr",
        run_mode="formal",
        repetitions=10,
        max_turns=None,
        run_id_prefix="cr",
    ),
    "cr2": StageSpec(
        condition="cr2",
        run_mode="formal",
        repetitions=3,
        max_turns=None,
        run_id_prefix="cr2",
    ),
    "run_b": StageSpec(
        condition="run_b",
        run_mode="formal",
        repetitions=10,
        max_turns=None,
        run_id_prefix="run_b",
    ),
    "cf_a": StageSpec(
        condition="cf_a",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_a",
    ),
    "cf_b": StageSpec(
        condition="cf_b",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_b",
    ),
    "cf_c": StageSpec(
        condition="cf_c",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_c",
    ),
    "cf_d": StageSpec(
        condition="cf_d",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_d",
    ),
    "cf_e": StageSpec(
        condition="cf_e",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_e",
    ),
    "cf_f": StageSpec(
        condition="cf_f",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix="cf_f",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a LACP experiment stage through Harness.")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES), help="Experiment stage to run.")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO, help="Scenario JSON path on the agent node.")
    parser.add_argument("--harness-url", default=DEFAULT_HARNESS_URL, help="Harness base URL.")
    parser.add_argument("--run-id-prefix", default=None, help="Override run_id prefix.")
    parser.add_argument("--repetitions", type=int, default=None, help="Override stage repetition count.")
    parser.add_argument("--max-turns", type=int, default=None, help="Override max turns per run.")
    parser.add_argument("--full-scenario", action="store_true", help="Ignore stage max-turn default and run all turns.")
    parser.add_argument("--skip-db-check", action="store_true", help="Skip dblog row-count validation.")
    parser.add_argument("--skip-theta-freeze", action="store_true", help="Do not freeze theta after CR2.")
    parser.add_argument(
        "--entropy-percentile",
        type=float,
        default=DEFAULT_ENTROPY_PERCENTILE,
        help="Percentile for theta_entropy over CR2 token entropy values.",
    )
    parser.add_argument(
        "--trigger-percentile",
        type=float,
        default=DEFAULT_TRIGGER_PERCENTILE,
        help="Percentile for theta_lms/theta_cds/theta_ma over CR2 absolute Node C-relative differentials.",
    )
    parser.add_argument("--harness-host", default=DEFAULT_HARNESS_HOST, help="SSH/SCP target for Harness.")
    parser.add_argument("--theta-path", default=DEFAULT_THETA_PATH, help="theta_config.json path on Harness.")
    parser.add_argument("--node-config-path", default=DEFAULT_NODE_CONFIG_PATH, help="node_config path on Harness.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without sending turns.")
    return parser.parse_args()


def make_run_id(prefix: str, repetition: int) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{prefix}_{stamp}_rep{repetition:02d}"


def expected_turns(scenario: str, max_turns: Optional[int]) -> int:
    data = load_scenario(scenario)
    total = len(data["turns"])
    return total if max_turns is None else min(max_turns, total)


def db_count_query(run_id: str) -> str:
    return (
        "SELECT 'experiment_runs', COUNT(*) FROM experiment_runs WHERE run_id='{run_id}' "
        "UNION ALL SELECT 'turn_node_logs', COUNT(*) FROM v_turn_node_logs WHERE run_id='{run_id}' "
        "UNION ALL SELECT 'intervention_logs', COUNT(*) FROM v_intervention_logs WHERE run_id='{run_id}' "
        "UNION ALL SELECT 'metric_logs', COUNT(*) FROM v_metric_logs WHERE run_id='{run_id}' "
        "UNION ALL SELECT 'payload_audit_logs', COUNT(*) FROM v_payload_audit_logs WHERE run_id='{run_id}'"
    ).format(run_id=run_id)


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def run_mysql_query(query: str) -> str:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for dblog queries")
    command = [
        "mysql",
        f"-h{DEFAULT_DB_HOST}",
        f"-u{DEFAULT_DB_USER}",
        f"--password={DEFAULT_DB_PASSWORD}",
        DEFAULT_DB_NAME,
        "-N",
        "-B",
        "-e",
        query,
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"dblog query failed: {proc.stderr.strip()}")
    return proc.stdout


def check_db_rows(run_id: str, turns: int, expected_nodes: int) -> None:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for dblog row-count checks")
    expected_node_rows = turns * expected_nodes
    command = [
        "mysql",
        f"-h{DEFAULT_DB_HOST}",
        f"-u{DEFAULT_DB_USER}",
        f"--password={DEFAULT_DB_PASSWORD}",
        DEFAULT_DB_NAME,
        "-N",
        "-e",
        db_count_query(run_id),
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"dblog row-count check failed: {proc.stderr.strip()}")
    counts = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        table, value = line.split("\t", 1)
        counts[table] = int(value)
    expected = {
        "experiment_runs": 1,
        "turn_node_logs": expected_node_rows,
        "intervention_logs": expected_node_rows,
        "metric_logs": expected_node_rows,
        "payload_audit_logs": expected_node_rows,
    }
    mismatches = {key: (counts.get(key), value) for key, value in expected.items() if counts.get(key) != value}
    if mismatches:
        raise RuntimeError(f"dblog row-count mismatch for {run_id}: {mismatches}")
    print(f"db_check ok run_id={run_id} turns={turns} node_rows={expected_node_rows}")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile from an empty value set")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def fetch_cr2_metric_values(run_ids: list[str]) -> dict[str, object]:
    run_id_list = ", ".join(sql_quote(run_id) for run_id in run_ids)
    query = f"""
SELECT run_id, turn_no, node, lms_value, cds, ma_assert, metric_status, metrics_json
FROM v_metric_logs
WHERE run_id IN ({run_id_list})
  AND analysis_eligible = 1
  AND COALESCE(exclude_from_causal_trigger, 0) = 0
ORDER BY run_id, turn_no, node
"""
    rows_by_turn: dict[tuple[str, int], dict[str, dict[str, object]]] = {}
    entropy_values: list[float] = []
    for line in run_mysql_query(query).splitlines():
        if not line.strip():
            continue
        run_id, turn_no, node, lms_value, cds, ma_assert, metric_status, metrics_json = line.split("\t", 7)
        status = {} if metric_status in {"", "NULL"} else json.loads(metric_status)
        metrics = {} if metrics_json in {"", "NULL"} else json.loads(metrics_json)
        for item in status.get("lms_token_entropies", []):
            if isinstance(item, (int, float)):
                entropy_values.append(float(item))
        row = {
            "lms_value": _float_or_none(lms_value),
            "cds": _float_or_none(cds),
            "ma_assert": _float_or_none(ma_assert),
            "metric_status": status,
            "metrics": metrics,
        }
        rows_by_turn.setdefault((run_id, int(turn_no)), {})[node] = row

    values = {"d_lms_abs": [], "d_cds_abs": [], "d_ma_abs": []}
    non_trigger_eligible_turns = []
    for (run_id, turn_no), nodes in sorted(rows_by_turn.items()):
        c = nodes.get("C")
        if not c:
            continue
        turn_is_trigger_eligible = False
        for node in ("A", "B"):
            x = nodes.get(node)
            if not x:
                continue
            d_lms = _diff(x.get("lms_value"), c.get("lms_value"), "x_minus_c")
            d_cds = _diff(x.get("cds"), c.get("cds"), "c_minus_x")
            d_ma = _diff(x.get("ma_assert"), c.get("ma_assert"), "x_minus_c")
            if d_lms is not None:
                values["d_lms_abs"].append(abs(d_lms))
            if d_cds is not None:
                values["d_cds_abs"].append(abs(d_cds))
            if d_ma is not None:
                values["d_ma_abs"].append(abs(d_ma))
            if any(value is not None and value > 0.0 for value in (d_lms, d_cds, d_ma)):
                turn_is_trigger_eligible = True
        if not turn_is_trigger_eligible:
            non_trigger_eligible_turns.append(turn_no)

    return {
        "theta_values": values,
        "entropy_values": entropy_values,
        "non_trigger_eligible_turns": sorted(set(non_trigger_eligible_turns)),
    }


def _float_or_none(raw: str) -> Optional[float]:
    if raw in {"", "NULL"}:
        return None
    return float(raw)


def _diff(left: object, right: object, direction: str) -> Optional[float]:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    if direction == "x_minus_c":
        return float(left) - float(right)
    if direction == "c_minus_x":
        return float(right) - float(left)
    raise ValueError(f"unsupported differential direction: {direction}")


def fetch_cr2_run_metadata(run_ids: list[str]) -> dict[str, object]:
    run_id_list = ", ".join(sql_quote(run_id) for run_id in run_ids)
    query = f"""
SELECT run_id, scenario_hash, node_config_hash, policy_hash
FROM experiment_runs
WHERE run_id IN ({run_id_list})
ORDER BY run_id
"""
    rows = []
    for line in run_mysql_query(query).splitlines():
        if not line.strip():
            continue
        run_id, scenario_hash, node_config_hash, policy_hash = line.split("\t")
        rows.append(
            {
                "run_id": run_id,
                "scenario_hash": None if scenario_hash in {"", "NULL"} else scenario_hash,
                "node_config_hash": None if node_config_hash in {"", "NULL"} else node_config_hash,
                "sc_policy_hash": None if policy_hash in {"", "NULL"} else policy_hash,
            }
        )
    return {
        "runs": rows,
        "scenario_hashes": sorted({row["scenario_hash"] for row in rows if row["scenario_hash"]}),
        "node_config_hashes": sorted({row["node_config_hash"] for row in rows if row["node_config_hash"]}),
        "sc_policy_hashes": sorted({row["sc_policy_hash"] for row in rows if row["sc_policy_hash"]}),
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_theta_config(
    run_ids: list[str],
    calibration: dict[str, object],
    expected_rows: int,
    entropy_percentile: float,
    trigger_percentile: float,
    metadata: dict[str, object],
) -> dict[str, object]:
    if not 0.0 < entropy_percentile < 1.0:
        raise ValueError("--entropy-percentile must be > 0 and < 1")
    if not 0.0 < trigger_percentile < 1.0:
        raise ValueError("--trigger-percentile must be > 0 and < 1")
    values = calibration["theta_values"]
    entropy_values = calibration["entropy_values"]
    if not isinstance(values, dict) or not isinstance(entropy_values, list):
        raise TypeError("invalid CR2 calibration payload")
    counts = {key: len(items) for key, items in values.items()}
    missing = {key: (count, expected_rows) for key, count in counts.items() if count < expected_rows}
    if missing:
        raise RuntimeError(f"CR2 theta freeze blocked; insufficient eligible metric rows: {missing}")
    if not entropy_values:
        raise RuntimeError(
            "CR2 theta freeze blocked; no lms_token_entropies found. "
            "Re-run CR2 with the updated Harness metrics logger."
        )

    return {
        "theta_entropy": percentile(entropy_values, entropy_percentile),
        "theta_lms": percentile(values["d_lms_abs"], trigger_percentile),
        "theta_cds": percentile(values["d_cds_abs"], trigger_percentile),
        "theta_ma": percentile(values["d_ma_abs"], trigger_percentile),
        "source": "CR2",
        "locked": True,
        "cr2_run_id": run_ids,
        "percentile_rule": {
            "theta_entropy": entropy_percentile,
            "theta_lms": trigger_percentile,
            "theta_cds": trigger_percentile,
            "theta_ma": trigger_percentile,
        },
        "direction_convention": {
            "d_lms": "LMS_X - LMS_C for X in {A,B}; threshold exceedance when d_lms > theta_lms",
            "d_cds": "CDS_C - CDS_X for X in {A,B}; threshold exceedance when d_cds > theta_cds",
            "d_ma": "MA_assert_X - MA_assert_C for X in {A,B}; threshold exceedance when d_ma > theta_ma",
            "trigger_threshold_basis": "empirical percentile of absolute CR2 Node C-relative differentials",
        },
        "calibration": {
            "algorithm": "cr2_oriented_differential_percentile_v1",
            "rules": {
                "theta_entropy": "70th percentile of CR2 natural RAG-off token entropy distribution",
                "theta_lms": "95th percentile of |LMS_X - LMS_C| for X in {A,B}",
                "theta_cds": "95th percentile of |CDS_C - CDS_X| for X in {A,B}",
                "theta_ma": "95th percentile of |MA_assert_X - MA_assert_C| for X in {A,B}",
            },
            "run_ids": run_ids,
            "expected_rows_per_metric": expected_rows,
            "metric_counts": counts,
            "entropy_token_count": len(entropy_values),
            "non_trigger_eligible_turns": calibration.get("non_trigger_eligible_turns", []),
            "run_metadata": metadata,
            "script_sha256": file_sha256(Path(__file__)),
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "node_config_hash": metadata.get("node_config_hashes", []),
        "sc_policy_hash": metadata.get("sc_policy_hashes", []),
        "corpus_hash": metadata.get("scenario_hashes", []),
        "code_git_sha": git_sha(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notes": "Auto-frozen after CR2 by run_experiment_stage.py. Required for final Run B and CF execution.",
    }


def git_sha() -> Optional[str]:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def write_local_theta(theta: dict[str, object], prefix: str) -> Path:
    path = Path(f"/tmp/{prefix}_theta_config_{int(time.time())}.json")
    path.write_text(json.dumps(theta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def install_theta_config(theta_path: Path, harness_host: str, remote_theta_path: str) -> None:
    remote_tmp = f"{remote_theta_path}.tmp.{int(time.time())}.{os.getpid()}"
    subprocess.run(["scp", str(theta_path), f"{harness_host}:{remote_tmp}"], check=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    remote_cmd = (
        f"set -e; "
        f"cp {remote_theta_path} {remote_theta_path}.bak.{stamp}; "
        f"mv {remote_tmp} {remote_theta_path}; "
        f"systemctl --user restart lacp-harness.service; "
        f"systemctl --user is-active lacp-harness.service"
    )
    subprocess.run(["ssh", harness_host, remote_cmd], check=True)


def install_cf_f_non_trigger_turns(
    harness_host: str,
    remote_node_config_path: str,
    non_trigger_eligible_turns: list[int],
) -> None:
    if not non_trigger_eligible_turns:
        raise RuntimeError("CF-F config update blocked; CR2 produced no non-trigger-eligible turns")
    code = r"""
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
turns = json.loads(sys.argv[2])
data = json.loads(path.read_text(encoding="utf-8"))
cf_f = data.setdefault("counterfactual", {}).setdefault("cf_f", {})
cf_f["non_trigger_eligible_turns"] = turns
if not cf_f.get("injection_turns"):
    cf_f["injection_turns"] = []
stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
backup = path.with_name(path.name + f".bak.cf_f.{stamp}")
backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"cf_f_non_trigger_turns_updated path={path} count={len(turns)} backup={backup}")
"""
    remote_cmd = " ".join(
        [
            "set -e;",
            "python3",
            "-c",
            shlex.quote(code),
            shlex.quote(remote_node_config_path),
            shlex.quote(json.dumps(non_trigger_eligible_turns)),
            ";",
            "systemctl --user restart lacp-harness.service",
            ";",
            "systemctl --user is-active lacp-harness.service",
        ]
    )
    subprocess.run(["ssh", harness_host, remote_cmd], check=True)


def freeze_theta_after_cr2(args: argparse.Namespace, run_ids: list[str], turns: int, repetitions: int) -> None:
    expected_rows = turns * repetitions * 2
    calibration = fetch_cr2_metric_values(run_ids)
    metadata = fetch_cr2_run_metadata(run_ids)
    theta = build_theta_config(
        run_ids,
        calibration,
        expected_rows,
        args.entropy_percentile,
        args.trigger_percentile,
        metadata,
    )
    theta_path = write_local_theta(theta, args.run_id_prefix or "cr2")
    install_theta_config(theta_path, args.harness_host, args.theta_path)
    install_cf_f_non_trigger_turns(
        args.harness_host,
        args.node_config_path,
        theta["calibration"]["non_trigger_eligible_turns"],
    )
    print(
        "theta_freeze_done "
        f"path={args.theta_path} theta_entropy={theta['theta_entropy']:.10g} "
        f"theta_lms={theta['theta_lms']:.10g} "
        f"theta_cds={theta['theta_cds']:.10g} theta_ma={theta['theta_ma']:.10g}"
    )


async def run_stage(args: argparse.Namespace) -> None:
    spec = STAGES[args.stage]
    repetitions = args.repetitions if args.repetitions is not None else spec.repetitions
    if repetitions < 1:
        raise ValueError("--repetitions must be >= 1")
    max_turns = None if args.full_scenario else (args.max_turns if args.max_turns is not None else spec.max_turns)
    prefix = args.run_id_prefix or spec.run_id_prefix
    turns = expected_turns(args.scenario, max_turns)

    print(
        "stage_plan "
        f"stage={args.stage} condition={spec.condition} run_mode={spec.run_mode} "
        f"repetitions={repetitions} turns_per_run={turns} causal_evidence={spec.causal_evidence}"
    )

    run_ids = []
    for index in range(1, repetitions + 1):
        run_id = make_run_id(prefix, index)
        run_ids.append(run_id)
        print(f"stage_run_start run_id={run_id}")
        if not args.dry_run:
            await send_scenario(
                args.scenario,
                args.harness_url,
                run_id,
                spec.condition,
                spec.run_mode,
                max_turns=max_turns,
            )
            if not args.skip_db_check:
                check_db_rows(run_id, turns, spec.expected_nodes)
        print(f"stage_run_done run_id={run_id}")

    if args.stage == "cr2" and not args.dry_run and not args.skip_theta_freeze:
        freeze_theta_after_cr2(args, run_ids, turns, repetitions)


def main() -> None:
    args = parse_args()
    asyncio.run(run_stage(args))


if __name__ == "__main__":
    main()
