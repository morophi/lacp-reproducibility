#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio

from config_utils import load_config
from metrics import compute_lms
from node_client import NodeClient


async def main():
    cfg = load_config("/home/morophi/harness/config/node_config.yaml")
    client = NodeClient(cfg["nodes"], cfg["model"])
    result = await client.chat(
        "A",
        [{"role": "user", "content": "짧게 답하세요. 기초생활보장 신청은 어디서 하나요?"}],
        run_mode="formal",
    )
    lms = compute_lms(result["raw"], cfg["metrics"]["lms"]["theta_entropy"])
    print("endpoint_mode=", result.get("endpoint_mode"))
    print("status=", result.get("status"), "ok=", result.get("ok"))
    print("text_len=", len(result.get("text") or ""), "text_raw_len=", len(result.get("text_raw") or ""))
    print("text=", result.get("text"))
    print("has_raw_choices=", isinstance(result.get("raw", {}).get("choices"), list))
    print("thinking_tag_present=", result.get("thinking_tag_present"))
    print("empty_thinking_shell=", result.get("empty_thinking_shell"))
    print("thinking_content_present=", result.get("thinking_content_present"))
    print("cleaning_applied=", result.get("cleaning_applied"))
    print("cleaning_allowed=", result.get("cleaning_allowed"))
    print("failed_TR=", result.get("failed_TR"))
    print("removed_prefix_chars=", result.get("removed_prefix_chars"))
    print("raw_logprobs_len=", len(result.get("raw_logprobs") or []))
    print("clean_logprobs_len=", len(result.get("clean_logprobs") or []))
    print("excluded_token_positions=", result.get("excluded_token_positions"))
    print("lms_available=", lms.get("lms_available"))
    print("lms_token_count=", lms.get("lms_token_count"))
    print("lms_value=", lms.get("lms_value"))


if __name__ == "__main__":
    asyncio.run(main())
