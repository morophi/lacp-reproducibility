#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from metrics import compute_lms, strip_empty_think_tags


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
