#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import time

from logger import build_logger
from config_utils import load_config


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


run_id = f"db_writer_smoke_{int(time.time())}"
row = {
    "run_id": run_id,
    "scenario_id": "db_writer_smoke_scenario",
    "scenario_hash": "0" * 64,
    "condition": "run_b",
    "run_mode": "smoke",
    "turn_no": 1,
    "node": "C",
    "source_file": "/tmp/db_writer_smoke.json",
    "utterance_hash": sha("smoke utterance"),
    "response_text": "smoke response",
    "response_hash": sha("smoke response"),
    "elapsed_ms": 12.3,
    "rag_injected": False,
    "sc_policy_applied": False,
    "sc_policy_id": None,
    "policy_hash": None,
    "trigger_mode": "smoke_db_writer",
    "trigger_reasons": ["db_writer_smoke"],
    "trigger_source_nodes": [],
    "threshold_snapshot": {"theta_lms": 0.0},
    "previous_turn_used_for_trigger": None,
    "rag_chunk_ids": [],
    "prompt_hash": "1" * 64,
    "model_name": "qwen3-nothink",
    "model_digest": None,
    "temperature": 0.0,
    "seed": 42,
    "thinking_disabled_requested": True,
    "endpoint_mode": "openai_chat_completions",
    "response_text_raw_hash": sha("<think>\n\n</think>\n\nsmoke response"),
    "thinking_tag_present": True,
    "empty_thinking_shell": True,
    "thinking_content_present": False,
    "cleaning_applied": True,
    "cleaning_allowed": True,
    "failed_TR": False,
    "removed_prefix_chars": 19,
    "raw_logprobs_len": 4,
    "clean_logprobs_len": 1,
    "excluded_token_positions": [0, 1, 2],
    "quality_gate": {
        "generation_quality_ready": True,
        "analysis_eligible": True,
        "exclude_from_causal_trigger": False,
        "usable_as_quality_outcome": True,
    },
    "generation_quality_ready": True,
    "analysis_eligible": True,
    "exclude_from_causal_trigger": False,
    "usable_as_quality_outcome": True,
    "metrics": {
        "lms_value": 1.23,
        "lms_token_count": 1,
        "theta_entropy": 0.0,
        "lms_delta": 0.0,
        "cds": None,
        "ma_assert": 1.0,
        "ma_epist": 0.0,
        "ma_hedge": 0.0,
        "sent_count": 1,
        "srr": None,
        "sci": None,
        "metric_status": {"lms_available": True},
        "metric_pipeline_version": "smoke",
    },
    "metric_status": {"lms_available": True},
    "raw_response_keys": ["choices", "usage"],
}

config = load_config("/home/morophi/harness/config/node_config.yaml")
logger = build_logger(config["logging"])
logger.log_turn(run_id, row)
print(json.dumps({"run_id": run_id, "ok": True}, ensure_ascii=False))
