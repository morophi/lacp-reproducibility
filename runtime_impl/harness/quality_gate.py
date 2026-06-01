#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic generation quality gate for LACP Harness.

This module never rewrites model output. It separates infrastructure success
from generation quality, preserves bad responses as observable quality
outcomes, and prevents contaminated node-turns from driving later causal
triggers.

Eligibility policy:
  analysis_eligible decides whether a row can enter causal/statistical result
  analysis, exclude_from_causal_trigger decides whether the row can influence
  later intervention timing, and history_eligible decides whether the model
  response may be carried into the next turn's conversational context. These
  are deliberately separate because a row can be unsuitable for analysis while
  still being a meaningful part of the observed dialogue.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# Keep these literals escaped so the rule set is stable across terminals,
# editors, and SSH hops that may not render Korean/Chinese text consistently.
HARD_CONTAMINATION_PATTERNS = (
    "\u7684\u5730\u65b9",  # 的地方
    "\u6216\u8005",  # 或者
    "\u53ef\u4ee5",  # 可以
    "\u9700\u8981",  # 需要
    "\u529e\u7406",  # 办理
    "\uad00\ud560\u7684",  # 관할的
)

WARNING_CONTAMINATION_REGEX = (
    re.compile(r"[\u3040-\u30ff]+"),  # Japanese kana
    re.compile(r"[\u4e00-\u9fff]{2,}"),  # contiguous CJK ideographs
)

APPLICATION_OFFICE_QUERY_TERMS = (
    "\uc2e0\uccad",
    "\uc5b4\ub514",
    "\uc5b4\ub514\uc11c",
    "\ucc3d\uad6c",
    "\uc811\uc218",
)

APPLICATION_OFFICE_EXPECTED = (
    "\uc74d\u00b7\uba74\u00b7\ub3d9",
    "\uc74d\uba74\ub3d9",
    "\ud589\uc815\ubcf5\uc9c0\uc13c\ud130",
    "\uc8fc\ubbfc\uc13c\ud130",
    "\uc8fc\uc18c\uc9c0 \uad00\ud560",
)

APPLICATION_OFFICE_SUSPICIOUS = (
    "\uc0ac\ud68c\ubcf5\uc9c0\uad00",
    "\ubcf5\uc9c0\uad00",
    "\uc9c0\ubc29\uc0ac\ud68c\ubcf5\uc9c0\uad00",
    "\uace0\uc6a9\ub178\ub3d9\ubd80",
    "\ub178\ub3d9\ubd80",
)

APPLICATION_OFFICE_CLAIM_ENDINGS = (
    "\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4",
    "\uac00\ub2a5\ud569\ub2c8\ub2e4",
    "\ud569\ub2c8\ub2e4",
)


def _find_contamination_spans(text: str) -> List[str]:
    spans: List[str] = []
    for pattern in HARD_CONTAMINATION_PATTERNS:
        if pattern in text:
            spans.append(pattern)
    for regex in WARNING_CONTAMINATION_REGEX:
        spans.extend(match.group(0) for match in regex.finditer(text))
    return sorted(set(spans))


def _is_application_office_query(utterance: str) -> bool:
    return "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5" in utterance and any(
        term in utterance for term in APPLICATION_OFFICE_QUERY_TERMS
    )


def _has_suspicious_application_claim(clean_text: str, suspicious_terms: List[str]) -> bool:
    """Detect a suspicious institution being asserted as an application venue.

    The Harness must not correct a bad answer, but it must mark that answer as
    unsafe for causal trigger reuse. This deliberately uses broad deterministic
    text rules because the known failure mode may span more than a short regex
    window: "신청은 ... 복지관에서 할 수 있습니다".
    """

    if not suspicious_terms or "\uc2e0\uccad" not in clean_text:
        return False
    if not any(ending in clean_text for ending in APPLICATION_OFFICE_CLAIM_ENDINGS):
        return False
    return any(term in clean_text for term in suspicious_terms)


