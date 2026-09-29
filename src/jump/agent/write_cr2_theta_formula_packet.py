#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Write a CR2 theta-formula review packet for professor feedback.

This does not install theta by itself. In formal operation it is called after
CR2 completion has already frozen theta, so the packet documents the formula
inputs and the frozen value context for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "runtime_impl" / "agent"
if AGENT.exists():
    sys.path.insert(0, str(AGENT))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_experiment_stage as stage_runner  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("/home/lacp/agent/validation_queries/formal_cr2_theta_packets")
DEFAULT_POST_VALIDATION_DIR = Path("/home/lacp/agent/validation_queries/formal_post_validation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a CR2 theta formula input packet.")
    parser.add_argument("--run-ids", nargs="+", required=True, help="Accepted CR2 run IDs, comma or space separated.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--post-validation-dir", type=Path, default=DEFAULT_POST_VALIDATION_DIR)
    parser.add_argument("--expected-run-count", type=int, default=3)
    parser.add_argument("--allow-draft", action="store_true", help="Allow fewer than expected-run-count run IDs.")
    return parser.parse_args()


def split_run_ids(raw_items: list[str]) -> list[str]:
    run_ids: list[str] = []
    for item in raw_items:
        run_ids.extend(part.strip() for part in item.split(",") if part.strip())
    seen: set[str] = set()
    unique = []
    for run_id in run_ids:
        if run_id not in seen:
            unique.append(run_id)
            seen.add(run_id)
    return unique


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_post_validation(post_dir: Path, run_id: str) -> dict[str, Any]:
    path = post_dir / f"{run_id}_post_validation.json"
    if not path.exists():
        raise FileNotFoundError(f"missing post-validation JSON for {run_id}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    if summary.get("status") != "pass":
        raise RuntimeError(f"post-validation is not pass for {run_id}: {summary.get('status')}")
    if summary.get("expected_turns") != 30 or summary.get("expected_row_count") != 90:
        raise RuntimeError(
            f"unexpected CR2 post-validation shape for {run_id}: "
            f"turns={summary.get('expected_turns')} rows={summary.get('expected_row_count')}"
        )
    integrity = summary.get("cr2_intervention_calibration_integrity")
    if not isinstance(integrity, dict) or integrity.get("status") != "pass":
        raise RuntimeError(f"CR2 intervention calibration integrity is not pass for {run_id}")
    return {"path": str(path), "sha256": file_sha256(path), "summary": summary}


def describe_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean(ordered),
        "p50": stage_runner.percentile(ordered, 0.50),
        "p70": stage_runner.percentile(ordered, 0.70),
        "p95": stage_runner.percentile(ordered, 0.95),
    }


