#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run a pre-formal stage rehearsal with DB writes disabled and write MD evidence.

The official Harness on port 9000 is left untouched. This script starts a
temporary Harness on a separate port with `logging.db.enabled = false`, executes
one declared stage through the existing agent-side stage runner, fetches the
JSONL fallback rows, verifies that dblog has no rows for the generated run ids,
and writes a Markdown pre-formal audit artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "validation_queries" / "preformal_md"
SCRATCH_DIR = REPO_ROOT / ".node_sync_logs" / "preformal_jsonl"
PREFORMAL_THETA_PATH = OUTPUT_DIR / "preformal_theta_config.json"
PREFORMAL_CALIBRATION_PATH = OUTPUT_DIR / "preformal_cr2_calibration.json"

DEFAULT_STAGE_RUNNER = "/home/morophi/agent/run_experiment_stage.py"
DEFAULT_SCENARIO = "/home/morophi/agent/scenario/lacp_30turn_civil_complaint_v1.json"
DEFAULT_HARNESS_HOST = "harness"
DEFAULT_JUMP_HOST = "jump"
DEFAULT_HARNESS_IP = "10.1.1.110"
DEFAULT_PORT = 9010
DEFAULT_HARNESS_HOME = "/home/morophi/harness"

STAGES = {
    "tr": {"condition": "run_b", "run_mode": "smoke", "repetitions": 1, "max_turns": 2},
    "cr": {"condition": "cr", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cr2": {"condition": "cr2", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "run_b": {"condition": "run_b", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_a": {"condition": "cf_a", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_b": {"condition": "cf_b", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_c": {"condition": "cf_c", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_d": {"condition": "cf_d", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_e": {"condition": "cf_e", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
    "cf_f": {"condition": "cf_f", "run_mode": "formal", "repetitions": 1, "max_turns": 1},
}


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run(cmd: list[str], *, timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(cmd, 124, stdout, f"{stderr}\nTimeoutExpired after {timeout}s")


def ssh(host: str, command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return run(["ssh", host, command], timeout=timeout)


def scp(src: str, dst: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return run(["scp", src, dst], timeout=timeout)


def record(name: str, proc: subprocess.CompletedProcess[str], ok: bool | None = None) -> StepResult:
    return StepResult(
        name=name,
        ok=(proc.returncode == 0 if ok is None else ok),
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def q(value: str) -> str:
    return shlex.quote(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--repetitions", type=int, default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--jump-host", default=DEFAULT_JUMP_HOST)
    parser.add_argument("--harness-host", default=DEFAULT_HARNESS_HOST)
    parser.add_argument("--harness-ip", default=DEFAULT_HARNESS_IP)
    parser.add_argument("--harness-home", default=DEFAULT_HARNESS_HOME)
    parser.add_argument("--stage-runner", default=DEFAULT_STAGE_RUNNER)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--scratch-dir", type=Path, default=SCRATCH_DIR)
    parser.add_argument("--pre-theta-path", type=Path, default=PREFORMAL_THETA_PATH)
    parser.add_argument("--pre-calibration-path", type=Path, default=PREFORMAL_CALIBRATION_PATH)
    parser.add_argument("--entropy-percentile", type=float, default=0.70)
    parser.add_argument("--trigger-percentile", type=float, default=0.95)
    parser.add_argument("--run-id-prefix", default=None)
    parser.add_argument("--keep-temp-harness", action="store_true")
    parser.add_argument(
        "--dry-plan",
        action="store_true",
        help="Write only the plan MD without starting Harness or sending turns.",
    )
    return parser.parse_args()


def remote_temp_config_command(
    harness_home: str,
    port: int,
    remote_calibration_path: str | None,
) -> tuple[str, str, str]:
    temp_config = f"/tmp/lacp_preformal_node_config_{port}.json"
    jsonl_dir = f"{harness_home}/logs/preformal_runs"
    code = r"""
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
jsonl_dir = sys.argv[3]
calibration_path = sys.argv[4]
data = json.loads(source.read_text(encoding="utf-8"))
data.setdefault("logging", {}).setdefault("db", {})["enabled"] = False
data["logging"]["jsonl_fallback_dir"] = jsonl_dir
if calibration_path:
    calibration = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
    turns = calibration.get("non_trigger_eligible_turns", [])
    if turns:
        data.setdefault("counterfactual", {}).setdefault("cf_f", {})["non_trigger_eligible_turns"] = turns
        data.setdefault("counterfactual", {}).setdefault("cf_f", {}).setdefault("injection_turns", [])
target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
"""
    command = " ".join(
        [
            "mkdir",
            "-p",
            q(jsonl_dir),
            "&&",
            "python3",
            "-c",
            q(code),
            q(f"{harness_home}/config/node_config.yaml"),
            q(temp_config),
            q(jsonl_dir),
            q(remote_calibration_path or ""),
        ]
    )
    return command, temp_config, jsonl_dir


def start_temp_harness(args: argparse.Namespace) -> list[StepResult]:
    results: list[StepResult] = []
    remote_theta = None
    remote_calibration = None
    if args.stage in {"run_b", "cf_a", "cf_b", "cf_c", "cf_d", "cf_e", "cf_f"}:
        if not args.pre_theta_path.exists():
            return [
                StepResult(
                    "prepare:pre_theta_required",
                    False,
                    2,
                    "",
                    f"missing pre-theta config: {args.pre_theta_path}. Run pre-formal CR2 first.",
                )
            ]
        remote_theta = f"/tmp/lacp_preformal_theta_config_{args.port}.json"
        proc = scp(str(args.pre_theta_path), f"{args.harness_host}:{remote_theta}", timeout=30)
        results.append(record("prepare:upload_pre_theta", proc))
        if args.pre_calibration_path.exists():
            remote_calibration = f"/tmp/lacp_preformal_calibration_{args.port}.json"
            proc = scp(str(args.pre_calibration_path), f"{args.harness_host}:{remote_calibration}", timeout=30)
            results.append(record("prepare:upload_pre_calibration", proc))
    prep_cmd, temp_config, _ = remote_temp_config_command(args.harness_home, args.port, remote_calibration)
    results.append(record("prepare:db_disabled_config", ssh(args.harness_host, prep_cmd, timeout=30)))

    kill_cmd = f"fuser -k {args.port}/tcp >/dev/null 2>&1 || true"
    results.append(record("prepare:clear_temp_port", ssh(args.harness_host, kill_cmd, timeout=20), ok=True))

    start_cmd = (
        f"cd {q(args.harness_home)} && "
        "( "
        f"nohup /home/morophi/harness_venv/bin/python {q(args.harness_home + '/harness_server.py')} "
        f"--config {q(temp_config)} "
        f"--sc-policy {q(args.harness_home + '/config/sc_policy.yaml')} "
        f"--theta {q(remote_theta or args.harness_home + '/config/theta_config.json')} "
        f"--host 0.0.0.0 --port {args.port} "
        f"> {q(args.harness_home + f'/logs/preformal_harness_{args.port}.out')} 2>&1 < /dev/null & "
        ")"
    )
    results.append(record("prepare:start_temp_harness", ssh(args.harness_host, start_cmd, timeout=20)))
    time.sleep(2)

    probe = f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{args.port}/turn"
    proc = ssh(args.harness_host, probe, timeout=20)
    results.append(record("verify:temp_harness_route", proc, ok=proc.returncode == 0 and proc.stdout.strip() == "405"))
    return results


def stop_temp_harness(args: argparse.Namespace) -> StepResult:
    proc = ssh(args.harness_host, f"fuser -k {args.port}/tcp >/dev/null 2>&1 || true", timeout=20)
    return record("cleanup:stop_temp_harness", proc, ok=True)


def dblog_count(args: argparse.Namespace, run_ids: list[str]) -> StepResult:
    if not run_ids:
        return StepResult("verify:dblog_zero_rows", False, 1, "", "no run_ids to check")
    quoted_ids = ", ".join("'" + run_id.replace("'", "''") + "'" for run_id in run_ids)
    sql = (
        "SELECT COUNT(*) FROM experiment_runs WHERE run_id IN ({ids});"
    ).format(ids=quoted_ids)
    cmd = (
        f"set -a; . {q(args.harness_home + '/.env.local')}; set +a; "
        f"mysql -h10.1.1.130 -umorophi --password=\"$LACP_DB_PASSWORD\" lacp_db -N -B -e {q(sql)}"
    )
    proc = ssh(args.harness_host, cmd, timeout=40)
    ok = proc.returncode == 0 and proc.stdout.strip() == "0"
    return record("verify:dblog_zero_rows", proc, ok=ok)


def execute_stage(args: argparse.Namespace) -> StepResult:
    spec = STAGES[args.stage]
    repetitions = args.repetitions if args.repetitions is not None else spec["repetitions"]
    max_turns = args.max_turns if args.max_turns is not None else spec["max_turns"]
    prefix = args.run_id_prefix or f"preformal_{args.stage}"
    command = (
        f"cd /home/morophi/agent && "
        f"python3 {q(args.stage_runner)} "
        f"--stage {q(args.stage)} "
        f"--scenario {q(args.scenario)} "
        f"--harness-url {q(f'http://{args.harness_ip}:{args.port}')} "
        f"--run-id-prefix {q(prefix)} "
        f"--repetitions {int(repetitions)} "
        f"--max-turns {int(max_turns)} "
        "--skip-db-check "
        "--skip-theta-freeze"
    )
    timeout = max(300, int(repetitions) * int(max_turns) * 240)
    return record("execute:stage_runner_db_disabled", ssh(args.jump_host, command, timeout=timeout))


def extract_run_ids(stdout: str) -> list[str]:
    return re.findall(r"stage_run_start run_id=([A-Za-z0-9_.:-]+)", stdout)


def fetch_jsonl(args: argparse.Namespace, run_ids: list[str]) -> tuple[list[StepResult], list[Path]]:
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    results: list[StepResult] = []
    local_paths: list[Path] = []
    for run_id in run_ids:
        local_path = args.scratch_dir / f"{run_id}.jsonl"
        remote_path = f"{args.harness_host}:{args.harness_home}/logs/preformal_runs/{run_id}.jsonl"
        proc = scp(remote_path, str(local_path), timeout=60)
        results.append(record(f"fetch:jsonl:{run_id}", proc))
        if proc.returncode == 0:
            local_paths.append(local_path)
    return results, local_paths


def summarize_jsonl(paths: list[Path]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "runs": {},
        "total_rows": 0,
        "nodes": Counter(),
        "conditions": Counter(),
        "run_modes": Counter(),
        "rag_injected": Counter(),
        "sc_policy_applied": Counter(),
        "quality_ready": Counter(),
        "analysis_eligible": Counter(),
        "errors": [],
    }
    for path in paths:
        run = {
            "rows": 0,
            "turns": set(),
            "nodes": Counter(),
            "rag_injected": Counter(),
            "sc_policy_applied": Counter(),
            "quality_ready": Counter(),
            "analysis_eligible": Counter(),
        }
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    summary["errors"].append(f"{path.name}:{line_no}: {exc}")
                    continue
                run["rows"] += 1
                summary["total_rows"] += 1
                run["turns"].add(row.get("turn_no"))
                node = str(row.get("node"))
                run["nodes"][node] += 1
                summary["nodes"][node] += 1
                summary["conditions"][str(row.get("condition"))] += 1
                summary["run_modes"][str(row.get("run_mode"))] += 1
                for key, counter_name in (
                    ("rag_injected", "rag_injected"),
                    ("sc_policy_applied", "sc_policy_applied"),
                    ("generation_quality_ready", "quality_ready"),
                    ("analysis_eligible", "analysis_eligible"),
                ):
                    value = str(bool(row.get(key)))
                    run[counter_name][value] += 1
                    summary[counter_name][value] += 1
        run["turns"] = sorted(turn for turn in run["turns"] if turn is not None)
        summary["runs"][path.stem] = stringify_counters(run)
    return stringify_counters(summary)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile from an empty value set")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def build_preformal_theta(
    paths: list[Path],
    run_ids: list[str],
    entropy_percentile: float,
    trigger_percentile: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows_by_turn: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    entropy_values: list[float] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                run_id = str(row.get("run_id"))
                turn_no = int(row.get("turn_no"))
                node = str(row.get("node"))
                metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
                status = row.get("metric_status") if isinstance(row.get("metric_status"), dict) else {}
                for item in status.get("lms_token_entropies", []):
                    if isinstance(item, (int, float)):
                        entropy_values.append(float(item))
                if row.get("analysis_eligible") is False or row.get("exclude_from_causal_trigger") is True:
                    continue
                rows_by_turn[(run_id, turn_no)][node] = metrics

    values = {"d_lms_abs": [], "d_cds_abs": [], "d_ma_abs": []}
    non_trigger_eligible_turns: list[int] = []
    for (_run_id, turn_no), nodes in sorted(rows_by_turn.items()):
        c = nodes.get("C")
        if not c:
            continue
        turn_trigger_eligible = False
        for node in ("A", "B"):
            x = nodes.get(node)
            if not x:
                continue
            x_lms, c_lms = _num(x.get("lms_value")), _num(c.get("lms_value"))
            x_cds, c_cds = _num(x.get("cds")), _num(c.get("cds"))
            x_ma, c_ma = _num(x.get("ma_assert")), _num(c.get("ma_assert"))
            d_lms = None if x_lms is None or c_lms is None else x_lms - c_lms
            d_cds = None if x_cds is None or c_cds is None else c_cds - x_cds
            d_ma = None if x_ma is None or c_ma is None else x_ma - c_ma
            if d_lms is not None:
                values["d_lms_abs"].append(abs(d_lms))
            if d_cds is not None:
                values["d_cds_abs"].append(abs(d_cds))
            if d_ma is not None:
                values["d_ma_abs"].append(abs(d_ma))
            if any(value is not None and value > 0.0 for value in (d_lms, d_cds, d_ma)):
                turn_trigger_eligible = True
        if not turn_trigger_eligible:
            non_trigger_eligible_turns.append(turn_no)

    missing = {key: len(items) for key, items in values.items() if not items}
    if missing or not entropy_values:
        raise ValueError(
            "insufficient CR2 pre-formal metrics for theta calibration: "
            f"missing={missing}, entropy_count={len(entropy_values)}"
        )

    calibration = {
        "source": "preformal_cr2_jsonl",
        "run_ids": run_ids,
        "metric_counts": {key: len(items) for key, items in values.items()},
        "entropy_token_count": len(entropy_values),
        "non_trigger_eligible_turns": sorted(set(non_trigger_eligible_turns)),
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": file_sha256(Path(__file__)),
    }
    theta = {
        "theta_entropy": percentile(entropy_values, entropy_percentile),
        "theta_lms": percentile(values["d_lms_abs"], trigger_percentile),
        "theta_cds": percentile(values["d_cds_abs"], trigger_percentile),
        "theta_ma": percentile(values["d_ma_abs"], trigger_percentile),
        "source": "PREFORMAL_CR2_JSONL",
        "locked": True,
        "preformal_only": True,
        "cr2_run_id": run_ids,
        "percentile_rule": {
            "theta_entropy": entropy_percentile,
            "theta_lms": trigger_percentile,
            "theta_cds": trigger_percentile,
            "theta_ma": trigger_percentile,
        },
        "calibration": calibration,
        "notes": "Pre-formal rehearsal theta. Do not use as official formal evidence.",
    }
    return theta, calibration


def write_preformal_theta_outputs(
    args: argparse.Namespace,
    run_ids: list[str],
    jsonl_paths: list[Path],
    results: list[StepResult],
) -> None:
    if args.stage != "cr2" or not jsonl_paths:
        return
    try:
        theta, calibration = build_preformal_theta(
            jsonl_paths,
            run_ids,
            args.entropy_percentile,
            args.trigger_percentile,
        )
        args.pre_theta_path.parent.mkdir(parents=True, exist_ok=True)
        args.pre_theta_path.write_text(
            json.dumps(theta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.pre_calibration_path.write_text(
            json.dumps(calibration, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        results.append(
            StepResult(
                "calibrate:preformal_theta",
                True,
                0,
                f"theta={args.pre_theta_path}\ncalibration={args.pre_calibration_path}",
                "",
            )
        )
    except Exception as exc:
        results.append(StepResult("calibrate:preformal_theta", False, 1, "", str(exc)))


def stringify_counters(value: Any) -> Any:
    if isinstance(value, Counter):
        return dict(sorted(value.items()))
    if isinstance(value, defaultdict):
        return dict(value)
    if isinstance(value, dict):
        return {key: stringify_counters(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stringify_counters(item) for item in value]
    return value


def markdown_table(results: list[StepResult]) -> str:
    rows = ["| Step | Status | Return code |", "| --- | --- | --- |"]
    for result in results:
        rows.append(f"| `{result.name}` | {'PASS' if result.ok else 'BLOCKED'} | {result.returncode} |")
    return "\n".join(rows)


def fenced(label: str, content: str) -> str:
    content = content.strip()
    if not content:
        content = "(empty)"
    return f"```{label}\n{content}\n```"


def write_md(
    args: argparse.Namespace,
    run_ids: list[str],
    results: list[StepResult],
    jsonl_summary: dict[str, Any] | None,
) -> Path:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = args.output_dir / f"{args.stage}_{stamp}_preformal.md"
    spec = STAGES[args.stage]
    status = "PASS" if all(result.ok for result in results) else "BLOCKED"
    lines = [
        f"# Pre-Formal Stage Evidence: {args.stage}",
        "",
        f"- Status: `{status}`",
        f"- Created UTC: `{stamp}`",
        f"- Stage: `{args.stage}`",
        f"- Condition: `{spec['condition']}`",
        f"- Run mode: `{spec['run_mode']}`",
        f"- DB write policy: `disabled via temporary Harness config`",
        f"- Evidence target: `Markdown only; JSONL scratch ignored by Git`",
        f"- Harness URL used: `http://{args.harness_ip}:{args.port}`",
        f"- Scenario: `{args.scenario}`",
        f"- Run IDs: `{', '.join(run_ids) if run_ids else '(none)'}`",
        "",
        "## Gate Results",
        "",
        markdown_table(results),
        "",
        "## JSONL Summary",
        "",
        fenced("json", json.dumps(jsonl_summary or {}, ensure_ascii=False, indent=2, sort_keys=True)),
        "",
        "## Command Outputs",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                "",
                f"- Status: `{'PASS' if result.ok else 'BLOCKED'}`",
                f"- Return code: `{result.returncode}`",
                "",
                "stdout:",
                fenced("text", result.stdout),
                "",
                "stderr:",
                fenced("text", result.stderr),
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def write_dry_plan(args: argparse.Namespace) -> int:
    spec = STAGES[args.stage]
    result = StepResult(
        "plan:dry",
        True,
        0,
        json.dumps(
            {
                "stage": args.stage,
                "condition": spec["condition"],
                "run_mode": spec["run_mode"],
                "default_repetitions": spec["repetitions"],
                "default_max_turns": spec["max_turns"],
                "db_write_policy": "disabled via temporary Harness config",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        "",
    )
    path = write_md(args, [], [result], None)
    print(path)
    return 0


def main() -> int:
    args = parse_args()
    if args.dry_plan:
        return write_dry_plan(args)

    results: list[StepResult] = []
    run_ids: list[str] = []
    jsonl_summary: dict[str, Any] | None = None
    try:
        results.extend(start_temp_harness(args))
        if all(result.ok for result in results):
            execute_result = execute_stage(args)
            results.append(execute_result)
            run_ids = extract_run_ids(execute_result.stdout)
        if run_ids:
            fetch_results, jsonl_paths = fetch_jsonl(args, run_ids)
            results.extend(fetch_results)
            jsonl_summary = summarize_jsonl(jsonl_paths)
            write_preformal_theta_outputs(args, run_ids, jsonl_paths, results)
            results.append(dblog_count(args, run_ids))
    finally:
        if not args.keep_temp_harness:
            results.append(stop_temp_harness(args))
    md_path = write_md(args, run_ids, results, jsonl_summary)
    print(md_path)
    return 0 if all(result.ok for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