def _policy_anchor_check(clean_text: str, utterance: str) -> Dict[str, Any]:
    if not _is_application_office_query(utterance):
        return {
            "policy_anchor_checked": False,
            "policy_anchor_pass": None,
            "policy_anchor_expected": [],
            "policy_anchor_found": [],
            "suspicious_policy_terms": [],
            "suspicious_application_claim": False,
        }

    found = [term for term in APPLICATION_OFFICE_EXPECTED if term in clean_text]
    suspicious = [term for term in APPLICATION_OFFICE_SUSPICIOUS if term in clean_text]
    suspicious_application_claim = _has_suspicious_application_claim(clean_text, suspicious)
    return {
        "policy_anchor_checked": True,
        "policy_anchor_pass": bool(found) and not suspicious_application_claim,
        "policy_anchor_expected": list(APPLICATION_OFFICE_EXPECTED),
        "policy_anchor_found": found,
        "suspicious_policy_terms": suspicious,
        "suspicious_application_claim": suspicious_application_claim,
    }


def check_output_quality(
    clean_text: str,
    raw_text: str,
    utterance: str,
    node_result: Dict[str, Any],
    run_mode: str = "formal",
) -> Dict[str, Any]:
    response_empty = not bool((clean_text or "").strip())
    infrastructure_valid = bool(node_result.get("ok"))
    thinking_content_present = bool(node_result.get("thinking_content_present"))
    contamination_spans = _find_contamination_spans(clean_text or "")
    language_contamination = bool(contamination_spans)
    policy = _policy_anchor_check(clean_text or "", utterance or "")
    policy_anchor_fail = policy.get("policy_anchor_checked") and policy.get("policy_anchor_pass") is False
    truncation_risk = False
    choices = node_result.get("raw", {}).get("choices")
    if isinstance(choices, list) and choices:
        truncation_risk = choices[0].get("finish_reason") == "length"

    invalid_reasons = []
    if response_empty:
        invalid_reasons.append("empty_response")
    if thinking_content_present:
        invalid_reasons.append("thinking_content_present")
    if language_contamination:
        invalid_reasons.append("language_contamination")
    if policy_anchor_fail:
        invalid_reasons.append("policy_anchor_failure")
    if truncation_risk:
        invalid_reasons.append("truncation_risk")

    failed_quality_gate = bool(invalid_reasons)

    hard_history_reasons = []
    # A response that never successfully came back from the node is preserved
    # as an infrastructure observation, but it must not become prompt context
    # for the next turn because no real assistant response exists.
    if not infrastructure_valid:
        hard_history_reasons.append("infrastructure_invalid")
    # Empty output and non-empty thinking content are hard failures: adding
    # either to history would create an artificial conversational state that
    # differs from a valid citizen-assistant exchange.
    if response_empty:
        hard_history_reasons.append("empty_response")
    if thinking_content_present:
        hard_history_reasons.append("thinking_content_present")
    # Formal runs treat truncation as context-unsafe unless a future explicit
    # truncation policy says otherwise. Smoke runs may still carry truncated
    # text while testing path readiness, so this gate is phase-aware.
    if truncation_risk and run_mode == "formal":
        hard_history_reasons.append("truncation_risk")
    # Deterministic language contamination is considered a hard context failure
    # because it can steer the next generation in a non-Korean or corrupted
    # direction even when the row remains valuable as a quality outcome.
    if language_contamination:
        hard_history_reasons.append("language_contamination")
    # Routing or intervention contamination is not currently produced by
    # NodeClient, but keeping the hook here makes the policy explicit if prompt
    # audit code later detects Node C RAG/SC leakage or Node B SC leakage.
    if node_result.get("routing_contamination") or node_result.get("intervention_contamination"):
        hard_history_reasons.append("intervention_contamination")

    history_eligible = not hard_history_reasons
    return {
        "infrastructure_valid": infrastructure_valid,
        "path_ready": infrastructure_valid,
        "generation_quality_ready": not failed_quality_gate,
        "analysis_eligible": not failed_quality_gate,
        "failed_quality_gate": failed_quality_gate,
        "invalid_reason": " + ".join(invalid_reasons) if invalid_reasons else None,
        "history_eligible": history_eligible,
        "history_exclusion_reason": " + ".join(hard_history_reasons) if hard_history_reasons else None,
        "history_exclusion_reasons": hard_history_reasons,
        "response_empty": response_empty,
        "thinking_content_present": thinking_content_present,
        "empty_thinking_shell": bool(node_result.get("empty_thinking_shell")),
        "cleaning_applied": bool(node_result.get("cleaning_applied")),
        "language_contamination": language_contamination,
        "contamination_spans": contamination_spans,
        "truncation_risk": truncation_risk,
        "usable_as_quality_outcome": True,
        "exclude_from_causal_trigger": failed_quality_gate,
        "metric_status": "stored_not_causal" if failed_quality_gate else "stored_and_causal",
        **policy,
    }
