#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Post-validate completed formal Harness JSONL evidence.

This script is intentionally read-only. Launchers call it after
`run_experiment_stage.py` reports `stage_run_done run_id=...`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_EXPECTED_NODES = {"A", "B", "C"}
CF_F_DEFAULT_FORCED_TURNS = {3, 6, 9, 12, 15, 18, 21, 24, 27, 29}
CF_D_DEFAULT_FORCED_TURNS = {5, 15, 25}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate post-run formal JSONL evidence.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--jsonl", type=Path, default=None)
    parser.add_argument("--harness-host", default="harness")
    parser.add_argument("--expected-turns", type=int, default=30)
    parser.add_argument("--expected-nodes", default="A,B,C")
    parser.add_argument("--output-dir", type=Path, default=Path("/home/lacp/agent/validation_queries/formal_post_validation"))
    parser.add_argument("--allow-missing-lms", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    expected_nodes = {part.strip().upper() for part in args.expected_nodes.split(",") if part.strip()}
    if not expected_nodes:
        expected_nodes = set(DEFAULT_EXPECTED_NODES)

    jsonl_path = resolve_jsonl(args)
    rows = load_jsonl(jsonl_path)
    summary = validate_rows(
        rows,
        stage=args.stage,
        run_id=args.run_id,
        expected_turns=args.expected_turns,
        expected_nodes=expected_nodes,
        require_lms=not args.allow_missing_lms,
    )
    payload = {
        "run_id": args.run_id,
        "stage": args.stage,
        "jsonl": str(jsonl_path),
        "summary": summary,
    }
    output = args.output_dir / f"{args.run_id}_post_validation.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "pass" else 2


def resolve_jsonl(args: argparse.Namespace) -> Path:
    if args.jsonl is not None:
        if not args.jsonl.exists():
            raise FileNotFoundError(args.jsonl)
        return args.jsonl

    local_harness_path = Path("/home/lacp/harness/logs/runs") / f"{args.run_id}.jsonl"
    if local_harness_path.exists():
        return local_harness_path

    fetched = args.output_dir / f"{args.run_id}.jsonl"
    remote = f"{args.harness_host}:/home/lacp/harness/logs/runs/{args.run_id}.jsonl"
    proc = subprocess.run(["scp", remote, str(fetched)], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to fetch harness jsonl {remote}: {proc.stderr.strip()}")
    return fetched


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{lineno}: invalid JSONL row: {exc}") from exc
    return rows


def validate_rows(
    rows: list[dict[str, Any]],
    *,
    stage: str,
    run_id: str,
    expected_turns: int,
    expected_nodes: set[str],
    require_lms: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    by_turn: dict[int, set[str]] = defaultdict(set)
    row_count_expected = expected_turns * len(expected_nodes)
    sc_rows = 0
    rag_rows = 0
    lms_available_rows = 0

    if not rows:
        failures.append("JSONL has no rows")

    for idx, row in enumerate(rows, 1):
        row_run_id = str(row.get("run_id") or "")
        if row_run_id != run_id:
            failures.append(f"row {idx} run_id mismatch: {row_run_id!r}")
        try:
            turn_no = int(row.get("turn_no"))
        except (TypeError, ValueError):
            failures.append(f"row {idx} missing integer turn_no")
            continue
        node = str(row.get("node") or "").upper()
        by_turn[turn_no].add(node)

        if node not in expected_nodes:
            failures.append(f"turn {turn_no} unexpected node {node!r}")
        if not str(row.get("response_text") or "").strip():
            failures.append(f"turn {turn_no} node {node} response_text empty")

        rag_injected = as_bool(row.get("rag_injected"))
        sc_applied = as_bool(row.get("sc_policy_applied"))
        prompt_sc_marker = as_bool(row.get("prompt_contains_sc_marker"))
        if rag_injected:
            rag_rows += 1
        if sc_applied:
            sc_rows += 1

        if node == "C":
            if rag_injected:
                failures.append(f"turn {turn_no} node C must not have RAG")
            if sc_applied or prompt_sc_marker:
                failures.append(f"turn {turn_no} node C must not have SC")
        if node == "B" and (sc_applied or prompt_sc_marker):
            failures.append(f"turn {turn_no} node B must not have SC")
        if sc_applied and node != "A":
            failures.append(f"turn {turn_no} node {node} SC is only allowed on A")
        if sc_applied != prompt_sc_marker:
            failures.append(
                f"turn {turn_no} node {node} sc_policy_applied={sc_applied} "
                f"prompt_contains_sc_marker={prompt_sc_marker}"
            )
        if rag_injected and int_or_zero(row.get("rag_context_chars")) <= 0:
            warnings.append(f"turn {turn_no} node {node} rag_injected true but rag_context_chars <= 0")

        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        metric_status = row.get("metric_status") if isinstance(row.get("metric_status"), dict) else {}
        nested_status = metrics.get("metric_status") if isinstance(metrics.get("metric_status"), dict) else {}
        if not metrics:
            failures.append(f"turn {turn_no} node {node} metrics missing")
        raw_len = first_int(
            row.get("raw_logprobs_len"),
            row.get("lms_raw_logprobs_len"),
            metric_status.get("raw_logprobs_len"),
            metric_status.get("lms_raw_logprobs_len"),
            nested_status.get("raw_logprobs_len"),
            nested_status.get("lms_raw_logprobs_len"),
        )
        clean_len = first_int(
            row.get("clean_logprobs_len"),
            row.get("lms_clean_logprobs_len"),
            metric_status.get("clean_logprobs_len"),
            metric_status.get("lms_clean_logprobs_len"),
            nested_status.get("clean_logprobs_len"),
            nested_status.get("lms_clean_logprobs_len"),
        )
        lms_value_present = metrics.get("lms_value") is not None
        lms_available = as_bool(
            first_present(
                row.get("lms_available"),
                metric_status.get("lms_available"),
                nested_status.get("lms_available"),
                lms_value_present,
            )
        )
        if lms_available:
            lms_available_rows += 1
        if require_lms and (raw_len <= 0 or clean_len <= 0 or not lms_available):
            failures.append(
                f"turn {turn_no} node {node} LMS/logprobs unavailable "
                f"raw={raw_len} clean={clean_len} available={lms_available}"
            )

    for turn_no in range(1, expected_turns + 1):
        nodes = by_turn.get(turn_no, set())
        if nodes != expected_nodes:
            failures.append(f"turn {turn_no} expected nodes {sorted(expected_nodes)}, got {sorted(nodes)}")

    if len(rows) != row_count_expected:
        failures.append(f"expected {row_count_expected} rows, got {len(rows)}")

    cf_integrity = validate_cf_integrity(stage, rows) if stage.startswith("cf_") else None
    if cf_integrity:
        failures.extend(cf_integrity["failures"])
    run_b_integrity = validate_run_b_integrity(rows) if stage == "run_b" else None
    if run_b_integrity:
        failures.extend(run_b_integrity["failures"])
        warnings.extend(run_b_integrity.get("warnings", []))
    cr2_integrity = validate_cr2_integrity(rows) if stage == "cr2" else None
    if cr2_integrity:
        failures.extend(cr2_integrity["failures"])

    reproducibility_summary = summarize_reproducibility(rows)
    sign_aware_summary = summarize_sign_aware_exceedance(rows)

    summary = {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "warnings": warnings,
        "row_count": len(rows),
        "expected_row_count": row_count_expected,
        "turn_count": len(by_turn),
        "expected_turns": expected_turns,
        "expected_nodes": sorted(expected_nodes),
        "rag_rows": rag_rows,
        "sc_rows": sc_rows,
        "lms_available_rows": lms_available_rows,
        "reproducibility_summary": reproducibility_summary,
        "sign_aware_exceedance_summary": sign_aware_summary,
    }
    if run_b_integrity is not None:
        summary["run_b_treatment_integrity"] = run_b_integrity
    if cr2_integrity is not None:
        summary["cr2_intervention_calibration_integrity"] = cr2_integrity
    if cf_integrity is not None:
        summary["counterfactual_treatment_integrity"] = cf_integrity
    return summary


def validate_run_b_integrity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    by_node = {
        "A": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "rag_context_rows": 0, "sc_block_rows": 0, "collection_rows": 0},
        "B": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "rag_context_rows": 0, "sc_block_rows": 0, "collection_rows": 0},
        "C": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "rag_context_rows": 0, "sc_block_rows": 0, "collection_rows": 0},
    }
    complete_turns = 0
    identical_prompt_turns = 0
    identical_response_turns = 0
    by_turn: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        node = str(row.get("node") or "").upper()
        if node not in by_node:
            continue
        try:
            turn_no = int(row.get("turn_no"))
        except (TypeError, ValueError):
            turn_no = -1
        by_turn[turn_no].append(row)
        by_node[node]["rows"] += 1
        rag = as_bool(row.get("rag_injected"))
        sc = as_bool(row.get("sc_policy_applied"))
        retrieved = bool(parse_retrieved_chunk_ids(row.get("retrieved_chunk_ids") or row.get("rag_chunk_ids")))
        rag_context = int_or_zero(row.get("rag_context_chars")) > 0
        sc_block = int_or_zero(row.get("sc_block_chars")) > 0
        collection_present = bool(str(row.get("collection_name") or "").strip())
        if rag:
            by_node[node]["rag_rows"] += 1
        if sc:
            by_node[node]["sc_rows"] += 1
        if retrieved:
            by_node[node]["retrieved_rows"] += 1
        if rag_context:
            by_node[node]["rag_context_rows"] += 1
        if sc_block:
            by_node[node]["sc_block_rows"] += 1
        if collection_present:
            by_node[node]["collection_rows"] += 1

        if rag and not collection_present:
            failures.append(f"run_b turn {turn_no} node {node} rag_injected without collection_name")
        if rag and not retrieved:
            failures.append(f"run_b turn {turn_no} node {node} rag_injected without retrieved_chunk_ids")
        if rag and not rag_context:
            failures.append(f"run_b turn {turn_no} node {node} rag_injected without rag_context_chars")
        if sc and not sc_block:
            failures.append(f"run_b turn {turn_no} node {node} sc_policy_applied without sc_block_chars")

    for turn_no, turn_rows in by_turn.items():
        nodes = {str(row.get("node") or "").upper() for row in turn_rows}
        if nodes != DEFAULT_EXPECTED_NODES:
            continue
        complete_turns += 1
        prompt_hashes = {str(row.get("prompt_hash") or "") for row in turn_rows if row.get("prompt_hash")}
        response_hashes = {str(row.get("response_hash") or "") for row in turn_rows if row.get("response_hash")}
        if len(prompt_hashes) == 1:
            identical_prompt_turns += 1
        if len(response_hashes) == 1:
            identical_response_turns += 1

    if by_node["A"]["rag_rows"] == 0:
        failures.append("Run B node A has zero rag_injected rows")
    elif by_node["A"]["rag_rows"] != by_node["A"]["rows"]:
        failures.append("Run B node A must have rag_injected on every row")
    if by_node["A"]["sc_rows"] == 0:
        warnings.append("Run B node A has zero sc_policy_applied rows; report as zero realized SC triggers")
    if by_node["B"]["rag_rows"] == 0:
        failures.append("Run B node B has zero rag_injected rows")
    elif by_node["B"]["rag_rows"] != by_node["B"]["rows"]:
        failures.append("Run B node B must have rag_injected on every row")
    if by_node["B"]["sc_rows"] != 0:
        failures.append("Run B node B must not have sc_policy_applied")
    if by_node["C"]["rag_rows"] != 0:
        failures.append("Run B node C must not have rag_injected")
    if by_node["C"]["sc_rows"] != 0:
        failures.append("Run B node C must not have sc_policy_applied")
    if complete_turns and identical_prompt_turns == complete_turns:
        failures.append("Run B A/B/C prompt_hash identical in every complete turn group")
    if complete_turns and identical_response_turns == complete_turns:
        failures.append("Run B A/B/C response_hash identical in every complete turn group")
    failures.extend(validate_run_b_trigger_alignment(by_turn))

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "warnings": warnings,
        "node_counts": by_node,
        "complete_turn_groups": complete_turns,
        "identical_prompt_turn_groups": identical_prompt_turns,
        "identical_response_turn_groups": identical_response_turns,
    }