def write_markdown(path: Path, packet: dict[str, Any], sidecar_name: str) -> None:
    calibration = packet["calibration"]
    theta_values = calibration["theta_values"]
    entropy_values = calibration["entropy_values"]
    non_trigger_turns = calibration["non_trigger_eligible_turns"]
    summaries = packet["value_summaries"]
    run_ids = packet["run_ids"]

    machine_block = {
        "packet_id": packet["packet_id"],
        "stage": "cr2",
        "status": packet["status"],
        "run_ids": run_ids,
        "expected_rows_per_metric": packet["expected_rows_per_metric"],
        "theta_value_inputs_json": sidecar_name,
        "auto_frozen_theta": packet["auto_frozen_theta"],
        "non_trigger_eligible_turns": non_trigger_turns,
        "pooled_shared_floor": True,
        "sign_aware_supporting_evidence": True,
        "theta_ma_status": packet["auto_frozen_theta"].get("theta_ma_status"),
    }

    lines = [
        "# CR2 Theta Formula Review Packet",
        "",
        f"- packet_id: `{packet['packet_id']}`",
        f"- status: `{packet['status']}`",
        f"- created_at_utc: `{packet['created_at_utc']}`",
        f"- scenario: `{packet['scenario']['scenario_id']}`",
        f"- scenario_hash: `{packet['scenario']['scenario_hash']}`",
        f"- run_count: `{len(run_ids)}`",
        f"- expected_rows_per_metric: `{packet['expected_rows_per_metric']}`",
        f"- raw_input_json: `{sidecar_name}`",
        "",
        "## Accepted CR2 Runs",
        "",
    ]
    for run_id in run_ids:
        post = packet["post_validation"][run_id]
        lines.append(f"- `{run_id}`: post_validation_sha256 `{post['sha256']}`")

    lines.extend(
        [
            "",
            "## Value Summaries",
            "",
            "| input | count | min | p50 | p70 | p95 | max | mean |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key in ["d_lms_abs", "d_cds_abs", "d_ma_abs", "d_lms_signed", "d_cds_signed", "d_ma_signed", "entropy_values"]:
        item = summaries[key]
        lines.append(
            f"| {key} | {item.get('count', 0)} | {item.get('min', '')} | {item.get('p50', '')} | "
            f"{item.get('p70', '')} | {item.get('p95', '')} | {item.get('max', '')} | {item.get('mean', '')} |"
        )

    lines.extend(
        [
            "",
            "## Direction Convention",
            "",
            "- d_lms = LMS_X - LMS_C for X in {A,B}",
            "- d_cds = CDS_C - CDS_X for X in {A,B}",
            "- d_ma = MA_assert_X - MA_assert_C for X in {A,B}",
            "- theta_entropy is derived from the natural CR2 token entropy distribution.",
            "- A/B Node C-relative CR2 differentials are pooled as a conservative shared intervention-effect floor.",
            "- Run B/CF supporting-evidence counts must be sign-aware; opposite-direction absolute exceedance is reported as deviation, not supportive evidence.",
            "- For MA, reduced unsafe final-decision-like assertiveness is the RBC/SC-supportive interpretation direction.",
            "",
            "## Auto-Frozen Theta Values",
            "",
            "These are the values currently frozen by the CR2 completion step before professor review.",
            "",
            "```json",
            json.dumps(packet["auto_frozen_theta"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## CR2 Routing Integrity",
            "",
            "Each accepted CR2 run must pass the wiring gate: Node A RAG+SC/RBPC, Node B RAG-only, Node C baseline.",
            "",
        ]
    )
    for run_id in run_ids:
        integrity = packet["post_validation"][run_id]["summary"].get("cr2_intervention_calibration_integrity", {})
        lines.append(f"- `{run_id}`: `{integrity.get('status')}`")

    lines.extend(
        [
            "",
            "## CF-F Non-Trigger Eligible Turns",
            "",
            ", ".join(str(turn) for turn in non_trigger_turns) if non_trigger_turns else "`none`",
            "",
            "## Machine Readable Handoff",
            "",
            "```json theta-formula-packet",
            json.dumps(machine_block, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Professor Feedback Slot",
            "",
            "- Please review whether the auto-frozen theta formula and percentile rules are acceptable.",
            "- If a revised formula is required, record the exact formula and whether the existing Run B freeze should be replaced before formal Run B.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_ids = split_run_ids(args.run_ids)
    if len(run_ids) != args.expected_run_count and not args.allow_draft:
        raise SystemExit(
            f"expected exactly {args.expected_run_count} accepted CR2 run IDs; got {len(run_ids)}. "
            "Use --allow-draft only for interim review packets."
        )

    scenario = stage_runner.load_scenario(stage_runner.DEFAULT_SCENARIO)
    turns = len(scenario["turns"])
    expected_rows_per_metric = turns * len(run_ids) * 2
    calibration = stage_runner.fetch_cr2_metric_values(run_ids)
    metadata = stage_runner.fetch_cr2_run_metadata(run_ids)
    auto_theta = stage_runner.build_theta_config(
        run_ids,
        calibration,
        expected_rows_per_metric,
        stage_runner.DEFAULT_ENTROPY_PERCENTILE,
        stage_runner.DEFAULT_TRIGGER_PERCENTILE,
        metadata,
    )

    post_validation = {
        run_id: load_post_validation(args.post_validation_dir, run_id)
        for run_id in run_ids
    }
    theta_values = calibration["theta_values"]
    entropy_values = calibration["entropy_values"]
    summaries = {
        "d_lms_abs": describe_values(theta_values["d_lms_abs"]),
        "d_cds_abs": describe_values(theta_values["d_cds_abs"]),
        "d_ma_abs": describe_values(theta_values["d_ma_abs"]),
        "entropy_values": describe_values(entropy_values),
    }
    packet_id = f"cr2_theta_formula_packet_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    packet = {
        "packet_id": packet_id,
        "status": "complete" if len(run_ids) == args.expected_run_count else "draft",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_ids": run_ids,
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "scenario_hash": scenario["scenario_hash"],
            "source_file": scenario["source_file"],
            "turns": turns,
        },
        "expected_rows_per_metric": expected_rows_per_metric,
        "calibration": calibration,
        "metadata": metadata,
        "auto_frozen_theta": {
            "theta_entropy": auto_theta["theta_entropy"],
            "theta_lms": auto_theta["theta_lms"],
            "theta_cds": auto_theta["theta_cds"],
            "theta_ma": auto_theta["theta_ma"],
            "theta_ma_status": auto_theta.get("theta_ma_status"),
            "theta_ma_threshold_evidence_enabled": auto_theta.get("theta_ma_threshold_evidence_enabled"),
            "source": auto_theta["source"],
            "locked": auto_theta["locked"],
            "percentile_rule": auto_theta["percentile_rule"],
            "direction_convention": auto_theta["direction_convention"],
        },
        "post_validation": post_validation,
        "value_summaries": summaries,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{packet_id}.json"
    md_path = args.output_dir / f"{packet_id}.md"
    json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(md_path, packet, json_path.name)
    print(f"cr2_theta_formula_packet_md={md_path}")
    print(f"cr2_theta_formula_packet_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
