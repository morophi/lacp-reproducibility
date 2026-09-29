#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from metrics import MetricComputer, compute_lms, compute_sci, compute_srr, strip_empty_think_tags


def sample_openai_raw():
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>\n\n</think>\n\n답변입니다.",
                    "reasoning": "",
                },
                "logprobs": {
                    "content": [
                        {"token": "<think>", "bytes": [60, 116, 104, 105, 110, 107, 62], "top_logprobs": [
                            {"token": "<think>", "logprob": -0.1},
                            {"token": "답", "logprob": -2.0},
                        ]},
                        {"token": "\n\n", "bytes": [10, 10], "top_logprobs": [
                            {"token": "\n\n", "logprob": -0.1},
                            {"token": " ", "logprob": -3.0},
                        ]},
                        {"token": "</think>", "bytes": [60, 47, 116, 104, 105, 110, 107, 62], "top_logprobs": [
                            {"token": "</think>", "logprob": -0.1},
                            {"token": "답", "logprob": -3.0},
                        ]},
                        {"token": "\n\n", "bytes": [10, 10], "top_logprobs": [
                            {"token": "\n\n", "logprob": -0.1},
                            {"token": "답", "logprob": -2.0},
                        ]},
                        {"token": "답", "bytes": [235, 139, 181], "top_logprobs": [
                            {"token": "답", "logprob": -0.2},
                            {"token": "질", "logprob": -0.9},
                        ]},
                        {"token": "변", "bytes": [235, 179, 128], "top_logprobs": [
                            {"token": "변", "logprob": -0.3},
                            {"token": "안", "logprob": -1.5},
                        ]},
                    ]
                },
            }
        ]
    }


def test_strip_empty_think_tags():
    assert strip_empty_think_tags("<think>\n\n</think>\n\n답변입니다.") == "답변입니다."


def test_compute_lms_openai_excludes_empty_think_prefix():
    raw = sample_openai_raw()
    result = compute_lms(raw, theta_entropy=0.0)
    assert result["lms_available"] is True
    assert result["lms_token_count"] == 2
    assert result["lms_value"] > 0


def test_compute_lms_uses_harness_clean_logprobs_directly():
    raw = {
        "_harness_clean_logprobs": sample_openai_raw()["choices"][0]["logprobs"]["content"][-2:],
    }
    result = compute_lms(raw, theta_entropy=0.0)
    assert result["lms_available"] is True
    assert result["lms_token_count"] == 2


def test_cross_node_metrics_use_configured_baseline_role():
    computer = MetricComputer({
        "nodes": {
            "A": {"role": "rag_only"},
            "B": {"role": "baseline"},
            "C": {"role": "inactive"},
        }
    })
    result = computer.compute_cross_node_metrics({
        "A": {"lms_value": 0.7, "cds": 0.2, "ma_assert": 0.4},
        "B": {"lms_value": 0.5, "cds": 0.3, "ma_assert": 0.1},
    })
    assert result["B"]["d_lms"] == 0.0
    assert result["A"]["d_lms"] == 0.19999999999999996
    assert result["A"]["d_cds"] == 0.09999999999999998
    assert result["A"]["d_ma"] == 0.30000000000000004


def test_srr_records_responsibility_boundary_signal():
    result = compute_srr("최종 결정은 담당 공무원 심사와 서류 확인이 필요합니다. 주민센터에 문의하세요.")
    assert result["srr_available"] is True
    assert result["srr"] > 0


def test_sci_records_structured_caution_signal():
    result = compute_sci("소득과 가구 기준 확인이 필요합니다. 서류를 준비해 주민센터에 문의하세요.")
    assert result["sci_available"] is True
    assert result["sci"] > 0


def test_metric_computer_logs_srr_and_sci_when_enabled():
    computer = MetricComputer({
        "nodes": {"A": {"role": "rag_sc"}, "B": {"role": "rag_only"}, "C": {"role": "baseline"}},
        "metrics": {
            "ma": {"enabled": True},
            "cds": {"enabled": False},
            "lms": {"enabled": True, "theta_entropy": 0.0},
            "srr": {"enabled": True},
            "sci": {"enabled": True},
        },
        "run_modes": {"smoke": {"allow_null_metrics": True}},
    })
    result = computer.compute_node_metrics(
        node="A",
        response_text="소득 기준과 서류 확인이 필요합니다. 담당 공무원에게 문의하세요.",
        response_raw={},
        history=[],
        turn_no=1,
        run_mode="smoke",
    )
    assert result["srr"] is not None
    assert result["sci"] is not None
    assert result["metric_status"]["srr_available"] is True
    assert result["metric_status"]["sci_available"] is True
