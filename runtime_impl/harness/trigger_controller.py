#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shared catch-trigger controller for LACP Harness.

Formal Run B uses this controller to decide whether A/B receive the same RAG
chunks. The controller monitors previous metrics from Node A and Node B only;
Node C is never a trigger source and never receives intervention.
"""

from __future__ import annotations

from typing import Any, Dict, List


class TriggerController:
    def __init__(self, sc_policy_engine, config: Dict[str, Any]):
        self.sc_policy_engine = sc_policy_engine
        self.config = config

    def evaluate_shared_trigger(
        self,
        previous_metrics: Dict[str, Dict[str, Any]],
        turn_no: int,
        condition: str,
        run_mode: str,
    ) -> Dict[str, Any]:
        mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
        threshold_snapshot = self.sc_policy_engine.threshold_snapshot()

        base = {
            "should_inject_rag": False,
            "apply_sc_to_a": False,
            "apply_sc_to_b": False,
            "reasons": [],
            "trigger_source_nodes": [],
            "threshold_snapshot": threshold_snapshot,
            "mode": "metric_catch_trigger",
            "previous_turn_used_for_trigger": turn_no - 1 if turn_no > 1 else None,
        }

        if condition != "run_b":
            return base

        if run_mode == "smoke" and mode_cfg.get("force_intervention_run_b", False):
            return {
                **base,
                "should_inject_rag": True,
                "apply_sc_to_a": True,
                "reasons": ["smoke_force_run_b"],
                "trigger_source_nodes": ["A", "B"],
                "mode": "smoke_force_run_b",
            }

        if turn_no == 1 and not previous_metrics:
            if self.config.get("run", {}).get("bootstrap_first_turn", False):
                return {
                    **base,
                    "should_inject_rag": True,
                    "apply_sc_to_a": True,
                    "reasons": ["bootstrap_first_turn"],
                    "trigger_source_nodes": ["A", "B"],
                    "mode": "bootstrap_first_turn",
                }
            return base

        if mode_cfg.get("require_metric_trigger", False):
            self._validate_required_metrics(previous_metrics, run_mode)

        reasons: List[str] = []
        source_nodes: List[str] = []
        for node in ("A", "B"):
            metrics = previous_metrics.get(node, {})
            policy_metrics = self._metrics_available_for_trigger_policy(metrics)
            decision = self.sc_policy_engine.evaluate_trigger(policy_metrics)
            if decision.should_inject_rag:
                source_nodes.append(node)
                for reason in decision.reasons:
                    detail = self._reason_detail(reason)
                    reasons.append(f"{node}.{detail}")

        should_inject = bool(reasons)
        return {
            **base,
            "should_inject_rag": should_inject,
            "apply_sc_to_a": should_inject,
            "apply_sc_to_b": False,
            "reasons": reasons,
            "trigger_source_nodes": source_nodes,
        }

    def _validate_required_metrics(self, previous_metrics: Dict[str, Dict[str, Any]], run_mode: str) -> None:
        required_nodes = ("A", "B")
        for node in required_nodes:
            if node not in previous_metrics:
                raise ValueError(f"Formal trigger requires previous metrics for Node {node}")
            metrics = previous_metrics[node]
            if metrics.get("exclude_from_causal_trigger") or metrics.get("analysis_eligible") is False:
                raise ValueError(f"Formal trigger previous metrics for Node {node} are excluded from causal trigger")
            missing = []
            policy_metrics = self._metrics_available_for_trigger_policy(metrics)
            for name in ("d_cds", "d_ma"):
                if policy_metrics.get(name) is None:
                    missing.append(name)
            eligibility = metrics.get("metric_trigger_eligibility", {})
            lms_trigger_blocked = isinstance(eligibility, dict) and eligibility.get("lms_trigger_eligible") is False
            # A missing LMS/LMS_delta value is a blocking error only when the
            # row claims LMS trigger eligibility. If logprobs are absent, the
            # Metrics layer marks lms_trigger_eligible=false and this validator
            # treats the LMS family as intentionally unavailable instead of
            # failing the whole turn. This matches the execution policy:
            # missing logprobs should be uncommon after formal preflight, but a
            # single occurrence should invalidate LMS evidence for that
            # node-turn, not automatically invalidate CDS/MA evidence.
            if (
                policy_metrics.get("lms_delta") is None
                and policy_metrics.get("d_lms") is None
                and not lms_trigger_blocked
                and not self.config.get("metrics", {}).get("lms", {}).get(
                    "allow_unavailable_for_trigger", False
                )
            ):
                missing.append("lms_delta")
            if missing:
                raise ValueError(f"Formal trigger missing metrics for Node {node}: {', '.join(missing)}")

    def _metrics_available_for_trigger_policy(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        filtered = dict(metrics)
        eligibility = metrics.get("metric_trigger_eligibility", {})
        if not isinstance(eligibility, dict):
            eligibility = {}

        # Trigger exclusion is a row-level circuit breaker: the observation is
        # still stored, but no metric from that row may influence intervention
        # timing. This is separate from history eligibility.
        if metrics.get("exclude_from_causal_trigger") or metrics.get("analysis_eligible") is False:
            for name in ("lms_delta", "d_lms", "cds", "d_cds", "ma_assert", "d_ma"):
                filtered[name] = None
            return filtered

        # Logprob absence invalidates LMS/LMS_delta trigger evidence only. The
        # expected formal path should provide logprobs, so this branch is a
        # guarded failure path for endpoint drift, node response schema drift,
        # timeout/partial-response cases, or preflight escape. CDS and MA remain
        # available when their own metric-specific eligibility is true, which
        # avoids over-excluding otherwise useful trigger evidence.
        if eligibility.get("lms_trigger_eligible") is False:
            filtered["lms_delta"] = None
            filtered["d_lms"] = None
        if eligibility.get("cds_trigger_eligible") is False:
            filtered["cds"] = None
            filtered["d_cds"] = None
        if eligibility.get("ma_trigger_eligible") is False:
            filtered["ma_assert"] = None
            filtered["d_ma"] = None
        return filtered

    @staticmethod
    def _reason_detail(reason: str) -> str:
        if reason == "low_confidence":
            return "low_confidence:d_lms>theta_lms"
        if reason == "context_drift":
            return "context_drift:d_cds>theta_cds"
        if reason == "weak_assertion":
            return "weak_assertion:d_ma>theta_ma"
        return reason
