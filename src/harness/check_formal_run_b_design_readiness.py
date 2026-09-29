#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fail-fast readiness check for Formal Run B intervention design.

This check is intentionally local/read-only. It prevents a formal Run B launch
when the configured trigger path can enter a no-intervention fixed point before
any RAG/SC exposure is realized.
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

    if force_intervention:
        design_mode = "forced_intervention_exposure"
    elif bootstrap_first_turn and require_metric_trigger:
        design_mode = "metric_triggered_with_bootstrap"
    elif bootstrap_first_turn:
        design_mode = "bootstrap_intervention_exposure"
        warnings.append("bootstrap_first_turn=true but require_metric_trigger=false")
    else:
        design_mode = "no_initial_intervention_exposure"
        failures.append(
            "Formal Run B has neither force_intervention_run_b nor bootstrap_first_turn; "
            "metric-triggered routing can enter a no-intervention fixed point"
        )

    return {
        "status": "pass" if not failures else "blocked",
        "failures": failures,
        "warnings": warnings,
        "run_mode": run_mode,
        "design_mode": design_mode,
        "force_intervention_run_b": force_intervention,
        "bootstrap_first_turn": bootstrap_first_turn,
        "require_metric_trigger": require_metric_trigger,
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
