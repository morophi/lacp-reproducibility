#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SC-Protocol policy engine for the Harness layer.

SC-Protocol is implemented only as a deterministic, versioned operating policy
block and trigger-governance reader. It is not a model, evaluator, inference
server, post-processor, or permanent Node A configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from config_utils import load_config, normalized_json_hash


@dataclass(frozen=True)
class TriggerDecision:
    should_inject_rag: bool
    reasons: List[str]
    policy_id: str
    policy_hash: str
    threshold_snapshot: Dict[str, Any]


class SCPolicyEngine:
    def __init__(self, policy_path: str, theta_path: str):
        self._policy = load_config(policy_path)
        self._theta = load_config(theta_path)
        self._validate()
        self._policy_block = self.build_policy_block()
        self._policy_hash = self._compute_policy_hash()

    @property
    def policy_id(self) -> str:
        return str(self._policy["policy_id"])

    @property
    def policy_hash(self) -> str:
        return self._policy_hash

    @property
    def theta_locked(self) -> bool:
        return bool(self._theta.get("locked"))

    def threshold_snapshot(self) -> Dict[str, Any]:
        required = self._required_threshold_refs()
        return {key: self._theta[key] for key in required}

    def build_policy_block(self) -> str:
        label = self._policy["prompt_policy"].get("block_label", "SC-PROTOCOL OPERATING POLICY")
        lines = [
            f"[{label}]",
            f"policy_id: {self.policy_id}",
            "- Ground eligibility-related statements in retrieved policy evidence when available.",
            "- Do not present the answer as a final administrative decision.",
            "- If retrieved evidence is insufficient, state what must be verified.",
            "- Maintain the boundary that final responsibility belongs to the human/public officer.",
            "- Do not make unverified eligibility determinations.",
            f"[/{label}]",
        ]
        block = "\n".join(lines)
        max_chars = int(self._policy["prompt_policy"].get("max_policy_block_chars", 1200))
        if len(block) > max_chars:
            raise ValueError(f"SC policy block exceeds max_policy_block_chars={max_chars}")
        forbidden = ("more confidently", "increase confidence", "more assertive", "increase assertiveness")
        if any(term in block.lower() for term in forbidden):
            raise ValueError("SC policy block contains forbidden confidence/assertiveness instruction")
        return block

    def evaluate_trigger(self, metrics: Dict[str, Any]) -> TriggerDecision:
        rules = self._policy.get("trigger_rules", {})
        if not rules.get("enabled", False):
            return TriggerDecision(False, [], self.policy_id, self.policy_hash, self.threshold_snapshot())

        matches = []
        conditions = rules.get("conditions", [])
        for condition in conditions:
            name = condition["name"]
            metric_name = condition["metric"]
            operator = condition["operator"]
            threshold_ref = condition["threshold_ref"]
            if metric_name not in metrics or metrics[metric_name] is None:
                continue
            if threshold_ref not in self._theta:
                raise ValueError(f"Missing threshold value: {threshold_ref}")
            if self._compare(metrics[metric_name], operator, self._theta[threshold_ref]):
                matches.append(name)

        logic = str(rules.get("logic", "OR")).upper()
        if logic == "OR":
            should_inject = bool(matches)
        elif logic == "AND":
            should_inject = len(matches) == len(conditions) and bool(conditions)
        else:
            raise ValueError(f"Unsupported trigger logic: {logic}")

        return TriggerDecision(should_inject, matches, self.policy_id, self.policy_hash, self.threshold_snapshot())

    def _compute_policy_hash(self) -> str:
        normalized = {
            "policy": self._policy,
            "policy_block": self._policy_block,
        }
        return normalized_json_hash(normalized)

    def _required_threshold_refs(self) -> List[str]:
        refs = []
        for condition in self._policy.get("trigger_rules", {}).get("conditions", []):
            ref = condition.get("threshold_ref")
            if ref:
                refs.append(ref)
        return sorted(set(refs))

    def _validate(self) -> None:
        for key in ("policy_id", "policy_role", "prompt_policy", "trigger_rules"):
            if key not in self._policy:
                raise ValueError(f"Missing SC policy field: {key}")
        if self._policy.get("policy_role") != "operational_policy":
            raise ValueError("SC policy role must be operational_policy")
        for ref in self._required_threshold_refs():
            if ref not in self._theta:
                raise ValueError(f"Missing theta threshold: {ref}")
            if not isinstance(self._theta[ref], (int, float)):
                raise ValueError(f"Theta threshold must be numeric: {ref}")

    @staticmethod
    def _compare(left: Any, operator: str, right: Any) -> bool:
        if operator == "<":
            return left < right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        if operator == ">=":
            return left >= right
        if operator == "==":
            return left == right
        raise ValueError(f"Unsupported operator: {operator}")
