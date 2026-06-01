#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from quality_gate import check_output_quality


def base_node_result():
    return {
        "ok": True,
        "empty_thinking_shell": True,
        "cleaning_applied": True,
        "thinking_content_present": False,
        "raw": {"choices": [{"finish_reason": "stop"}]},
    }


def test_language_and_policy_failure_preserved_not_causal():
    result = check_output_quality(
        clean_text=(
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\uc8fc\ubbfc\ub4f1\ub85d\uc0c1 \uc8fc\uc18c\uc9c0 \uad00\ud560"
            "\u7684\u5730\u65b9\uc0ac\ud68c\ubcf5\uc9c0\uad00 \ub610\ub294 "
            "\ubcf5\uc9c0\uad00\uc5d0\uc11c \ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        raw_text=(
            "<think>\n\n</think>\n\n"
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\uc8fc\ubbfc\ub4f1\ub85d\uc0c1 \uc8fc\uc18c\uc9c0 \uad00\ud560"
            "\u7684\u5730\u65b9\uc0ac\ud68c\ubcf5\uc9c0\uad00 \ub610\ub294 "
            "\ubcf5\uc9c0\uad00\uc5d0\uc11c \ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        utterance="\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 \uc5b4\ub514\uc11c \ud558\ub098\uc694?",
        node_result=base_node_result(),
    )
    assert result["language_contamination"] is True
    assert "\u7684\u5730\u65b9" in result["contamination_spans"]
    assert result["policy_anchor_pass"] is False
    assert result["suspicious_application_claim"] is True
    assert result["generation_quality_ready"] is False
    assert result["analysis_eligible"] is False
    assert result["usable_as_quality_outcome"] is True
    assert result["exclude_from_causal_trigger"] is True
    assert result["history_eligible"] is False
    assert "language_contamination" in result["history_exclusion_reasons"]


def test_clean_application_office_answer_passes():
    result = check_output_quality(
        clean_text=(
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\uc8fc\ubbfc\ub4f1\ub85d\uc0c1 \uc8fc\uc18c\uc9c0 \uad00\ud560 "
            "\uc74d\u00b7\uba74\u00b7\ub3d9 \ud589\uc815\ubcf5\uc9c0\uc13c\ud130\uc5d0\uc11c "
            "\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        raw_text=(
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\uc8fc\ubbfc\ub4f1\ub85d\uc0c1 \uc8fc\uc18c\uc9c0 \uad00\ud560 "
            "\uc74d\u00b7\uba74\u00b7\ub3d9 \ud589\uc815\ubcf5\uc9c0\uc13c\ud130\uc5d0\uc11c "
            "\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        utterance="\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 \uc5b4\ub514\uc11c \ud558\ub098\uc694?",
        node_result=base_node_result(),
    )
    assert result["language_contamination"] is False
    assert result["policy_anchor_pass"] is True
    assert result["generation_quality_ready"] is True
    assert result["analysis_eligible"] is True
    assert result["exclude_from_causal_trigger"] is False
    assert result["history_eligible"] is True


def test_policy_anchor_failure_does_not_automatically_remove_history():
    result = check_output_quality(
        clean_text=(
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\ubcf5\uc9c0\uad00\uc5d0\uc11c \ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        raw_text=(
            "\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 "
            "\ubcf5\uc9c0\uad00\uc5d0\uc11c \ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        ),
        utterance="\uae30\ucd08\uc0dd\ud65c\ubcf4\uc7a5 \uc2e0\uccad\uc740 \uc5b4\ub514\uc11c \ud558\ub098\uc694?",
        node_result=base_node_result(),
    )
    # Policy-anchor failure is analysis/trigger-ineligible, but it is not
    # automatically a history hard failure unless it also causes one of the
    # context-safety problems such as contamination, empty output, or failed_TR.
    assert result["policy_anchor_pass"] is False
    assert result["analysis_eligible"] is False
    assert result["exclude_from_causal_trigger"] is True
    assert result["history_eligible"] is True


def test_failed_tr_is_history_ineligible():
    node_result = base_node_result()
    node_result["thinking_content_present"] = True
    result = check_output_quality(
        clean_text="\uc751\ub2f5\uc785\ub2c8\ub2e4.",
        raw_text="<think>internal</think>\n\n\uc751\ub2f5\uc785\ub2c8\ub2e4.",
        utterance="\uc9c8\ubb38\uc785\ub2c8\ub2e4.",
        node_result=node_result,
    )
    assert result["analysis_eligible"] is False
    assert result["exclude_from_causal_trigger"] is True
    assert result["history_eligible"] is False
    assert "thinking_content_present" in result["history_exclusion_reasons"]
