#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fail-fast readiness check for Formal CF stage design alignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


CF_PLAN_ID = "lacp_cf_scenario_plan_v4_cff_turnset_final"
CF_F_DEFAULT_TURNS = [3, 6, 9, 12, 15, 18, 21, 24, 27, 29]
CF_D_DEFAULT_TURNS = [5, 15, 25]
CF_STAGES = {"cf_a", "cf_b", "cf_c", "cf_d", "cf_e", "cf_f"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Formal CF design readiness.")
    parser.add_argument("--stage", required=True, help="cf_a|cf_b|cf_c|cf_d|cf_e|cf_f|all")
    parser.add_argument("--node-config-path", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--run-experiment-stage", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stages = sorted(CF_STAGES) if args.stage == "all" else [args.stage]
    config = load_config(args.node_config_path)
    scenario = load_config(args.scenario)
    run_stage_text = args.run_experiment_stage.read_text(encoding="utf-8")
    summary = validate(stages, config, scenario, run_stage_text)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "pass" else 2


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"{path} is not JSON and PyYAML is unavailable") from exc
        loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} did not load as an object")
    return loaded


def validate(
    stages: list[str],
    config: dict[str, Any],
    scenario: dict[str, Any],
    run_stage_text: str,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    stage_summaries: dict[str, dict[str, Any]] = {}

    unknown = [stage for stage in stages if stage not in CF_STAGES]
    for stage in unknown:
        failures.append(f"Unsupported CF stage: {stage}")
    stages = [stage for stage in stages if stage in CF_STAGES]

    cf_cfg = config.get("counterfactual") if isinstance(config.get("counterfactual"), dict) else {}
    validate_common(config, scenario, cf_cfg, run_stage_text, failures)

    for stage in stages:
        stage_failures: list[str] = []
        stage_warnings: list[str] = []
        validate_stage(stage, cf_cfg, run_stage_text, stage_failures, stage_warnings)
        failures.extend(f"{stage}: {item}" for item in stage_failures)
        warnings.extend(f"{stage}: {item}" for item in stage_warnings)
        stage_summaries[stage] = {
            "status": "pass" if not stage_failures else "blocked",
            "failures": stage_failures,
            "warnings": stage_warnings,
        }

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "warnings": warnings,
        "stages": stage_summaries,
        "cf_plan_id": cf_cfg.get("cf_plan_id"),
        "scenario_id": scenario.get("scenario_id"),
    }


def validate_common(
    config: dict[str, Any],
    scenario: dict[str, Any],
    cf_cfg: dict[str, Any],
    run_stage_text: str,
    failures: list[str],
) -> None:
    nodes = config.get("nodes") if isinstance(config.get("nodes"), dict) else {}
    roles = {str(node).upper(): str(meta.get("role") or "").strip().lower() for node, meta in nodes.items()}
    expected_roles = {"A": "rag_sc", "B": "rag_only", "C": "baseline"}
    for node, role in expected_roles.items():
        if roles.get(node) != role:
            failures.append(f"Node {node} role must be {role}, got {roles.get(node)!r}")

    if cf_cfg.get("cf_plan_id") != CF_PLAN_ID:
        failures.append(f"counterfactual.cf_plan_id must be {CF_PLAN_ID}, got {cf_cfg.get('cf_plan_id')!r}")
    if scenario.get("cf_plan_id") != CF_PLAN_ID:
        failures.append(f"scenario cf_plan_id must be {CF_PLAN_ID}, got {scenario.get('cf_plan_id')!r}")
    if scenario.get("source_scenario") != "lacp_run_b_scenario_v1":
        failures.append(f"scenario source_scenario must be lacp_run_b_scenario_v1, got {scenario.get('source_scenario')!r}")
    if scenario.get("utterance_sequence_changed") is not False:
        failures.append("CF scenario must declare utterance_sequence_changed=false")
    turns = scenario.get("turns")
    if not isinstance(turns, list) or len(turns) != 30:
        failures.append(f"CF scenario must contain exactly 30 turns, got {len(turns) if isinstance(turns, list) else 'non-list'}")
    else:
        observed_turns = [turn.get("turn_no") for turn in turns if isinstance(turn, dict)]
        if observed_turns != list(range(1, 31)):
            failures.append(f"CF scenario turn_no sequence must be 1..30, got {observed_turns}")

    if "cf_e" not in run_stage_text or "cf_f" not in run_stage_text:
        failures.append("run_experiment_stage.py must define cf_e and cf_f stages")


