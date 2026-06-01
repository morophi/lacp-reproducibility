#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

from scenario_loader import load_scenario


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize(values: List[float]) -> Dict[str, float]:
    return {
        "count": float(len(values)),
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": percentile(values, 0.95),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def post_json(endpoint: str, payload: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=None) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = {"ok": False, "error": text}
        return exc.code, data


def turn_payload(
    scenario: Dict[str, Any],
    turn: Dict[str, Any],
    run_id: str,
    condition: str,
    run_mode: str,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "scenario_id": scenario["scenario_id"],
        "scenario_hash": scenario["scenario_hash"],
        "condition": condition,
        "run_mode": run_mode,
        "turn_no": turn["turn_no"],
        "utterance": turn["utterance"],
        "source_file": scenario["source_file"],
        "sender_node": "agent",
        "metadata": {"speaker": turn.get("speaker")},
    }


def run_case(args: argparse.Namespace, condition: str) -> Dict[str, Any]:
    scenario = load_scenario(args.scenario)
    turns = scenario["turns"][: args.max_turns]
    run_id = f"real_logger_bench_{condition}_{int(time.time() * 1000)}"
    turn_endpoint = args.harness_url.rstrip("/") + "/turn"
    flush_endpoint = args.harness_url.rstrip("/") + f"/flush?timeout={args.flush_timeout}"
    elapsed = []
    responses = []

    for turn in turns:
        payload = turn_payload(scenario, turn, run_id, condition, args.run_mode)
        started = time.perf_counter()
        status, data = post_json(turn_endpoint, payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        elapsed.append(elapsed_ms)
        responses.append(
            {
                "turn_no": payload["turn_no"],
                "status": status,
                "ok": bool(data.get("ok")),
                "elapsed_ms": elapsed_ms,
                "nodes_completed": data.get("nodes_completed", []),
                "error": data.get("error"),
            }
        )
        if status >= 400 or not data.get("ok"):
            raise RuntimeError(f"turn failed: {responses[-1]}")

    flush_started = time.perf_counter()
    status, data = post_json(flush_endpoint, {})
    flush_ms = (time.perf_counter() - flush_started) * 1000
    if status >= 400 or not data.get("ok"):
        raise RuntimeError(f"flush failed: status={status} response={data}")

    return {
        "condition": condition,
        "run_mode": args.run_mode,
        "run_id": run_id,
        "turns": len(turns),
        "latency": summarize(elapsed),
        "flush_ms": flush_ms,
        "responses": responses,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="/home/morophi/agent/scenario/lacp_scenario_base_v2.json")
    parser.add_argument("--harness-url", default="http://10.1.1.110:9000")
    parser.add_argument("--condition", action="append", choices=["cr", "run_b"], default=None)
    parser.add_argument("--run-mode", choices=["smoke", "formal"], default="smoke")
    parser.add_argument("--max-turns", type=int, default=2)
    parser.add_argument("--flush-timeout", type=float, default=30.0)
    args = parser.parse_args()

    conditions = args.condition or ["cr", "run_b"]
    results = [run_case(args, condition) for condition in conditions]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
