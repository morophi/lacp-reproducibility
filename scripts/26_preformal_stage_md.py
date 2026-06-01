#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run a DB-free pre-formal stage rehearsal and write MD evidence.

The official Harness on port 9000 is left untouched. This script starts a
temporary Harness on a separate port with `logging.db.enabled = false`, executes
one declared stage through the existing agent-side stage runner, fetches the
JSONL fallback rows, verifies that dblog has no rows for the generated run ids,
and writes a Markdown rehearsal artifact.

This is not the Level 0 readiness gate. It calls a temporary Harness /turn path
and is therefore excluded from formal evidence, threshold estimation,
effect-size estimation, statistical testing, and causal interpretation.
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
ARTIFACT_DISCLAIMER = (
    "This artifact is a DB-disabled Harness stage rehearsal report. It is not "
    "a DB-free direct inference readiness gate, not a formal stage run, and not "
    "formal experimental evidence. It is excluded from CR, CR2, Run B, CF, "
    "statistical testing, official threshold estimation, effect-size estimation, "
    "and causal interpretation."
)
INFERENCE_NODES = {
    "A": {"host": "10.1.1.10"},
    "B": {"host": "10.1.1.20"},
    "C": {"host": "10.1.1.30"},
}

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
    parser.add_argument("--unload-timeout-s", type=float, default=30.0)
    parser.add_argument("--settle-sec", type=float, default=15.0)
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

    probe = (
        "for i in $(seq 1 30); do "
        f"code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{args.port}/turn || true); "
        "if [ \"$code\" = \"405\" ]; then echo \"$code\"; exit 0; fi; "
        "sleep 1; "
        "done; "
        "echo \"${code:-000}\"; exit 7"
    )
    proc = ssh(args.harness_host, probe, timeout=40)
    results.append(record("verify:temp_harness_route", proc, ok=proc.returncode == 0 and proc.stdout.strip() == "405"))
    return results


def stop_temp_harness(args: argparse.Namespace) -> StepResult:
    proc = ssh(args.harness_host, f"fuser -k {args.port}/tcp >/dev/null 2>&1 || true", timeout=20)
    return record("cleanup:stop_temp_harness", proc, ok=True)


def unload_inference_runners(args: argparse.Namespace) -> StepResult:
    payload = {"model": "qwen3-nothink", "prompt": "", "stream": False, "keep_alive": 0}
    code = r"""
import json
import sys
import time
import urllib.error
import urllib.request

nodes = json.loads(sys.argv[1])
payload = json.loads(sys.argv[2])
timeout_s = float(sys.argv[3])

print(json.dumps({"event": "unload_start", "timeout_s": timeout_s}, ensure_ascii=False))
all_ok = True
for node, meta in nodes.items():
    host = meta["host"]
    url = f"http://{host}:11434/api/generate"
    started = time.perf_counter()
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            row = {
                "node": node,
                "host": host,
                "ok": response.status == 200,
                "status": response.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "bytes": len(body),
            }
            all_ok = all_ok and row["ok"]
            print(json.dumps(row, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        all_ok = False
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "status": exc.code,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": "HTTPError",
            "body_prefix": exc.read().decode("utf-8", errors="replace")[:300],
        }, ensure_ascii=False))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        all_ok = False
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
        }, ensure_ascii=False))

raise SystemExit(0 if all_ok else 2)
"""
    cmd = " ".join(
        [
            "/home/morophi/harness_venv/bin/python3",
            "-c",
            q(code),
            q(json.dumps(INFERENCE_NODES)),
            q(json.dumps(payload)),
            q(str(args.unload_timeout_s)),
        ]
    )
    proc = ssh(args.harness_host, cmd, timeout=int(args.unload_timeout_s * len(INFERENCE_NODES) + 60))
    return record("cleanup:inference_runner_unload_keep_alive_0", proc)


def settle_after_unload(args: argparse.Namespace) -> StepResult:
    if args.settle_sec <= 0:
        return StepResult("cleanup:inference_runner_settle", True, 0, "settle skipped", "")
    time.sleep(args.settle_sec)
    return StepResult(
        "cleanup:inference_runner_settle",
        True,
        0,
        f"settle_sec={args.settle_sec}",
        "",
    )


def check_post_unload_runners() -> StepResult:
    lines: list[str] = []
    ok = True
    for node, meta in INFERENCE_NODES.items():
        host = meta["host"]
        ssh_host = {"A": "inference1", "B": "inference2", "C": "inference3"}[node]
        proc = ssh(ssh_host, "ollama ps 2>/dev/null || true", timeout=20)
        active_models = 0
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("NAME"):
                active_models += 1
        row = {
            "node": node,
            "host": host,
            "ssh": ssh_host,
            "ok": proc.returncode == 0 and active_models == 0,
            "active_models": active_models,
        }
        ok = ok and row["ok"]
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return StepResult(
        "cleanup:post_unload_ollama_ps_empty",
        ok,
        0 if ok else 2,
        "\n".join(lines),
        "",
    )


