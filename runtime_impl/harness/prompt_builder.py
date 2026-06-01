#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node-specific prompt construction for LACP Harness.

This module enforces treatment separation: SC-Protocol can only enter Node A
payloads through Harness, and Node C is protected from both RAG and SC context.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from config_utils import normalized_json_hash


BASE_SYSTEM_PROMPT = (
    "You are a Korean public-service assistant for a controlled LACP experiment. "
    "Answer the citizen's current utterance using the provided conversation context."
)


def _chunk_id(chunk: Dict[str, Any], index: int) -> str:
    return str(
        chunk.get("chunk_id")
        or chunk.get("id")
        or chunk.get("metadata", {}).get("chunk_id")
        or f"chunk_{index + 1}"
    )


def _chunk_text(chunk: Dict[str, Any]) -> str:
    return str(
        chunk.get("text")
        or chunk.get("document")
        or chunk.get("content")
        or chunk.get("page_content")
        or ""
    )


def _block_types(chunk: Dict[str, Any]) -> List[str]:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    raw = metadata.get("block_types") or chunk.get("block_types") or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _rag_context_block(rag_chunks: List[Dict[str, Any]]) -> str:
    lines = ["[RAG CONTEXT]"]
    for idx, chunk in enumerate(rag_chunks):
        chunk_id = _chunk_id(chunk, idx)
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        source = chunk.get("source") or metadata.get("source_file") or metadata.get("source") or ""
        lines.append(f"[CHUNK id={chunk_id} source={source}]")
        lines.append(_chunk_text(chunk))
        lines.append("[/CHUNK]")
    lines.append("[/RAG CONTEXT]")
    return "\n".join(lines)


def build_messages(
    node: str,
    user_utterance: str,
    history: List[Dict[str, Any]],
    rag_chunks: Optional[List[Dict[str, Any]]] = None,
    sc_policy_block: Optional[str] = None,
    policy_hash: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_node = node.upper()
    if normalized_node not in {"A", "B", "C"}:
        raise ValueError(f"Unsupported node: {node}")
    if normalized_node in {"B", "C"} and sc_policy_block is not None:
        raise ValueError("SC-Protocol policy block may only be passed to Node A")
    if normalized_node == "C" and rag_chunks:
        raise ValueError("Node C must never receive RAG context")

    safe_history = copy.deepcopy(history)
    chunks = list(rag_chunks or [])
    rag_injected = bool(chunks)
    sc_policy_applied = bool(sc_policy_block)

    messages: List[Dict[str, str]] = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
    if sc_policy_block:
        messages.append({"role": "system", "content": sc_policy_block})
    if chunks:
        messages.append({"role": "system", "content": _rag_context_block(chunks)})
    messages.extend(safe_history)
    messages.append({"role": "user", "content": user_utterance})

    prompt_hash = normalized_json_hash(messages)
    rag_chunk_ids = [_chunk_id(chunk, idx) for idx, chunk in enumerate(chunks)]
    chunk_texts = [_chunk_text(chunk) for chunk in chunks]
    block_type_distribution: Dict[str, int] = {}
    table_exposure = False
    for chunk in chunks:
        types = _block_types(chunk)
        for block_type in types:
            block_type_distribution[block_type] = block_type_distribution.get(block_type, 0) + 1
            if "table" in block_type.lower():
                table_exposure = True
    payload_hash = normalized_json_hash({
        "node": normalized_node,
        "messages": messages,
    })
    return {
        "messages": messages,
        "prompt_metadata": {
            "node": normalized_node,
            "rag_injected": rag_injected,
            "sc_policy_applied": sc_policy_applied,
            "rag_chunk_ids": rag_chunk_ids,
            "rag_context_chars": sum(len(text) for text in chunk_texts),
            "retrieved_chunk_ids": rag_chunk_ids,
            "chunk_lengths": [len(text) for text in chunk_texts],
            "block_type_distribution": block_type_distribution,
            "collection_name": chunks[0].get("collection_name") if chunks else None,
            "top_k": len(chunks) if chunks else None,
            "returned_count": len(chunks),
            "retrieval_method": chunks[0].get("retrieval_method") if chunks else None,
            "table_exposure": table_exposure,
            "prompt_hash": prompt_hash,
            "payload_hash": payload_hash,
            "message_count": len(messages),
            "prompt_chars": sum(len(message.get("content", "")) for message in messages),
            "policy_hash": policy_hash if sc_policy_applied else None,
        },
    }
