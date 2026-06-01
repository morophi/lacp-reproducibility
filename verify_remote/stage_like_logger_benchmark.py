#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_utils import load_config
from experiment_runner import ExperimentRunner
from metrics import MetricComputer


SCENARIO_ID = "stage_like_logger_benchmark"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def logprob_items(text: str) -> List[Dict[str, Any]]:
    return [
        {
            "token": token,
            "bytes": list(token.encode("utf-8")),
            "logprob": -0.1,
            "top_logprobs": [
                {"token": token, "logprob": -0.1},
                {"token": "대안", "logprob": -1.4},
            ],
        }
        for token in text.split()
    ]


class FakeNodeClient:
    model_name = "qwen3-nothink-fake"
    temperature = 0.0
    seed = 42
    thinking = False

    def __init__(self, delay_ms: float):
        self.delay_ms = delay_ms

    async def chat(self, node: str, messages: list[dict], run_mode: str = "formal") -> Dict[str, Any]:
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)
        text = (
            f"{node} 노드 응답입니다. 신청인은 주소지 관할 주민센터에서 상담하고 "
            "필요 서류를 확인해야 합니다."
        )
        raw = {
            "choices": [
                {
                    "message": {"content": text},
                    "finish_reason": "stop",
                    "logprobs": {"content": logprob_items(text)},
                }
            ],
            "usage": {"completion_tokens": len(text.split())},
        }
        return {
            "node": node,
            "ok": True,
            "status": 200,
            "endpoint_mode": "fake_openai_chat_completions",
            "text": text,
            "text_raw": text,
            "thinking_tag_present": False,
            "empty_thinking_shell": False,
            "thinking_content_present": False,
            "cleaning_applied": False,
            "cleaning_allowed": True,
            "failed_TR": False,
            "removed_prefix_chars": 0,
            "raw_logprobs": raw["choices"][0]["logprobs"]["content"],
            "clean_logprobs": raw["choices"][0]["logprobs"]["content"],
            "excluded_token_positions": [],
            "raw": raw,
            "elapsed_ms": self.delay_ms,
        }


class FakeRAGClient:
    async def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return [
            {
                "id": f"fake_chunk_{idx}",
                "text": f"가짜 검색 문서 {idx}: {query}",
                "metadata": {"source": "stage_like_logger_benchmark", "block_type": "text"},
            }
            for idx in range(top_k)
        ]


def queue_depth(runner: ExperimentRunner) -> int:
    db_logger = getattr(runner.logger, "db_logger", None)
    q = getattr(db_logger, "_queue", None)
    if q is None:
        return 0
    return int(q.qsize())


def write_config(base_path: str, async_enabled: bool, jsonl_dir: str) -> str:
    config = copy.deepcopy(load_config(base_path))
    config["logging"]["jsonl_fallback_dir"] = jsonl_dir
    config["logging"]["db"]["async_enabled"] = async_enabled
    config["metrics"]["cds"]["enabled"] = False
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    with handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return handle.name


async def run_case(
    name: str,
    config_path: str,
    sc_policy_path: str,
    theta_path: str,
    turns: int,
    condition: str,
    fake_latency_ms: float,
) -> Dict[str, Any]:
    runner = ExperimentRunner(config_path, sc_policy_path, theta_path)
    runner.node_client = FakeNodeClient(fake_latency_ms)
    runner.rag_client = FakeRAGClient()
    runner.config["metrics"]["cds"]["enabled"] = False
    runner.metric_computer = MetricComputer(runner.config)

    run_id = f"stage_like_logger_{name}_{condition}_{int(time.time() * 1000)}"
    elapsed: List[float] = []
    max_depth = 0
    flush_ms = 0.0
    try:
        for turn_no in range(1, turns + 1):
            payload = {
                "run_id": run_id,
                "scenario_id": SCENARIO_ID,
                "scenario_hash": sha(SCENARIO_ID),
                "condition": condition,
                "run_mode": "smoke",
                "turn_no": turn_no,
                "utterance": f"벤치마크 민원 발화 {turn_no}: 수급 신청 서류를 어디서 확인하나요?",
                "source_file": "/tmp/stage_like_logger_benchmark.json",
            }
            started = time.perf_counter()
            result = await runner.handle_turn(payload)
            elapsed.append((time.perf_counter() - started) * 1000)
            if not result.get("ok"):
                raise RuntimeError(result)
            max_depth = max(max_depth, queue_depth(runner))
        flush_started = time.perf_counter()
        runner.flush_logs(30.0)
        flush_ms = (time.perf_counter() - flush_started) * 1000
    finally:
        runner.close()

    summary = summarize(elapsed)
    summary["flush_ms"] = flush_ms
    summary["max_queue_depth"] = float(max_depth)
    summary["run_id"] = run_id
    summary["mode"] = name
    summary["condition"] = condition
    summary["fake_latency_ms"] = fake_latency_ms
    return summary


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/home/morophi/harness/config/node_config.yaml")
    parser.add_argument("--sc-policy", default="/home/morophi/harness/config/sc_policy.yaml")
    parser.add_argument("--theta", default="/home/morophi/harness/config/theta_config.json")
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--fake-latency-ms", type=float, action="append", default=None)
    parser.add_argument("--jsonl-dir", default="/tmp/lacp_stage_like_logger_bench")
    parser.add_argument("--mode", choices=["sync", "async", "both"], default="both")
    args = parser.parse_args()

    latencies = args.fake_latency_ms or [0.0, 50.0, 100.0]
    modes = ["sync", "async"] if args.mode == "both" else [args.mode]
    results = []
    for mode in modes:
        cfg = write_config(
            args.config,
            async_enabled=(mode == "async"),
            jsonl_dir=str(Path(args.jsonl_dir) / mode),
        )
        for latency in latencies:
            for condition in ("cr", "run_b"):
                results.append(
                    await run_case(
                        mode,
                        cfg,
                        args.sc_policy,
                        args.theta,
                        args.turns,
                        condition,
                        latency,
                    )
                )
    print(json.dumps({"scenario_id": SCENARIO_ID, "turns": args.turns, "results": results}, indent=2, ensure_ascii=False))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