def validate_cr2_integrity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    by_node = {
        "A": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "bad_modes": 0},
        "B": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "bad_modes": 0},
        "C": {"rows": 0, "rag_rows": 0, "sc_rows": 0, "retrieved_rows": 0, "bad_modes": 0},
    }
    for row in rows:
        node = str(row.get("node") or "").upper()
        if node not in by_node:
            continue
        by_node[node]["rows"] += 1
        rag = as_bool(row.get("rag_injected"))
        sc = as_bool(row.get("sc_policy_applied"))
        retrieved = bool(parse_retrieved_chunk_ids(row.get("retrieved_chunk_ids") or row.get("rag_chunk_ids")))
        if rag:
            by_node[node]["rag_rows"] += 1
        if sc:
            by_node[node]["sc_rows"] += 1
        if retrieved:
            by_node[node]["retrieved_rows"] += 1
        if str(row.get("trigger_mode") or "") != "cr2_intervention_exposure":
            by_node[node]["bad_modes"] += 1

    for node in ("A", "B", "C"):
        if by_node[node]["rows"] == 0:
            failures.append(f"CR2 node {node} has no rows")
        if by_node[node]["bad_modes"]:
            failures.append(f"CR2 node {node} has rows without trigger_mode=cr2_intervention_exposure")

    if by_node["A"]["rag_rows"] != by_node["A"]["rows"]:
        failures.append("CR2 node A must have rag_injected on every row")
    if by_node["A"]["sc_rows"] != by_node["A"]["rows"]:
        failures.append("CR2 node A must have sc_policy_applied on every row")
    if by_node["A"]["retrieved_rows"] != by_node["A"]["rows"]:
        failures.append("CR2 node A must have retrieved_chunk_ids on every row")

    if by_node["B"]["rag_rows"] != by_node["B"]["rows"]:
        failures.append("CR2 node B must have rag_injected on every row")
    if by_node["B"]["sc_rows"] != 0:
        failures.append("CR2 node B must not have sc_policy_applied")
    if by_node["B"]["retrieved_rows"] != by_node["B"]["rows"]:
        failures.append("CR2 node B must have retrieved_chunk_ids on every row")

    if by_node["C"]["rag_rows"] != 0:
        failures.append("CR2 node C must not have rag_injected")
    if by_node["C"]["sc_rows"] != 0:
        failures.append("CR2 node C must not have sc_policy_applied")
    if by_node["C"]["retrieved_rows"] != 0:
        failures.append("CR2 node C must not have retrieved_chunk_ids")

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "node_counts": by_node,
        "wiring_artifact_only": True,
        "db_schema_changed": False,
    }


