#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fail-fast readiness check for Formal Run B intervention design.

This check is intentionally local/read-only. It prevents a formal Run B launch
when the configured path can enter a no-intervention fixed point or when it
would force SC outside the pre-registered trigger-gated design.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Formal Run B design readiness.")
    parser.add_argument("--node-config-path", type=Path, required=True)
    parser.add_argument("--run-mode", default="formal")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.node_config_path)
    summary = validate_design(config, args.run_mode)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "pass" else 2


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"{path} is not JSON and PyYAML is unavailable") from exc
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise RuntimeError(f"{path} did not load as an object")
        return loaded


def validate_design(config: dict[str, Any], run_mode: str) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    nodes = config.get("nodes") if isinstance(config.get("nodes"), dict) else {}
    roles = {str(node).upper(): str(meta.get("role") or "").strip().lower() for node, meta in nodes.items()}
    run_cfg = config.get("run") if isinstance(config.get("run"), dict) else {}
    mode_cfg = config.get("run_modes", {}).get(run_mode, {}) if isinstance(config.get("run_modes"), dict) else {}
    rag_cfg = config.get("rag") if isinstance(config.get("rag"), dict) else {}

    expected_roles = {"A": "rag_sc", "B": "rag_only", "C": "baseline"}
    for node, role in expected_roles.items():
        if roles.get(node) != role:
            failures.append(f"Node {node} role must be {role}, got {roles.get(node)!r}")

    if not bool(run_cfg.get("sc_enabled", True)):
        failures.append("Formal Run B requires run.sc_enabled=true for Node A SC exposure")
    if not str(rag_cfg.get("collection") or "").strip():
        failures.append("Formal Run B requires rag.collection to be set")

    force_intervention = bool(mode_cfg.get("force_intervention_run_b", False))
    bootstrap_first_turn = bool(run_cfg.get("bootstrap_first_turn", False))
    require_metric_trigger = bool(mode_cfg.get("require_metric_trigger", False))
    intervention_mode = str(run_cfg.get("intervention_mode") or "").strip()

    if force_intervention:
        design_mode = "forced_intervention_exposure"
        failures.append("Formal Run B must not use force_intervention_run_b; forced assignment belongs to smoke/CF paths")
    elif intervention_mode != "fixed_rag_exposure":
        design_mode = "missing_fixed_ab_rag_exposure"
        failures.append("Formal Run B requires run.intervention_mode=fixed_rag_exposure for A/B RAG exposure")
    elif bootstrap_first_turn:
        design_mode = "bootstrap_sc_exposure"
        failures.append("Formal Run B must not bootstrap first-turn SC; turn 1 has no prior delta metrics")
    elif not require_metric_trigger:
        design_mode = "fixed_rag_without_sc_trigger_gate"
        failures.append("Formal Run B requires formal.require_metric_trigger=true for trigger-gated SC")
    elif not bool(mode_cfg.get("request_logprobs", False)) and not bool(config.get("model", {}).get("request_logprobs", False)):
        design_mode = "fixed_rag_trigger_gate_without_logprobs"
        failures.append("Formal Run B requires logprobs for LMS trigger evidence")
    else:
        design_mode = "fixed_rag_exposure_trigger_gated_sc"

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "warnings": warnings,
        "run_mode": run_mode,
        "design_mode": design_mode,
        "force_intervention_run_b": force_intervention,
        "bootstrap_first_turn": bootstrap_first_turn,
        "require_metric_trigger": require_metric_trigger,
        "intervention_mode": intervention_mode,
        "roles": roles,
        "rag_collection": rag_cfg.get("collection"),
        "sc_enabled": bool(run_cfg.get("sc_enabled", True)),
    }


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"formal_run_b_design_readiness_error: {exc}", file=sys.stderr)
        raise SystemExit(2)
