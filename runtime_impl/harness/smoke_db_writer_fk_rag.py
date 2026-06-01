#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import time

from config_utils import load_config
from logger import build_logger


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


run_id = f"db_writer_fk_rag_smoke_{int(time.time())}"
row = {
    "run_id": run_id,
    "scenario_id": "db_writer_fk_rag_smoke_scenario",
    "scenario_hash": "0" * 64,
    "condition": "run_b",
    "run_mode": "smoke",
    "turn_no": 1,
    "node": "A",
    "source_file": "/tmp/db_writer_fk_rag_smoke.json",
    "harness_version": "smoke",
    "node_config_hash": "2" * 64,
    "run_sc_policy_id": "sc_protocol_v1",
    "run_policy_hash": "3" * 64,
    "theta_source": "/home/morophi/harness/config/theta_config.json",
    "theta_locked": True,
    "utterance_hash": sha("rag smoke utterance"),
    "response_text": "rag smoke response",
    "response_hash": sha("rag smoke response"),
    "elapsed_ms": 12.3,
    "rag_injected": True,
    "sc_policy_applied": True,
    "sc_policy_id": "sc_protocol_v1",
    "policy_hash": "3" * 64,
    "trigger_mode": "smoke_db_writer_fk_rag",
    "trigger_reasons": ["db_writer_fk_rag_smoke"],
    "trigger_source_nodes": ["A"],
    "threshold_snapshot": {"theta_lms": 0.0},
    "previous_turn_used_for_trigger": 0,
    "rag_chunk_ids": ["chunk_fk_smoke_1"],
    "retrieved_chunk_ids": ["chunk_fk_smoke_1"],
    "collection_name": "lacp_docs_v2_table_safe",
    "top_k": 1,
    "returned_count": 1,
    "rag_context_chars": 18,
    "retrieval_method": "synthetic_smoke",
    "table_exposure": False,
    "chunk_lengths": [18],
    "block_type_distribution": {"text": 1},
    "prompt_hash": "4" * 64,
    "payload_hash": "5" * 64,
    "message_count": 4,
    "prompt_chars": 128,
    "model_name": "qwen3-nothink",
    "model_digest": None,
    "temperature": 0.0,
    "seed": 42,
    "thinking_disabled_requested": True,
    "endpoint_mode": "openai_chat_completions",
    "response_text_raw_hash": sha("rag smoke response"),
    "thinking_tag_present": False,
    "empty_thinking_shell": False,
    "thinking_content_present": False,
    "cleaning_applied": False,
    "cleaning_allowed": True,
    "failed_TR": False,
    "removed_prefix_chars": 0,
    "raw_logprobs_len": 4,
    "clean_logprobs_len": 4,
    "excluded_token_positions": [],
    "quality_gate": {
        "generation_quality_ready": True,
        "analysis_eligible": True,
        "exclude_from_causal_trigger": False,
        "history_eligible": True,
        "usable_as_quality_outcome": True,
    },
    "generation_quality_ready": True,
    "analysis_eligible": True,
    "exclude_from_causal_trigger": False,
    "history_eligible": True,
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