def summarize_reproducibility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[str, dict[str, Any]] = defaultdict(lambda: {"hashes": set(), "elapsed_ms": [], "metric_values": defaultdict(list)})
    for row in rows:
        node = str(row.get("node") or "").upper()
        if not node:
            continue
        response_hash = row.get("response_hash")
        if response_hash:
            by_node[node]["hashes"].add(str(response_hash))
        elapsed = float_or_none(row.get("elapsed_ms"))
        if elapsed is not None:
            by_node[node]["elapsed_ms"].append(elapsed)
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        for key in ("lms_value", "cds", "ma_assert", "srr", "sci"):
            value = float_or_none(metrics.get(key))
            if value is not None:
                by_node[node]["metric_values"][key].append(value)

    summary: dict[str, Any] = {}
    for node, item in sorted(by_node.items()):
        elapsed = item["elapsed_ms"]
        metric_values = item["metric_values"]
        summary[node] = {
            "response_hash_unique_count": len(item["hashes"]),
            "response_hash_mode": "hash_identical" if len(item["hashes"]) == 1 else "divergent",
            "elapsed_ms": describe_numeric(elapsed),
            "metrics": {key: describe_numeric(values) for key, values in sorted(metric_values.items())},
        }
    return summary


def summarize_sign_aware_exceedance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "rule": "absolute magnitude alone is not counted as supporting evidence",
        "supportive_counts": defaultdict(int),
        "opposite_direction_counts": defaultdict(int),
        "evaluated_rows": 0,
    }
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        threshold = row.get("threshold_snapshot") if isinstance(row.get("threshold_snapshot"), dict) else {}
        if not metrics or not threshold:
            continue
        summary["evaluated_rows"] += 1
        for metric, theta_key, supportive_positive in (
            ("d_lms", "theta_lms", True),
            ("d_cds", "theta_cds", True),
            ("d_ma", "theta_ma", False),
        ):
            if not threshold_metric_enabled(threshold, theta_key):
                continue
            value = float_or_none(metrics.get(metric))
            theta = float_or_none(threshold.get(theta_key))
            if value is None or theta is None or abs(value) <= theta:
                continue
            key = f"{row.get('node')}:{metric}"
            if (value > 0) == supportive_positive:
                summary["supportive_counts"][key] += 1
            else:
                summary["opposite_direction_counts"][key] += 1

    return {
        "rule": summary["rule"],
        "evaluated_rows": summary["evaluated_rows"],
        "supportive_counts": dict(summary["supportive_counts"]),
        "opposite_direction_counts": dict(summary["opposite_direction_counts"]),
    }


