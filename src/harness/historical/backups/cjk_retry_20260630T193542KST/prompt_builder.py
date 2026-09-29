#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node-specific prompt construction for LACP Harness.

This module enforces treatment separation: SC-Protocol can only enter Node A
payloads through Harness. RAG eligibility is controlled by the Harness role map
in node_config.yaml so physical B/C role swaps can be frozen before a new chain.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional

from config_utils import normalized_json_hash


BASE_SYSTEM_PROMPT = (
    "You are a Korean public-service assistant for a controlled LACP experiment. "
    "Answer the citizen's current utterance using the provided conversation context. "
    "Formal response constraint: answer in Korean within 700 characters. "
    "Use Korean wording only; do not use Japanese kana, Chinese ideographs, or mixed-language phrases. "
    "Do not repeat the same sentence or claim. Prefer a brief summary and concrete next step."
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
    sc_policy_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_node = node.upper()
    if normalized_node not in {"A", "B", "C"}:
        raise ValueError(f"Unsupported node: {node}")
    if normalized_node in {"B", "C"} and sc_policy_block is not None:
        raise ValueError("SC-Protocol policy block may only be passed to Node A")
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
    sc_block_chars = len(sc_policy_block or "")
    sc_block_hash = hashlib.sha256(sc_policy_block.encode("utf-8")).hexdigest() if sc_policy_block else None
    retrieved_chunk_ids_hash = hashlib.sha256(
        json.dumps(rag_chunk_ids, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest() if rag_chunk_ids else None
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
            "final_prompt_chars": sum(len(message.get("content", "")) for message in messages),
            "sc_block_chars": sc_block_chars,
            "sc_block_hash": sc_block_hash,
            "prompt_contains_sc_marker": "[SC-PROTOCOL" in (sc_policy_block or ""),
            "retrieved_chunk_ids_hash": retrieved_chunk_ids_hash,
            "policy_hash": policy_hash if sc_policy_applied else None,
            "sc_policy_payload": sc_policy_payload if sc_policy_applied else None,
        },
    }