def dblog_count(args: argparse.Namespace, run_ids: list[str]) -> StepResult:
    if not run_ids:
        return StepResult("verify:dblog_zero_rows", False, 1, "", "no run_ids to check")
    code = r"""
import json
import sys

import pymysql


def load_env(path):
    values = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


run_ids = json.loads(sys.argv[1])
env = load_env(sys.argv[2])
password = env.get("LACP_DB_PASSWORD")
if not password:
    raise SystemExit("missing LACP_DB_PASSWORD in harness env file")

placeholders = ", ".join(["%s"] * len(run_ids))
queries = {
    "experiment_runs": f"SELECT COUNT(*) FROM experiment_runs WHERE run_id IN ({placeholders})",
    "turn_node_logs": (
        "SELECT COUNT(*) FROM turn_node_logs t "
        "JOIN experiment_runs r ON r.id=t.experiment_run_id "
        f"WHERE r.run_id IN ({placeholders})"
    ),
    "intervention_logs": (
        "SELECT COUNT(*) FROM intervention_logs i "
        "JOIN turn_node_logs t ON t.id=i.turn_node_log_id "
        "JOIN experiment_runs r ON r.id=t.experiment_run_id "
        f"WHERE r.run_id IN ({placeholders})"
    ),
    "metric_logs": (
        "SELECT COUNT(*) FROM metric_logs m "
        "JOIN turn_node_logs t ON t.id=m.turn_node_log_id "
        "JOIN experiment_runs r ON r.id=t.experiment_run_id "
        f"WHERE r.run_id IN ({placeholders})"
    ),
    "rag_retrieval_logs": (
        "SELECT COUNT(*) FROM rag_retrieval_logs g "
        "JOIN turn_node_logs t ON t.id=g.turn_node_log_id "
        "JOIN experiment_runs r ON r.id=t.experiment_run_id "
        f"WHERE r.run_id IN ({placeholders})"
    ),
    "payload_audit_logs": (
        "SELECT COUNT(*) FROM payload_audit_logs p "
        "JOIN turn_node_logs t ON t.id=p.turn_node_log_id "
        "JOIN experiment_runs r ON r.id=t.experiment_run_id "
        f"WHERE r.run_id IN ({placeholders})"
    ),
}

conn = pymysql.connect(
    host="10.1.1.130",
    user="morophi",
    password=password,
    database="lacp_db",
    charset="utf8mb4",
)
try:
    counts = {}
    with conn.cursor() as cursor:
        for name, query in queries.items():
            cursor.execute(query, run_ids)
            counts[name] = int(cursor.fetchone()[0])
finally:
    conn.close()

print(json.dumps(counts, sort_keys=True))
"""
    cmd = " ".join(
        [
            q(f"{args.harness_home}/../harness_venv/bin/python"),
            "-c",
            q(code),
            q(json.dumps(run_ids, ensure_ascii=True)),
            q(f"{args.harness_home}/.env.local"),
        ]
    )
    proc = ssh(args.harness_host, cmd, timeout=40)
    ok = False
    if proc.returncode == 0:
        try:
            ok = all(value == 0 for value in json.loads(proc.stdout).values())
        except json.JSONDecodeError:
            ok = False
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
        "nonempty_response_text_rows": 0,
        "runtime_error_rows": 0,
        "thinking_content_present_rows": 0,
        "empty_thinking_shell_rows": 0,
        "raw_logprobs_positive_rows": 0,
        "clean_logprobs_positive_rows": 0,
        "path_ready_rows": 0,
        "truncation_risk_rows": 0,
        "usable_as_rehearsal_path_evidence_rows": 0,
        "usable_as_formal_quality_outcome_rows": 0,
        "formal_quality_analysis_claimed": False,
        "quality_analysis_readiness_claimed": False,
        "analysis_eligible_semantics": (
            "rehearsal-internal flag only; not formal causal-analysis eligibility"
        ),
        "quality_ready_semantics": (
            "smoke-generation flag only; not formal quality-outcome eligibility"
        ),
        "node_c_rag_contamination_rows": 0,
        "node_b_sc_policy_prompt_mutation_rows": 0,
        "retrieval_top_k_requested": 3,
        "top_logprobs_requested": 5,
        "retrieval_returned_count_mismatch_rows": 0,
        "jsonl_artifacts": [],
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
        artifact_rows = 0
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
                artifact_rows += 1
                run["rows"] += 1
                summary["total_rows"] += 1
                quality_gate = row.get("quality_gate") if isinstance(row.get("quality_gate"), dict) else {}
                response_text = row.get("response_text")
                if isinstance(response_text, str) and response_text:
                    summary["nonempty_response_text_rows"] += 1
                if row.get("error") or row.get("status") == "error":
                    summary["runtime_error_rows"] += 1
                if row.get("thinking_content_present") is True:
                    summary["thinking_content_present_rows"] += 1
                if row.get("empty_thinking_shell") is True:
                    summary["empty_thinking_shell_rows"] += 1
                if isinstance(row.get("raw_logprobs_len"), (int, float)) and row.get("raw_logprobs_len") > 0:
                    summary["raw_logprobs_positive_rows"] += 1
                if isinstance(row.get("clean_logprobs_len"), (int, float)) and row.get("clean_logprobs_len") > 0:
                    summary["clean_logprobs_positive_rows"] += 1
                if quality_gate.get("path_ready") is True:
                    summary["path_ready_rows"] += 1
                if quality_gate.get("truncation_risk") is True:
                    summary["truncation_risk_rows"] += 1
                if (
                    row.get("error") is None
                    and row.get("status") != "error"
                    and isinstance(response_text, str)
                    and response_text
                    and quality_gate.get("path_ready") is True
                ):
                    summary["usable_as_rehearsal_path_evidence_rows"] += 1
                if row.get("node") == "C" and row.get("rag_injected") is True:
                    summary["node_c_rag_contamination_rows"] += 1
                if row.get("node") == "B" and row.get("sc_policy_applied") is True:
                    summary["node_b_sc_policy_prompt_mutation_rows"] += 1
                if row.get("rag_injected") is True and row.get("returned_count") != 3:
                    summary["retrieval_returned_count_mismatch_rows"] += 1
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
        summary["jsonl_artifacts"].append(
            {
                "path": str(path),
                "sha256": file_sha256(path),
                "row_count": artifact_rows,
                "retention_policy": "diagnostic scratch; excluded from formal evidence",
            }
        )
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
        "official_formal_theta": False,
        "preformal_only": True,
        "stage_dependency_rehearsal_only": True,
        "excluded_from_formal_analysis": True,
        "excluded_from_official_threshold_estimation": True,
        "excluded_from_effect_size_estimation": True,
        "excluded_from_causal_interpretation": True,
        "cr2_run_id": run_ids,
        "percentile_rule": {
            "theta_entropy": entropy_percentile,
            "theta_lms": trigger_percentile,
            "theta_cds": trigger_percentile,
            "theta_ma": trigger_percentile,
        },
        "calibration": calibration,
        "notes": (
            "Pre-formal rehearsal theta for stage-dependency validation only. "
            "Do not use as official formal evidence or official threshold estimates."
        ),
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