def validate_run_b_trigger_alignment(by_turn: dict[int, list[dict[str, Any]]]) -> list[str]:
    failures: list[str] = []
    ordered_turns = sorted(turn_no for turn_no in by_turn if turn_no > 0)
    for turn_no in ordered_turns:
        rows_by_node = {str(row.get("node") or "").upper(): row for row in by_turn.get(turn_no, [])}
        node_a = rows_by_node.get("A")
        node_b = rows_by_node.get("B")
        node_c = rows_by_node.get("C")
        if not node_a or not node_b or not node_c:
            continue
        if turn_no == 1:
            if as_bool(node_a.get("sc_policy_applied")):
                failures.append("Run B turn 1 node A must not have SC; no previous delta metrics exist")
            continue
        previous_rows = {
            str(row.get("node") or "").upper(): row
            for row in by_turn.get(turn_no - 1, [])
        }
        expected_sc, reasons = expected_run_b_sc_from_previous_turn(previous_rows, node_a)
        actual_sc = as_bool(node_a.get("sc_policy_applied"))
        if actual_sc != expected_sc:
            failures.append(
                f"Run B turn {turn_no} node A SC mismatch: expected={expected_sc} "
                f"actual={actual_sc} reasons={reasons}"
            )
    return failures


def expected_run_b_sc_from_previous_turn(
    previous_rows: dict[str, dict[str, Any]],
    current_a_row: dict[str, Any],
) -> tuple[bool, list[str]]:
    threshold = current_a_row.get("threshold_snapshot") if isinstance(current_a_row.get("threshold_snapshot"), dict) else {}
    reasons: list[str] = []
    for node in ("A", "B"):
        row = previous_rows.get(node)
        if not row:
            continue
        if as_bool(row.get("exclude_from_causal_trigger")) or row.get("analysis_eligible") is False:
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        eligibility = metrics.get("metric_trigger_eligibility") if isinstance(metrics.get("metric_trigger_eligibility"), dict) else {}
        for metric, theta_key, eligibility_key in (
            ("d_lms", "theta_lms", "lms_trigger_eligible"),
            ("d_cds", "theta_cds", "cds_trigger_eligible"),
            ("d_ma", "theta_ma", "ma_trigger_eligible"),
        ):
            if not threshold_metric_enabled(threshold, theta_key):
                continue
            if eligibility.get(eligibility_key) is False:
                continue
            value = float_or_none(metrics.get(metric))
            theta = float_or_none(threshold.get(theta_key))
            if value is not None and theta is not None and abs(value) > theta:
                reasons.append(f"{node}.{metric}:abs({value})>{theta}")
    return bool(reasons), reasons


