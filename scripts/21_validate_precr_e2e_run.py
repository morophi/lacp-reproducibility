"""
Step 21: Validate a 5-turn pre-CR E2E smoke run.

This validator is intentionally post-hoc and read-only. It checks a Harness
JSONL run log after `agent/run_scenario.py` has sent the 5-query pre-CR scenario.
The run is readiness evidence only, not causal evidence.

Checks:
    - A/B/C response_text are non-empty for every turn.
    - thinking content is absent.
    - Node C has no RAG; Nodes A/B have RAG.
    - LMS/MA/CDS metrics are present enough to prove logging plumbing.
    - prompt_eval_count, done_reason, retrieved chunk ids, collection/corpus
      metadata, and sidecar flags are preserved when available.

The script does not call inference nodes, RAG, Chroma, or MariaDB.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


EXPECTED_NODES = {"A", "B", "C"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate pre-CR E2E 5-query JSONL run output.")
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--expected-turns", type=int, default=5)
    parser.add_argument("--context-limit", type=int, default=4096)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_jsonl(args.jsonl)
    summary = validate(rows, args.expected_turns, args.context_limit)
    payload = {"jsonl": str(args.jsonl), "summary": summary, "rows_checked": len(rows)}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 2


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def validate(rows: list[dict[str, Any]], expected_turns: int, context_limit: int) -> dict[str, Any]:
    failures: list[str] = []
    by_turn: dict[int, set[str]] = defaultdict(set)
    response_empty = 0
    thinking_present = 0
    timeout_or_500 = 0
    rag_counts = Counter()
    metric_complete_rows = 0
    prompt_eval_over_limit = 0
    done_reason_counts = Counter()
    length_done_rows = 0
    missing_retrieval_metadata = 0
    sidecar_prompt_true_rows = 0

    for row in rows:
        turn_no = int(row.get("turn_no", -1))
        node = str(row.get("node", ""))
        by_turn[turn_no].add(node)
        if not str(row.get("response_text") or "").strip():
            response_empty += 1
        if row.get("thinking_content_present"):
            thinking_present += 1
        raw_keys = set(row.get("raw_response_keys") or [])
        if row.get("status") == 500 or "error" in raw_keys:
            timeout_or_500 += 1
        rag_injected = bool(row.get("rag_injected"))
        rag_counts[(node, rag_injected)] += 1
        metrics = row.get("metrics") or {}
        metric_status = row.get("metric_status") or metrics.get("metric_status") or {}
        if metric_has_lms(metrics, metric_status) and metric_has_ma(metrics) and metric_has_cds(metrics):
            metric_complete_rows += 1
        raw = metrics.get("raw") if isinstance(metrics.get("raw"), dict) else {}
        prompt_eval_count = first_present("prompt_eval_count", row, metrics, raw)
        if isinstance(prompt_eval_count, int) and prompt_eval_count >= context_limit:
            prompt_eval_over_limit += 1
        done_reason = first_present("done_reason", row, metrics, raw)
        if done_reason:
            done_reason_counts[str(done_reason)] += 1
            if str(done_reason) == "length":
                length_done_rows += 1
        if rag_injected and not row.get("rag_chunk_ids"):
            missing_retrieval_metadata += 1
        retrieval_policy = row.get("retrieval_policy") or {}
        if retrieval_policy.get("sidecar_prompt_injection_enabled") is True:
            sidecar_prompt_true_rows += 1

    for turn in range(1, expected_turns + 1):
        if by_turn.get(turn) != EXPECTED_NODES:
            failures.append(f"turn {turn} missing nodes: {sorted(EXPECTED_NODES - by_turn.get(turn, set()))}")
    if len(rows) != expected_turns * 3:
        failures.append(f"expected {expected_turns * 3} node rows, got {len(rows)}")
    if response_empty:
        failures.append(f"response_text empty rows: {response_empty}")
    if thinking_present:
        failures.append(f"thinking_present_rows: {thinking_present}")
    if timeout_or_500:
        failures.append(f"timeout_or_500_rows: {timeout_or_500}")
    if rag_counts.get(("C", True), 0):
        failures.append("Node C rag_injected must be 0")
    for node in ("A", "B"):
        if rag_counts.get((node, True), 0) != expected_turns:
            failures.append(f"Node {node} rag_injected expected {expected_turns}")
    if metric_complete_rows != len(rows):
        failures.append(f"metric complete rows {metric_complete_rows}/{len(rows)}")
    if prompt_eval_over_limit:
        failures.append(f"prompt_eval_count over context limit rows: {prompt_eval_over_limit}")
    if length_done_rows:
        failures.append(f"done_reason=length rows: {length_done_rows}")
    if missing_retrieval_metadata:
        failures.append(f"rag rows missing retrieved chunk ids: {missing_retrieval_metadata}")
    if sidecar_prompt_true_rows:
        failures.append(f"sidecar prompt injection true rows: {sidecar_prompt_true_rows}")

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "row_count": len(rows),
        "turn_node_coverage": {str(turn): sorted(nodes) for turn, nodes in sorted(by_turn.items())},
        "response_empty_rows": response_empty,
        "thinking_present_rows": thinking_present,
        "rag_counts": {f"{node}:{flag}": count for (node, flag), count in sorted(rag_counts.items())},
        "metric_complete_rows": metric_complete_rows,
        "prompt_eval_over_limit_rows": prompt_eval_over_limit,
        "done_reason_counts": dict(sorted(done_reason_counts.items())),
        "done_reason_length_rows": length_done_rows,
        "missing_retrieval_metadata_rows": missing_retrieval_metadata,
        "sidecar_prompt_true_rows": sidecar_prompt_true_rows,
    }


def metric_has_lms(metrics: dict[str, Any], metric_status: dict[str, Any]) -> bool:
    return metrics.get("lms_value") is not None or metric_status.get("lms") in {"ok", "unavailable_nonblocking"}


def metric_has_ma(metrics: dict[str, Any]) -> bool:
    return any(metrics.get(key) is not None for key in ("ma_assert", "ma_epist", "ma_hedge"))


def metric_has_cds(metrics: dict[str, Any]) -> bool:
    return metrics.get("cds") is not None


def first_present(key: str, *sources: dict[str, Any]) -> Any:
    for source in sources:
        if isinstance(source, dict) and key in source:
            return source[key]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
