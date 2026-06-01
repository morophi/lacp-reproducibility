#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""DB-free readiness gate for inference nodes before LACP runs.

The check deliberately avoids Harness /turn and database writes. It verifies
that each inference node can serve the same OpenAI-compatible logprobs path used
by Harness, then records a local JSON evidence file.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("validation_queries/preflight")
DEFAULT_SCENARIO = "/home/morophi/agent/scenario/lacp_scenario_base_v2.json"
NODES = {
    "A": {"ssh": "inference1", "host": "10.1.1.10"},
    "B": {"ssh": "inference2", "host": "10.1.1.20"},
    "C": {"ssh": "inference3", "host": "10.1.1.30"},
}


@dataclass
class CommandResult:
    name: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def ssh(host: str, remote_command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_command], timeout=timeout)


def compact_result(name: str, proc: subprocess.CompletedProcess[str], ok: bool | None = None) -> CommandResult:
    return CommandResult(
        name=name,
        ok=(proc.returncode == 0 if ok is None else ok),
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def remote_status_command() -> str:
    return (
        "main_pid=$(systemctl show -p MainPID --value ollama); "
        "echo '__service__'; "
        "systemctl is-active ollama; "
        "echo '__main_pid__'; "
        "printf '%s\\n' \"$main_pid\"; "
        "echo '__ollama_ps__'; "
        "ollama ps 2>&1; "
        "echo '__processes__'; "
        "ps -eo pid,ppid,stat,etimes,pcpu,pmem,cmd | grep -E 'ollama|runner' | grep -v grep; "
        "echo '__recent_errors__'; "
        "journalctl -u ollama --since '-10 minutes' --no-pager "
        "| grep -F \"ollama[$main_pid]\" "
        "| grep -E 'aborting completion|\\| 500 \\|' "
        "| tail -n 20 || true"
    )


def parse_runner_health(stdout: str, cpu_threshold: float, min_busy_seconds: int) -> dict[str, Any]:
    section = ""
    runners: list[dict[str, Any]] = []
    service_active = False
    recent_errors: list[str] = []

    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        if line.startswith("__") and line.endswith("__"):
            section = line
            continue
        if section == "__service__" and line == "active":
            service_active = True
        elif section == "__processes__" and "runner --ollama-engine" in line:
            parts = line.split(None, 6)
            if len(parts) >= 7:
                try:
                    etimes = int(parts[3])
                    pcpu = float(parts[4])
                except ValueError:
                    etimes = -1
                    pcpu = -1.0
                runners.append(
                    {
                        "pid": parts[0],
                        "stat": parts[2],
                        "etimes": etimes,
                        "pcpu": pcpu,
                        "pmem": parts[5],
                        "cmd": parts[6],
                    }
                )
        elif section == "__recent_errors__" and line:
            recent_errors.append(line)

    busy_runners = [
        runner
        for runner in runners
        if runner["pcpu"] >= cpu_threshold and runner["etimes"] >= min_busy_seconds
    ]
    return {
        "service_active": service_active,
        "runners": runners,
        "busy_runners": busy_runners,
        "recent_errors": recent_errors,
        "ok": service_active and not busy_runners and not recent_errors,
    }


def build_probe_payload(max_tokens: int, long_prompt_chars: int) -> dict[str, Any]:
    if long_prompt_chars > 0:
        prompt = (
            "Direct inference readiness probe. "
            "This request mirrors Harness OpenAI-compatible logprobs execution. "
            + ("LACP readiness context. " * 500)
        )[:long_prompt_chars]
    else:
        prompt = "Say ready in Korean."

    return {
        "model": "qwen3-nothink",
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": max_tokens,
        "logprobs": True,
        "top_logprobs": 5,
        "think": False,
    }


def harness_probe_command(max_tokens: int, long_prompt_chars: int, timeout_s: float) -> str:
    payload = build_probe_payload(max_tokens=max_tokens, long_prompt_chars=long_prompt_chars)
    code = r"""
import json, sys, time, urllib.error, urllib.request

nodes = json.loads(sys.argv[1])
payload = json.loads(sys.argv[2])
timeout_s = float(sys.argv[3])

print(json.dumps({
    "event": "probe_start",
    "max_tokens": payload["max_tokens"],
    "timeout_s": timeout_s,
    "message_chars": sum(len(m["content"]) for m in payload["messages"]),
}, ensure_ascii=False))

for node, meta in nodes.items():
    host = meta["host"]
    url = f"http://{host}:11434/v1/chat/completions"
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            raw = json.loads(body.decode("utf-8"))
            choices = raw.get("choices") or [{}]
            logprobs = (choices[0].get("logprobs") or {}).get("content") or []
            print(json.dumps({
                "node": node,
                "host": host,
                "ok": resp.status == 200 and len(logprobs) > 0,
                "status": resp.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "logprobs_len": len(logprobs),
                "first_top_count": len((logprobs[0].get("top_logprobs") if logprobs else []) or []),
            }, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
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
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
        }, ensure_ascii=False))
"""
    return " ".join(
        [
            "/home/morophi/harness_venv/bin/python3",
            "-c",
            shlex.quote(code),
            shlex.quote(json.dumps(NODES)),
            shlex.quote(json.dumps(payload)),
            shlex.quote(str(timeout_s)),
        ]
    )


def harness_unload_command(timeout_s: float) -> str:
    payload = {"model": "qwen3-nothink", "prompt": "", "stream": False, "keep_alive": 0}
    code = r"""
import json, sys, time, urllib.error, urllib.request

nodes = json.loads(sys.argv[1])
payload = json.loads(sys.argv[2])
timeout_s = float(sys.argv[3])

print(json.dumps({"event": "unload_start", "timeout_s": timeout_s}, ensure_ascii=False))

for node, meta in nodes.items():
    host = meta["host"]
    url = f"http://{host}:11434/api/generate"
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            print(json.dumps({
                "node": node,
                "host": host,
                "ok": resp.status == 200,
                "status": resp.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "bytes": len(body),
                "body_prefix": body.decode("utf-8", errors="replace")[:200],
            }, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
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
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
        }, ensure_ascii=False))
"""
    return " ".join(
        [
            "/home/morophi/harness_venv/bin/python3",
            "-c",
            shlex.quote(code),
            shlex.quote(json.dumps(NODES)),
            shlex.quote(json.dumps(payload)),
            shlex.quote(str(timeout_s)),
        ]
    )


def load_first_turn_payload(scenario: str) -> dict[str, Any]:
    code = r"""
import json, sys
from scenario_loader import load_scenario

scenario = load_scenario(sys.argv[1])
turn = scenario["turns"][0]
utterance = turn.get("utterance") or turn.get("text") or turn.get("user") or turn.get("content")
print(json.dumps({
    "scenario_id": scenario["scenario_id"],
    "scenario_hash": scenario["scenario_hash"],
    "turn_no": int(turn.get("turn_no") or turn.get("turn") or 1),
    "utterance": utterance,
}, ensure_ascii=False))
"""
    proc = ssh(
        "jump",
        "cd /home/morophi/agent && python3 -c "
        + shlex.quote(code)
        + " "
        + shlex.quote(scenario),
        timeout=40,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to load first scenario turn: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def actual_first_turn_probe_command(first_turn: dict[str, Any], timeout_s: float) -> str:
    code = r"""
import asyncio, json, sys, time, urllib.error, urllib.request

sys.path.insert(0, "/home/morophi/harness")

from config_utils import load_config
from prompt_builder import build_messages
from rag_client import RAGClient
from sc_policy import SCPolicyEngine
from trigger_controller import TriggerController

nodes = json.loads(sys.argv[1])
first_turn = json.loads(sys.argv[2])
timeout_s = float(sys.argv[3])

config = load_config("/home/morophi/harness/config/node_config.yaml")
sc_engine = SCPolicyEngine(
    "/home/morophi/harness/config/sc_policy.yaml",
    "/home/morophi/harness/config/theta_config.json",
)
trigger_controller = TriggerController(sc_engine, config)
trigger = trigger_controller.evaluate_shared_trigger(
    previous_metrics={},
    turn_no=1,
    condition="run_b",
    run_mode="smoke",
)

rag_chunks = []
if trigger["should_inject_rag"]:
    rag_cfg = config["rag"]
    mode_cfg = config.get("run_modes", {}).get("smoke", {})
    rag_client = RAGClient(
        host=rag_cfg["host"],
        port=int(rag_cfg["port"]),
        collection=rag_cfg["collection"],
        embedding_model=rag_cfg["embedding_model"],
    )
    top_k = int(mode_cfg.get("rag_top_k", rag_cfg.get("top_k", 5)))
    rag_chunks = asyncio.run(rag_client.retrieve(first_turn["utterance"], top_k=top_k))

sc_policy_block = sc_engine.build_policy_block() if trigger["apply_sc_to_a"] else None
histories = {"A": [], "B": [], "C": []}
built = {
    "A": build_messages("A", first_turn["utterance"], histories["A"], rag_chunks, sc_policy_block, sc_engine.policy_hash),
    "B": build_messages("B", first_turn["utterance"], histories["B"], rag_chunks, None, None),
    "C": build_messages("C", first_turn["utterance"], histories["C"], None, None, None),
}
model_cfg = config["model"]
mode_cfg = config.get("run_modes", {}).get("smoke", {})
num_predict = int(mode_cfg.get("num_predict", model_cfg.get("num_predict", 512)))

print(json.dumps({
    "event": "actual_first_turn_probe_start",
    "scenario_id": first_turn["scenario_id"],
    "scenario_hash": first_turn["scenario_hash"],
    "turn_no": first_turn["turn_no"],
    "trigger": trigger,
    "rag_returned_count": len(rag_chunks),
    "prompt_metadata": {node: value["prompt_metadata"] for node, value in built.items()},
    "timeout_s": timeout_s,
}, ensure_ascii=False))

for node, meta in nodes.items():
    host = meta["host"]
    url = f"http://{host}:11434/v1/chat/completions"
    payload = {
        "model": model_cfg.get("name", "qwen3-nothink"),
        "messages": built[node]["messages"],
        "temperature": float(model_cfg.get("temperature", 0.0)),
        "seed": int(model_cfg.get("seed", 42)),
        "max_tokens": num_predict,
        "logprobs": bool(model_cfg.get("request_logprobs", False)),
        "top_logprobs": int(model_cfg.get("top_logprobs", 5)),
        "think": bool(model_cfg.get("thinking", False)),
    }
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            raw = json.loads(body.decode("utf-8"))
            choices = raw.get("choices") or [{}]
            logprobs = (choices[0].get("logprobs") or {}).get("content") or []
            text = ((choices[0].get("message") or {}).get("content") or "")[:160]
            print(json.dumps({
                "node": node,
                "host": host,
                "ok": resp.status == 200 and len(logprobs) > 0,
                "status": resp.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "logprobs_len": len(logprobs),
                "first_top_count": len((logprobs[0].get("top_logprobs") if logprobs else []) or []),
                "prompt_chars": built[node]["prompt_metadata"]["prompt_chars"],
                "message_count": built[node]["prompt_metadata"]["message_count"],
                "rag_injected": built[node]["prompt_metadata"]["rag_injected"],
                "sc_policy_applied": built[node]["prompt_metadata"]["sc_policy_applied"],
                "text_prefix": text,
            }, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "status": exc.code,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": "HTTPError",
            "prompt_chars": built[node]["prompt_metadata"]["prompt_chars"],
            "body_prefix": exc.read().decode("utf-8", errors="replace")[:300],
        }, ensure_ascii=False))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(json.dumps({
            "node": node,
            "host": host,
            "ok": False,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
            "prompt_chars": built[node]["prompt_metadata"]["prompt_chars"],
        }, ensure_ascii=False))
"""
    return " ".join(
        [
            "/home/morophi/harness_venv/bin/python3",
            "-c",
            shlex.quote(code),
            shlex.quote(json.dumps(NODES)),
            shlex.quote(json.dumps(first_turn, ensure_ascii=False)),
            shlex.quote(str(timeout_s)),
        ]
    )


def parse_probe_stdout(stdout: str) -> list[dict[str, Any]]:
    rows = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"ok": False, "error": "JSONDecodeError", "raw": line})
    return rows