def threshold_metric_enabled(threshold: dict[str, Any], theta_key: str) -> bool:
    enabled_key = f"{theta_key}_threshold_evidence_enabled"
    if threshold.get(enabled_key) is False:
        return False
    status_key = f"{theta_key}_status"
    status = str(threshold.get(status_key) or "").lower()
    if "descriptive" in status or "fallback" in status:
        return False
    return True


def validate_cf_integrity(stage: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    by_node = {
        "A": {"rows": 0, "rag_rows": 0, "sc_rows": 0},
        "B": {"rows": 0, "rag_rows": 0, "sc_rows": 0},
        "C": {"rows": 0, "rag_rows": 0, "sc_rows": 0},
    }
    for row in rows:
        try:
            turn_no = int(row.get("turn_no"))
        except (TypeError, ValueError):
            continue
        node = str(row.get("node") or "").upper()
        rag_injected = as_bool(row.get("rag_injected"))
        sc_applied = as_bool(row.get("sc_policy_applied"))
        if node in by_node:
            by_node[node]["rows"] += 1
            by_node[node]["rag_rows"] += int(rag_injected)
            by_node[node]["sc_rows"] += int(sc_applied)

        expected = expected_cf_assignment(stage, turn_no, node)
        if expected is None:
            continue
        expected_rag, expected_sc = expected
        if rag_injected != expected_rag or sc_applied != expected_sc:
            failures.append(
                f"{stage} turn {turn_no} node {node} expected rag={expected_rag} "
                f"sc={expected_sc} got rag={rag_injected} sc={sc_applied}"
            )

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "node_counts": by_node,
    }