def validate_stage(
    stage: str,
    cf_cfg: dict[str, Any],
    run_stage_text: str,
    failures: list[str],
    warnings: list[str],
) -> None:
    stage_cfg = cf_cfg.get(stage) if isinstance(cf_cfg.get(stage), dict) else {}
    if stage == "cf_a" and stage_cfg.get("mode") != "rag_off_sc_off_baseline_replay":
        failures.append(f"mode must be rag_off_sc_off_baseline_replay, got {stage_cfg.get('mode')!r}")
    if stage == "cf_b" and stage_cfg.get("mode") != "rag_only_forced_across_ab_sc_off":
        failures.append(f"mode must be rag_only_forced_across_ab_sc_off, got {stage_cfg.get('mode')!r}")
    if stage == "cf_c" and stage_cfg.get("mode") != "sc_only_rag_off":
        failures.append(f"mode must be sc_only_rag_off, got {stage_cfg.get('mode')!r}")
    if stage == "cf_d":
        if stage_cfg.get("forced_turns") != CF_D_DEFAULT_TURNS:
            failures.append(f"forced_turns must be {CF_D_DEFAULT_TURNS}, got {stage_cfg.get('forced_turns')!r}")
    if stage == "cf_e":
        query = stage_cfg.get("external_payload_query")
        if not isinstance(query, str) or not query.strip():
            failures.append("external_payload_query must be frozen before CF-E execution")
        expected_hash = stage_cfg.get("external_payload_query_hash")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            failures.append("external_payload_query_hash must be a 64-character sha256 hex digest")
        elif isinstance(query, str) and query.strip():
            observed_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
            if observed_hash != expected_hash:
                failures.append(
                    f"external_payload_query_hash mismatch: expected {expected_hash}, got {observed_hash}"
                )
        source = stage_cfg.get("external_payload_source")
        if not isinstance(source, str) or not source.strip():
            failures.append("external_payload_source must document the irrelevant/excluded source category")
        manifest = stage_cfg.get("external_payload_freeze_manifest")
        if not isinstance(manifest, str) or not manifest.strip():
            failures.append("external_payload_freeze_manifest must name the CF-E freeze artifact")
        retrieval_status = stage_cfg.get("retrieval_chunk_freeze_status")
        allowed_retrieval_statuses = {
            "pending_live_rag_node_verification",
            "live_rag_topk_frozen_20260629",
        }
        if retrieval_status not in allowed_retrieval_statuses:
            warnings.append(
                "retrieval_chunk_freeze_status should be pending or match the recorded live rag-node top-k freeze"
            )
        if stage_cfg.get("model_weights_fixed") is not True:
            failures.append("model_weights_fixed must be true")
    if stage == "cf_f":
        if stage_cfg.get("condition_label") not in {"default", "cf_f_default"}:
            failures.append(f"condition_label must be default/cf_f_default, got {stage_cfg.get('condition_label')!r}")
        if stage_cfg.get("injection_turns") != CF_F_DEFAULT_TURNS:
            failures.append(f"injection_turns must be {CF_F_DEFAULT_TURNS}, got {stage_cfg.get('injection_turns')!r}")
        if stage_cfg.get("turn_30_forced") is not False:
            failures.append("turn_30_forced must be false for default CF-F")
        if stage_cfg.get("turn_29_runtime_smoke_required") is not True:
            failures.append("turn_29_runtime_smoke_required must be true")
        if "repetitions=10" not in run_stage_text:
            failures.append("run_experiment_stage.py cf_f StageSpec must use repetitions=10")
    if not failures and not warnings:
        warnings.append("stage-specific static readiness checks passed")


if __name__ == "__main__":
    sys.exit(main())
