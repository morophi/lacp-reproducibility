#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest

from prompt_builder import build_messages


SC_BLOCK = "[SC-PROTOCOL OPERATING POLICY]\npolicy_id: sc_protocol_v1\n[/SC-PROTOCOL OPERATING POLICY]"
RAG = [{"chunk_id": "chunk_a", "text": "raw retrieved table-safe text", "metadata": {"source_file": "x.pdf"}}]


def test_node_a_contains_sc_policy():
    result = build_messages("A", "hello", [], RAG, SC_BLOCK, "abc")
    joined = "\n".join(message["content"] for message in result["messages"])
    assert "SC-PROTOCOL OPERATING POLICY" in joined
    assert result["prompt_metadata"]["sc_policy_applied"] is True


def test_node_b_no_sc_policy():
    result = build_messages("B", "hello", [], RAG, None, None)
    joined = "\n".join(message["content"] for message in result["messages"])
    assert "SC-PROTOCOL OPERATING POLICY" not in joined
    assert result["prompt_metadata"]["sc_policy_applied"] is False


def test_node_c_no_sc_or_rag():
    result = build_messages("C", "hello", [], None, None, None)
    joined = "\n".join(message["content"] for message in result["messages"])
    assert "SC-PROTOCOL OPERATING POLICY" not in joined
    assert "RAG CONTEXT" not in joined


def test_node_b_rejects_sc_policy():
    with pytest.raises(ValueError):
        build_messages("B", "hello", [], None, SC_BLOCK, "abc")


def test_node_c_rejects_rag():
    with pytest.raises(ValueError):
        build_messages("C", "hello", [], RAG, None, None)


def test_prompt_hash_changes_when_rag_changes():
    one = build_messages("B", "hello", [], [{"chunk_id": "1", "text": "a"}], None, None)
    two = build_messages("B", "hello", [], [{"chunk_id": "2", "text": "b"}], None, None)
    assert one["prompt_metadata"]["prompt_hash"] != two["prompt_metadata"]["prompt_hash"]


def test_prompt_hash_changes_when_sc_changes():
    one = build_messages("A", "hello", [], None, SC_BLOCK, "abc")
    two = build_messages("A", "hello", [], None, SC_BLOCK + "\nextra", "def")
    assert one["prompt_metadata"]["prompt_hash"] != two["prompt_metadata"]["prompt_hash"]


def test_shared_rag_chunks_a_b_same_ids_and_sc_only_a():
    a = build_messages("A", "hello", [], RAG, SC_BLOCK, "abc")
    b = build_messages("B", "hello", [], RAG, None, None)
    c = build_messages("C", "hello", [], None, None, None)

    assert a["prompt_metadata"]["rag_chunk_ids"] == b["prompt_metadata"]["rag_chunk_ids"]
    assert "SC-PROTOCOL OPERATING POLICY" in "\n".join(message["content"] for message in a["messages"])
    assert "SC-PROTOCOL OPERATING POLICY" not in "\n".join(message["content"] for message in b["messages"])
    c_text = "\n".join(message["content"] for message in c["messages"])
    assert "RAG CONTEXT" not in c_text
    assert "SC-PROTOCOL OPERATING POLICY" not in c_text