def expected_cf_assignment(stage: str, turn_no: int, node: str) -> tuple[bool, bool] | None:
    node = node.upper()
    if node not in DEFAULT_EXPECTED_NODES:
        return None
    if stage == "cf_a":
        return False, False
    if stage == "cf_b":
        return (node in {"A", "B"}), False
    if stage == "cf_c":
        return False, node == "A"
    if stage == "cf_d":
        forced = turn_no in CF_D_DEFAULT_FORCED_TURNS
        return (node in {"A", "B"} and forced), False
    if stage == "cf_e":
        return (node in {"A", "B"}), node == "A"
    if stage == "cf_f":
        forced = turn_no in CF_F_DEFAULT_FORCED_TURNS
        if node == "A":
            return forced, forced
        if node == "B":
            return forced, False
        return False, False
    return None


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def parse_retrieved_chunk_ids(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text in {"", "NULL", "null", "[]"}:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [text]
    return [value]


def float_or_none(value: Any) -> float | None:
    if value in (None, "", "NULL"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def describe_numeric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean(ordered),
        "p95": percentile(ordered, 0.95),
        "dispersion": ordered[-1] - ordered[0],
    }


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


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def first_int(*values: Any) -> int:
    for value in values:
        if value is not None:
            return int_or_zero(value)
    return 0


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"post_validation_error: {exc}", file=sys.stderr)
        raise SystemExit(2)