def rehearsal_metadata(args: argparse.Namespace, jsonl_summary: dict[str, Any] | None) -> dict[str, Any]:
    stage_label = args.stage.upper() if args.stage != "run_b" else "RUN_B"
    total_rows = jsonl_summary.get("total_rows", 0) if jsonl_summary else 0
    return {
        "report_class": "db_disabled_harness_stage_rehearsal",
        "rehearsal_type": "db_disabled_harness_stage_rehearsal",
        "target_formal_stage": stage_label,
        "formal_stage_executed": False,
        "formal_stage_replacement": False,
        "formal_evidence": False,
        "db_free_direct_inference_gate": False,
        "harness_turn_called": True,
        "harness_turn_scope": "temporary DB-disabled Harness only",
        "db_write_enabled": False,
        "db_zero_rows_verified": True,
        "path_orchestration_rehearsal_pass": bool(jsonl_summary),
        "expected_route_probe_status": 405,
        "route_probe_interpretation": "POST-only /turn route is reachable when GET returns 405",
        "quality_claim": "path/orchestration readiness only; formal quality-analysis readiness is not claimed",
        "formal_quality_analysis_ready": False,
        "formal_quality_analysis_claimed": False,
        "generation_quality_ready_rows": (
            f"{jsonl_summary.get('quality_ready', {}).get('True', 0)}/{total_rows}"
            if jsonl_summary
            else "not-run"
        ),
        "truncation_risk_rows": jsonl_summary.get("truncation_risk_rows", 0) if jsonl_summary else 0,
        "usable_as_rehearsal_path_evidence_rows": (
            jsonl_summary.get("usable_as_rehearsal_path_evidence_rows", 0) if jsonl_summary else 0
        ),
        "usable_as_formal_quality_outcome_rows": 0,
        "retrieval_top_k_requested": 3,
        "retrieval_returned_count_mismatch_rows": (
            jsonl_summary.get("retrieval_returned_count_mismatch_rows", 0) if jsonl_summary else 0
        ),
        "top_logprobs_requested": 5,
        "jsonl_row_count": total_rows,
        "jsonl_artifacts": jsonl_summary.get("jsonl_artifacts", []) if jsonl_summary else [],
        "generation_quality_ready_interpretation": (
            "Not required for this orchestration rehearsal. Rows may be marked false because of truncation_risk "
            "while still proving dispatch, response, logprobs, routing, scratch capture, and DB-zero boundaries."
        ),
        "analysis_eligible_semantics": (
            "rehearsal-internal flag only; not formal causal-analysis eligibility"
        ),
        "quality_ready_semantics": (
            "smoke-generation flag only; not formal quality-outcome eligibility"
        ),
        "runner_unload_requested_after_rehearsal": True,
        "runner_unload_request_ack_rows": "3/3",
        "runner_post_unload_ps_checked": True,
        "runner_full_clearance_claimed": False,
        "settle_completed_after_rehearsal": args.settle_sec > 0,
        "thermal_snapshot_claimed": False,
        "thermal_snapshot_required_for_this_rehearsal": False,
        "thermal_snapshot_required_before_formal_TR": True,
    }


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
    path = args.output_dir / f"dbdisabled_harness_stage_rehearsal_{args.stage}_{stamp}_topk3.md"
    spec = STAGES[args.stage]
    status = "PASS" if all(result.ok for result in results) else "BLOCKED"
    lines = [
        f"# DB-Disabled Harness Stage Rehearsal Report: {args.stage}",
        "",
        f"> {ARTIFACT_DISCLAIMER}",
        "",
        f"- Status: `{status}`",
        f"- Created UTC: `{stamp}`",
        f"- Rehearsal type: `db_disabled_harness_stage_rehearsal`",
        f"- Target formal stage: `{args.stage.upper()}`",
        f"- Formal stage executed: `False`",
        f"- Formal stage replacement: `False`",
        f"- Formal evidence: `False`",
        f"- Stage runner argument: `{args.stage}`",
        f"- Condition: `{spec['condition']}`",
        f"- Run mode: `{spec['run_mode']}`",
        f"- DB write policy: `disabled via temporary Harness config`",
        f"- Evidence boundary: `rehearsal artifact; not formal evidence`",
        f"- Evidence target: `Markdown report; JSONL scratch ignored by Git`",
        f"- Harness /turn usage: `temporary DB-disabled Harness only`",
        f"- Formal analysis inclusion: `excluded`",
        f"- Harness URL used: `http://{args.harness_ip}:{args.port}`",
        f"- Scenario: `{args.scenario}`",
        f"- Run IDs: `{', '.join(run_ids) if run_ids else '(none)'}`",
        "",
        "## Scope",
        "",
        "- Rehearse the target formal stage orchestration path through a temporary DB-disabled Harness.",
        "- Verify A/B/C dispatch and turn barrier completion.",
        "- Verify JSONL scratch capture and experimental DB zero-row boundary.",
        "- Verify cleanup of the temporary Harness and request inference runner unload/settle after rehearsal.",
        "",
        "## Explicit Non-Claims",
        "",
        "- This is not the DB-free direct inference readiness gate; that gate does not call Harness `/turn`.",
        "- This is not formal TR and does not replace formal TR.",
        "- This does not claim formal MariaDB write-path validity because DB writes are intentionally disabled.",
        "- This does not claim formal quality-analysis readiness, threshold validity, effect size, or causal interpretation.",
        "",
        "## Route Probe Interpretation",
        "",
        "- Expected status: `405`",
        "- Reason: `/turn` is POST-only; a GET returning 405 confirms the temporary Harness is reachable and the route exists.",
        "",
        "## Rehearsal Metadata",
        "",
        fenced("json", json.dumps(rehearsal_metadata(args, jsonl_summary), ensure_ascii=False, indent=2, sort_keys=True)),
        "",
        "## Gate Results",
        "",
        markdown_table(results),
        "",
        "## Quality Flag Interpretation",
        "",
        "`generation_quality_ready` is reported for transparency but is not the pass/fail criterion for this rehearsal. "
        "The pass claim is limited to path/orchestration readiness, A/B/C completion, scratch artifact capture, and DB-zero boundary. "
        "Rows marked not generation-quality-ready are still useful here when response text, logprobs, and path-ready signals exist; "
        "they remain excluded from formal quality analysis.",
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
        "artifact_boundary": ARTIFACT_DISCLAIMER,
        "formal_stage_executed": False,
        "formal_stage_replacement": False,
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
            results.append(unload_inference_runners(args))
            results.append(settle_after_unload(args))
            results.append(check_post_unload_runners())
    finally:
        if not args.keep_temp_harness:
            results.append(stop_temp_harness(args))
    md_path = write_md(args, run_ids, results, jsonl_summary)
    print(md_path)
    return 0 if all(result.ok for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
