#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from config_utils import load_config
from logger import CompositeLogger, JSONLLogger, MariaDBLogger


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


def synthetic_row(run_id: str, idx: int, include_rag: bool) -> Dict[str, Any]:
    nodes: Iterable[str] = ("A", "B") if include_rag else ("A", "B", "C")
    node_list = list(nodes)
    node = node_list[idx % len(node_list)]
    turn_no = idx // len(node_list) + 1
    text = f"synthetic response {run_id} {idx}"
    rag_injected = bool(include_rag and node in {"A", "B"})
    sc_policy_applied = bool(rag_injected and node == "A")
    return {
        "run_id": run_id,
        "scenario_id": "logger_overhead_benchmark",
        "scenario_hash": "0" * 64,
        "condition": "overhead_benchmark",
        "run_mode": "smoke",
        "turn_no": turn_no,
        "node": node,
        "source_file": "/tmp/logger_overhead_benchmark.json",
        "harness_version": "overhead-benchmark",
        "node_config_hash": "2" * 64,
        "run_sc_policy_id": "sc_protocol_v1",
        "run_policy_hash": "3" * 64,
        "theta_source": "/home/morophi/harness/config/theta_config.json",
        "theta_locked": True,
        "utterance_hash": sha(f"utterance {run_id} {idx}"),
        "response_text": text,
        "response_hash": sha(text),
        "elapsed_ms": 1000.0 + idx,
        "rag_injected": rag_injected,
        "sc_policy_applied": sc_policy_applied,
        "sc_policy_id": "sc_protocol_v1" if sc_policy_applied else None,
        "policy_hash": "3" * 64 if sc_policy_applied else None,
        "trigger_mode": "benchmark" if rag_injected else None,
        "trigger_reasons": ["benchmark"] if rag_injected else [],
        "trigger_source_nodes": ["A"] if sc_policy_applied else [],
        "threshold_snapshot": {"theta_lms": 0.0} if sc_policy_applied else {},
        "previous_turn_used_for_trigger": max(turn_no - 1, 0) if rag_injected else None,
        "rag_chunk_ids": [f"chunk_{idx}_1"] if rag_injected else [],
        "retrieved_chunk_ids": [f"chunk_{idx}_1"] if rag_injected else [],
        "collection_name": "lacp_docs_v2_table_safe_topk5" if rag_injected else None,
        "top_k": 5 if rag_injected else None,
        "returned_count": 1 if rag_injected else 0,
        "rag_context_chars": 128 if rag_injected else 0,
        "retrieval_method": "synthetic_benchmark" if rag_injected else None,
        "table_exposure": False,
        "chunk_lengths": [128] if rag_injected else [],
        "block_type_distribution": {"text": 1} if rag_injected else {},
        "prompt_hash": sha(f"prompt {run_id} {idx}"),
        "payload_hash": sha(f"payload {run_id} {idx}"),
        "message_count": 4 if rag_injected else 2,
        "prompt_chars": 1024 if rag_injected else 512,
        "model_name": "qwen3-nothink",
        "model_digest": None,
        "temperature": 0.0,
        "seed": 42,
        "thinking_disabled_requested": True,
        "endpoint_mode": "openai_chat_completions",
        "response_text_raw_hash": sha(text),
        "thinking_tag_present": False,
        "empty_thinking_shell": False,
        "thinking_content_present": False,
        "cleaning_applied": False,
        "cleaning_allowed": True,
        "failed_TR": False,
        "removed_prefix_chars": 0,
        "raw_logprobs_len": 4,
        "clean_logprobs_len": 4,
        "excluded_token_positions": [],
        "quality_gate": {
            "generation_quality_ready": True,
            "analysis_eligible": True,
            "exclude_from_causal_trigger": False,
            "history_eligible": True,
            "usable_as_quality_outcome": True,
        },
        "generation_quality_ready": True,
        "analysis_eligible": True,
        "exclude_from_causal_trigger": False,
        "history_eligible": True,
        "usable_as_quality_outcome": True,
        "metrics": {
            "lms_value": 1.23,
            "lms_token_count": 4,
            "theta_entropy": 0.0,
            "lms_delta": 0.0,
            "cds": 0.11,
            "ma_assert": 1.0,
            "ma_epist": 0.0,
            "ma_hedge": 0.0,
            "sent_count": 1,
            "srr": None,
            "sci": None,
            "metric_status": {"lms_available": True},
            "metric_trigger_eligibility": {"lms": True, "ma": True, "cds": True},
            "metric_pipeline_version": "benchmark",
        },
        "metric_status": {"lms_available": True},
        "raw_response_keys": ["choices", "usage"],
    }


def run_case(name: str, logger: Any, rows: int, include_rag: bool) -> Dict[str, Any]:
    suffix = "rag" if include_rag else "no_rag"
    run_id = f"logger_overhead_{name}_{suffix}_{int(time.time() * 1000)}"
    elapsed: List[float] = []
    for idx in range(rows):
        row = synthetic_row(run_id, idx, include_rag)
        started = time.perf_counter()
        logger.log_turn(run_id, row)
        elapsed.append((time.perf_counter() - started) * 1000)
    summary = summarize(elapsed)
    summary["total_ms"] = sum(elapsed)
    return {"mode": name, "shape": suffix, "run_id": run_id, **summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/home/morophi/harness/config/node_config.yaml")
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument("--jsonl-dir", default="/tmp/lacp_logger_overhead_bench")
    args = parser.parse_args()

    config = load_config(args.config)
    db_config = config["logging"]["db"]
    jsonl_dir = Path(args.jsonl_dir)
    jsonl_dir.mkdir(parents=True, exist_ok=True)

    cases = [
        ("jsonl", lambda: JSONLLogger(str(jsonl_dir / "jsonl"))),
        ("db", lambda: MariaDBLogger(db_config)),
        (
            "composite",
            lambda: CompositeLogger(
                JSONLLogger(str(jsonl_dir / "composite")),
                MariaDBLogger(db_config),
            ),
        ),
    ]

    results = []
    for name, factory in cases:
        for include_rag in (False, True):
            results.append(run_case(name, factory(), args.rows, include_rag))

    print(json.dumps({"rows_per_case": args.rows, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
