#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import types

sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=object))
sys.modules.setdefault("chromadb", types.SimpleNamespace(HttpClient=object))
sys.modules.setdefault(
    "sentence_transformers",
    types.SimpleNamespace(SentenceTransformer=object),
)

from experiment_runner import ExperimentRunner, FORMAL_LANGUAGE_RETRY_GUARD


def test_formal_quality_retryable_only_for_language_contamination():
    assert ExperimentRunner._formal_quality_retryable({
        "invalid_reason": "language_contamination",
    }) is True

    assert ExperimentRunner._formal_quality_retryable({
        "invalid_reason": "policy_anchor_failure",
    }) is False

    assert ExperimentRunner._formal_quality_retryable({
        "invalid_reason": "language_contamination + truncation_risk",
    }) is False

    assert ExperimentRunner._formal_quality_retryable({
        "invalid_reason": None,
    }) is False


def test_messages_with_language_retry_guard_preserves_message_order():
    messages = [
        {"role": "system", "content": "base"},
        {"role": "system", "content": "rag"},
        {"role": "user", "content": "question"},
    ]

    guarded = ExperimentRunner._messages_with_language_retry_guard(messages)

    assert [message["role"] for message in guarded] == ["system", "system", "system", "user"]
    assert guarded[0]["content"] == "base"
    assert guarded[1]["content"] == FORMAL_LANGUAGE_RETRY_GUARD
    assert guarded[2]["content"] == "rag"
    assert guarded[3]["content"] == "question"