def probe_ok(rows: list[dict[str, Any]], max_elapsed_ms: float) -> bool:
    node_rows = [row for row in rows if row.get("node")]
    if len(node_rows) != len(NODES):
        return False
    return all(
        row.get("ok") is True
        and row.get("status") == 200
        and row.get("logprobs_len", 0) > 0
        and row.get("first_top_count") == 5
        and float(row.get("elapsed_ms", max_elapsed_ms + 1)) <= max_elapsed_ms
        for row in node_rows
    )


def unload_ok(rows: list[dict[str, Any]]) -> bool:
    node_rows = [row for row in rows if row.get("node")]
    if len(node_rows) != len(NODES):
        return False
    return all(row.get("ok") is True and row.get("status") == 200 for row in node_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--short-timeout-s", type=float, default=180.0)
    parser.add_argument("--harness-timeout-s", type=float, default=240.0)
    parser.add_argument("--actual-turn-timeout-s", type=float, default=180.0)
    parser.add_argument("--short-max-elapsed-ms", type=float, default=180000.0)
    parser.add_argument("--harness-max-elapsed-ms", type=float, default=240000.0)
    parser.add_argument("--actual-turn-max-elapsed-ms", type=float, default=180000.0)
    parser.add_argument("--runner-cpu-threshold", type=float, default=90.0)
    parser.add_argument("--runner-min-busy-seconds", type=int, default=60)
    parser.add_argument("--harness-long-prompt-chars", type=int, default=4200)
    parser.add_argument(
        "--include-harness-like-probe",
        action="store_true",
        help="Also run the older synthetic long prompt probe. Default readiness uses the actual first turn instead.",
    )
    parser.add_argument("--unload-timeout-s", type=float, default=30.0)
    parser.add_argument("--settle-sec", type=float, default=15.0)
    parser.add_argument(
        "--skip-unload",
        action="store_true",
        help="Leave the model loaded after readiness probes. Not recommended before experiment runs.",
    )
    parser.add_argument("--evidence-name", default=None)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    args = parser.parse_args()

    created_at = now_stamp()
    evidence_name = args.evidence_name or f"inference_readiness_{created_at}.json"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output_dir / evidence_name

    status_before: dict[str, Any] = {}
    for node, meta in NODES.items():
        proc = ssh(meta["ssh"], remote_status_command(), timeout=40)
        health = parse_runner_health(proc.stdout, args.runner_cpu_threshold, args.runner_min_busy_seconds)
        status_before[node] = {
            "ssh_host": meta["ssh"],
            "command": asdict(compact_result(f"status_before:{node}", proc, ok=proc.returncode == 0)),
            "health": health,
        }

    short_proc = ssh(
        "harness",
        harness_probe_command(max_tokens=64, long_prompt_chars=0, timeout_s=args.short_timeout_s),
        timeout=int(args.short_timeout_s * len(NODES) + 60),
    )
    short_rows = parse_probe_stdout(short_proc.stdout)

    harness_proc = None
    harness_rows: list[dict[str, Any]] = []
    if args.include_harness_like_probe:
        harness_proc = ssh(
            "harness",
            harness_probe_command(
                max_tokens=512,
                long_prompt_chars=args.harness_long_prompt_chars,
                timeout_s=args.harness_timeout_s,
            ),
            timeout=int(args.harness_timeout_s * len(NODES) + 60),
        )
        harness_rows = parse_probe_stdout(harness_proc.stdout)

    first_turn = load_first_turn_payload(args.scenario)
    actual_proc = ssh(
        "harness",
        actual_first_turn_probe_command(first_turn, timeout_s=args.actual_turn_timeout_s),
        timeout=int(args.actual_turn_timeout_s * len(NODES) + 180),
    )
    actual_rows = parse_probe_stdout(actual_proc.stdout)

    unload_proc = None
    unload_rows: list[dict[str, Any]] = []
    if not args.skip_unload:
        unload_proc = ssh(
            "harness",
            harness_unload_command(timeout_s=args.unload_timeout_s),
            timeout=int(args.unload_timeout_s * len(NODES) + 60),
        )
        unload_rows = parse_probe_stdout(unload_proc.stdout)

    if args.settle_sec > 0:
        time.sleep(args.settle_sec)

    status_after: dict[str, Any] = {}
    for node, meta in NODES.items():
        proc = ssh(meta["ssh"], remote_status_command(), timeout=40)
        health = parse_runner_health(proc.stdout, args.runner_cpu_threshold, args.runner_min_busy_seconds)
        status_after[node] = {
            "ssh_host": meta["ssh"],
            "command": asdict(compact_result(f"status_after:{node}", proc, ok=proc.returncode == 0)),
            "health": health,
        }

    before_ok = all(item["command"]["ok"] and item["health"]["ok"] for item in status_before.values())
    short_ok = short_proc.returncode == 0 and probe_ok(short_rows, args.short_max_elapsed_ms)
    harness_ok = (
        True
        if not args.include_harness_like_probe
        else harness_proc is not None and harness_proc.returncode == 0 and probe_ok(harness_rows, args.harness_max_elapsed_ms)
    )
    actual_ok = actual_proc.returncode == 0 and probe_ok(actual_rows, args.actual_turn_max_elapsed_ms)
    unload_phase_ok = (
        True
        if args.skip_unload
        else unload_proc is not None and unload_proc.returncode == 0 and unload_ok(unload_rows)
    )
    after_ok = all(item["command"]["ok"] and item["health"]["ok"] for item in status_after.values())
    all_ok = before_ok and short_ok and harness_ok and actual_ok and unload_phase_ok and after_ok

    evidence = {
        "created_at_utc": created_at,
        "purpose": "DB-free inference readiness gate before LACP run execution",
        "db_writes": False,
        "harness_turn_called": False,
        "direct_inference_probe_called": True,
        "actual_first_turn_payload_built": True,
        "synthetic_harness_like_probe_called": args.include_harness_like_probe,
        "scenario": args.scenario,
        "model_unload_requested": not args.skip_unload,
        "settle_sec": args.settle_sec,
        "run_contamination_scope": (
            "No Harness /turn, no Harness history mutation, no RAG retrieval, no DB writes. "
            "Direct inference probes can warm/load model runners, so this gate unloads the model "
            "with keep_alive=0 and waits before final status checks unless --skip-unload is used."
        ),
        "status": "pass" if all_ok else "blocked",
        "checks": {
            "status_before_ok": before_ok,
            "short_probe_ok": short_ok,
            "harness_like_probe_ok": harness_ok,
            "actual_first_turn_probe_ok": actual_ok,
            "unload_phase_ok": unload_phase_ok,
            "status_after_ok": after_ok,
        },
        "thresholds": {
            "runner_cpu_threshold": args.runner_cpu_threshold,
            "runner_min_busy_seconds": args.runner_min_busy_seconds,
            "short_max_elapsed_ms": args.short_max_elapsed_ms,
            "harness_max_elapsed_ms": args.harness_max_elapsed_ms,
            "actual_turn_max_elapsed_ms": args.actual_turn_max_elapsed_ms,
        },
        "status_before": status_before,
        "short_probe": {
            "command": asdict(compact_result("probe:short_openai_logprobs", short_proc, ok=short_ok)),
            "rows": short_rows,
        },
        "harness_like_probe": {
            "command": (
                None
                if harness_proc is None
                else asdict(compact_result("probe:harness_like_openai_logprobs", harness_proc, ok=harness_ok))
            ),
            "rows": harness_rows,
        },
        "actual_first_turn_probe": {
            "first_turn": first_turn,
            "command": asdict(compact_result("probe:actual_first_turn_openai_logprobs", actual_proc, ok=actual_ok)),
            "rows": actual_rows,
        },
        "unload": {
            "command": (
                None
                if unload_proc is None
                else asdict(compact_result("probe:unload_keep_alive_0", unload_proc, ok=unload_phase_ok))
            ),
            "rows": unload_rows,
        },
        "status_after": status_after,
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": evidence["status"], "evidence": str(evidence_path)}, ensure_ascii=False, indent=2))
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
