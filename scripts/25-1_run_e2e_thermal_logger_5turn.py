#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run a 5-turn thermal-only inference probe.

This script intentionally bypasses Agent, Harness, RAG, dblog, JSONL fetch, and
validation. It samples temperatures every second while sending direct local
Ollama requests to inference1/2/3, then keeps sampling for a cooldown window.
The only persisted artifact is the thermal JSONL file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path("validation_queries/e2e_runs")
DEFAULT_NODES = ("inference1", "inference2", "inference3")
DEFAULT_MODEL = "qwen3-nothink:latest"


def load_thermal_logger():
    module_path = Path(__file__).with_name("25_run_e2e_rough_smoke.py")
    spec = importlib.util.spec_from_file_location("lacp_e2e_rough_smoke", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ThermalLogger


def ssh(host: str, remote_command: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_command],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def ollama_probe_command(model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 96, "temperature": 0.2},
        },
        ensure_ascii=False,
    )
    return (
        "curl -sS --max-time 180 "
        "-H 'Content-Type: application/json' "
        "-d "
        + shlex.quote(payload)
        + " http://127.0.0.1:11434/api/generate >/dev/null"
    )


def run_node_turn(node: str, turn: int, model: str, timeout_sec: int) -> dict:
    prompt = (
        "Thermal-only LACP inference probe. "
        f"Node={node}. Turn={turn}. "
        "Produce a concise Korean paragraph about retrieval verification."
    )
    started = time.monotonic()
    proc = ssh(node, ollama_probe_command(model, prompt), timeout=timeout_sec)
    return {
        "node": node,
        "turn": turn,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "stderr": proc.stderr.strip(),
    }


def run_direct_inference_load(nodes: tuple[str, ...], turns: int, model: str, timeout_sec: int) -> list[dict]:
    results: list[dict] = []
    for turn in range(1, turns + 1):
        with ThreadPoolExecutor(max_workers=len(nodes)) as executor:
            futures = [executor.submit(run_node_turn, node, turn, model, timeout_sec) for node in nodes]
            for future in as_completed(futures):
                results.append(future.result())
    return sorted(results, key=lambda row: (row["turn"], row["node"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="Defaults to thermal_only_5turn_YYYYmmddTHHMMSSZ.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--nodes", nargs="+", default=list(DEFAULT_NODES))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thermal-interval-sec", type=float, default=1.0)
    parser.add_argument("--thermal-cooldown-sec", type=float, default=10.0)
    parser.add_argument("--node-timeout-sec", type=int, default=240)
    args = parser.parse_args()

    if args.turns < 1 or args.turns > 30:
        raise SystemExit("--turns must be between 1 and 30")

    run_id = args.run_id or time.strftime("thermal_only_5turn_%Y%m%dT%H%M%SZ", time.gmtime())
    nodes = tuple(args.nodes)
    ThermalLogger = load_thermal_logger()
    thermal_logger = ThermalLogger(
        run_id,
        args.output_dir,
        args.thermal_interval_sec,
        nodes=nodes,
        cooldown_sec=args.thermal_cooldown_sec,
    )

    started = time.monotonic()
    thermal_logger.start()
    try:
        inference_results = run_direct_inference_load(nodes, args.turns, args.model, args.node_timeout_sec)
    finally:
        thermal_logger.stop()

    failed = [row for row in inference_results if not row["ok"]]
    payload = {
        "run_id": run_id,
        "mode": "thermal_only_direct_inference",
        "nodes": nodes,
        "turns": args.turns,
        "model": args.model,
        "thermal_log": str(thermal_logger.path),
        "thermal_interval_sec": args.thermal_interval_sec,
        "thermal_cooldown_sec": args.thermal_cooldown_sec,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "inference_requests": len(inference_results),
        "inference_failures": failed,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
