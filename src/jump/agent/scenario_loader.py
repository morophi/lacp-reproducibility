#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LACP Scenario Agent loader.

Reason for this module:
  The agent/jump node must remain a deterministic utterance supplier only.
  It reads existing scenario JSON, validates shape, computes provenance hashes,
  and never rewrites scenario content or builds experiment prompts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def compute_file_sha256(path: str) -> str:
    scenario_path = Path(path)
    with scenario_path.open("rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _derive_scenario_id(path: str) -> str:
    return Path(path).stem


def _coerce_turn_no(item: Dict[str, Any], fallback: int) -> int:
    value = item.get("turn_no", item.get("turn", fallback))
    if not isinstance(value, int):
        raise ValueError(f"turn_no must be an integer at turn index {fallback}")
    return value


def _extract_turns(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("turns"), list):
        return data["turns"]
    raise ValueError("Scenario JSON must be a list of turns or an object with a turns list")


def validate_scenario(data: Dict[str, Any]) -> None:
    if not data.get("scenario_id"):
        raise ValueError("scenario_id is required in the loaded scenario object")

    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("turns must exist and be a non-empty list")

    seen_turns = set()
    for idx, item in enumerate(turns, 1):
        if not isinstance(item, dict):
            raise ValueError(f"turn item at index {idx} must be an object")
        turn_no = _coerce_turn_no(item, idx)
        if turn_no in seen_turns:
            raise ValueError(f"duplicate turn_no detected: {turn_no}")
        seen_turns.add(turn_no)
        if "utterance" not in item or not isinstance(item["utterance"], str) or item["utterance"] == "":
            raise ValueError(f"turn {turn_no} is missing a non-empty utterance")


def load_scenario(path: str) -> Dict[str, Any]:
    scenario_path = Path(path)
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    with scenario_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_turns = _extract_turns(raw_data)
    scenario_id = raw_data.get("scenario_id") if isinstance(raw_data, dict) else None
    condition = raw_data.get("condition") if isinstance(raw_data, dict) else None

    normalized_turns = []
    for idx, item in enumerate(raw_turns, 1):
        turn_copy = copy.deepcopy(item)
        turn_copy["turn_no"] = _coerce_turn_no(turn_copy, idx)
        if "utterance" not in turn_copy and isinstance(turn_copy.get("text"), str):
            turn_copy["utterance"] = turn_copy["text"]
        normalized_turns.append(turn_copy)

    scenario = {
        "scenario_id": scenario_id or _derive_scenario_id(path),
        "condition": condition,
        "source_file": str(scenario_path),
        "scenario_hash": compute_file_sha256(path),
        "turns": sorted(normalized_turns, key=lambda t: t["turn_no"]),
    }
    validate_scenario(scenario)
    return scenario
