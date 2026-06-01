#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LACP Harness Orchestration Smoke Test

Purpose:
  1. Check experiment/scenario paths
  2. Check Node A/B/C Ollama API
  3. Verify model/digest consistency
  4. Run single-node generate test
  5. Build RAG context from Harness
  6. Send one-turn concurrent requests to A/B/C
  7. Collect responses and elapsed_ms
  8. Write DB-ready JSONL logs
  9. Run 3-turn mini test
 10. Write summary report

Assumption:
  - Harness runs this script.
  - RAG ChromaDB is available at 10.1.1.120:8000
  - Inference nodes expose Ollama API at 11434
  - Node A/B receive RAG context
  - Node C receives no RAG context

Change note:
  The Ollama /api/generate response can contain both a generated `response`
  field and a separate `thinking` field. The harness treats only `response`
  or message.content fallback as response_text, preserves thinking_text
  separately, and separates path readiness from generation-quality readiness.
  The harness now sends top-level `think: false` by default so Qwen thinking
  output is explicitly disabled and separately validates that control.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import chromadb
from sentence_transformers import SentenceTransformer


DEFAULT_NODES = {
    "A": "10.1.1.10",
    "B": "10.1.1.20",
    "C": "10.1.1.30",
}

DEFAULT_RAG_HOST = "10.1.1.120"
DEFAULT_RAG_PORT = 8000
DEFAULT_COLLECTION = "lacp_docs"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

DEFAULT_MODEL_CANDIDATES = [
    "qwen3-nothink",
    "qwen3:8b",
    "qwen3",
]

DEFAULT_TEST_TURNS = [
    {
        "turn": 1,
        "utterance": "수급자격 확인이 필요합니다. 주민등록지가 다른 경우 어떻게 확인해야 하나요?"
    },
    {
        "turn": 2,
        "utterance": "거주지가 바뀐 수급자 가구의 서류 관리는 어떻게 처리해야 하나요?"
    },
    {
        "turn": 3,
        "utterance": "재산조사에서 이혼에 따른 재산분할은 어떻게 확인하나요?"
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_scenario(path: Optional[str]) -> List[Dict[str, Any]]:
    if not path:
        return DEFAULT_TEST_TURNS

    scenario_path = Path(path)
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

    with scenario_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        turns = data
    elif isinstance(data, dict) and "turns" in data:
        turns = data["turns"]
    else:
        raise ValueError("Scenario JSON must be a list or {'turns': [...]}")

    normalized = []
    for idx, item in enumerate(turns, 1):
        turn_no = item.get("turn", idx)
        utterance = item.get("utterance") or item.get("text") or item.get("prompt")
        if not utterance:
            raise ValueError(f"Scenario item missing utterance/text/prompt at index {idx}")
        normalized.append({"turn": turn_no, "utterance": utterance})

    return normalized


async def http_get_json(session: aiohttp.ClientSession, url: str, timeout_sec: int = 10) -> Tuple[bool, Any, float]:
    start = time.perf_counter()
    try:
        async with session.get(url, timeout=timeout_sec) as resp:
            text = await resp.text()
            elapsed_ms = (time.perf_counter() - start) * 1000
            try:
                payload = json.loads(text)
            except Exception:
                payload = text
            return resp.status == 200, payload, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return False, repr(e), elapsed_ms


async def http_post_json(
    session: aiohttp.ClientSession,
    url: str,
    payload: Dict[str, Any],
    timeout_sec: int = 120,
) -> Tuple[bool, Any, float]:
    start = time.perf_counter()
    try:
        async with session.post(url, json=payload, timeout=timeout_sec) as resp:
            text = await resp.text()
            elapsed_ms = (time.perf_counter() - start) * 1000
            try:
                data = json.loads(text)
            except Exception:
                data = text
            return resp.status == 200, data, elapsed_ms
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return False, repr(e), elapsed_ms


async def check_ollama_tags(nodes: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = {}
        for node, ip in nodes.items():
            url = f"http://{ip}:11434/api/tags"
            tasks[node] = http_get_json(session, url)

        for node, task in tasks.items():
            ok, payload, elapsed_ms = await task
            results[node] = {
                "ok": ok,
                "payload": payload,
                "elapsed_ms": elapsed_ms,
            }
    return results


def extract_models_from_tags(tags_payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(tags_payload, dict):
        return []
    models = tags_payload.get("models", [])
    if not isinstance(models, list):
        return []
    return models


def select_common_model(
    tag_results: Dict[str, Dict[str, Any]],
    preferred_model: Optional[str],
) -> Dict[str, Any]:
    node_models = {}

    for node, result in tag_results.items():
        models = extract_models_from_tags(result.get("payload"))
        node_models[node] = models

    if preferred_model:
        selected_name = preferred_model
    else:
        all_names = []
        for models in node_models.values():
            all_names.extend([m.get("name") for m in models if m.get("name")])

        selected_name = None
        for candidate in DEFAULT_MODEL_CANDIDATES:
            if candidate in all_names:
                selected_name = candidate
                break

        if selected_name is None and all_names:
            selected_name = all_names[0]

    if not selected_name:
        raise RuntimeError("No Ollama model found on inference nodes.")

    digests = {}
    presence = {}

    for node, models in node_models.items():
        found = None
        for m in models:
            if m.get("name") == selected_name:
                found = m
                break

        presence[node] = found is not None
        digests[node] = found.get("digest") if found else None

    digest_values = [d for d in digests.values() if d]
    digest_consistent = len(set(digest_values)) == 1 and len(digest_values) == len(digests)

    return {
        "selected_model": selected_name,
        "presence": presence,
        "digests": digests,
        "digest_consistent": digest_consistent,
        "node_models": node_models,
    }


def load_embedding_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, local_files_only=True)


def rag_retrieve(
    embedding_model: SentenceTransformer,
    query: str,
    rag_host: str,
    rag_port: int,
    collection_name: str,
    top_k: int,
) -> Dict[str, Any]:
    q_emb = embedding_model.encode(query, normalize_embeddings=True).tolist()

    client = chromadb.HttpClient(host=rag_host, port=rag_port)
    col = client.get_collection(collection_name)

    count = col.count()

    result = col.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    chunks = []
    for i, doc in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) else {}
        dist = distances[i] if i < len(distances) else None
        chunks.append({
            "rank": i + 1,
            "distance": dist,
            "document": doc,
            "metadata": meta,
            "chunk_id": meta.get("chunk_id"),
            "source_label": meta.get("source_label"),
        })

    return {
        "collection": collection_name,
        "collection_count": count,
        "query": query,
        "top_k": top_k,
        "chunks": chunks,
    }


def build_rag_context(rag_result: Dict[str, Any]) -> str:
    lines = []
    lines.append("[Retrieved Policy Context]")
    for chunk in rag_result["chunks"]:
        rank = chunk["rank"]
        chunk_id = chunk.get("chunk_id")
        source_label = chunk.get("source_label")
        distance = chunk.get("distance")
        doc = chunk.get("document", "")

        lines.append(f"\n[{rank}] source={source_label} chunk_id={chunk_id} distance={distance}")
        lines.append(doc.strip())

    return "\n".join(lines).strip()


def build_prompt(
    node: str,
    utterance: str,
    rag_context: Optional[str],
) -> Tuple[str, bool, List[str]]:
    retrieved_chunk_ids = []

    if rag_context:
        # Extract chunk ids from context is not robust; actual ids are passed separately in logs.
        pass

    if node in ("A", "B") and rag_context:
        prompt = f"""
{rag_context}

[Citizen Utterance]
{utterance}

[Instruction]
위 검색 지침을 참고하되, 지침에 없는 내용은 단정하지 말고 확인 필요 사항을 분리하여 답하십시오.
답변은 한국어로 작성하십시오.
""".strip()
        return prompt, True, retrieved_chunk_ids

    prompt = f"""
[Citizen Utterance]
{utterance}

[Instruction]
검색 지침 없이, 모델의 일반 판단만으로 답하십시오.
답변은 한국어로 작성하십시오.
""".strip()
    return prompt, False, retrieved_chunk_ids


async def ollama_generate(
    session: aiohttp.ClientSession,
    node: str,
    ip: str,
    model: str,
    prompt: str,
    temperature: float,
    seed: int,
    num_predict: int,
    think: bool,
) -> Dict[str, Any]:
    url = f"http://{ip}:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "options": {
            "temperature": temperature,
            "seed": seed,
            "num_predict": num_predict,
        },
    }

    ok, data, elapsed_ms = await http_post_json(session, url, payload)

    response_text = ""
    thinking_text = ""
    raw_response_keys: List[str] = []
    response_field_used = "none"
    if isinstance(data, dict):
        raw_response_keys = sorted(str(key) for key in data.keys())
        thinking_text = data.get("thinking") or ""
        if data.get("response"):
            response_text = data.get("response") or ""
            response_field_used = "response"
        elif isinstance(data.get("message"), dict) and data["message"].get("content"):
            response_text = data["message"].get("content") or ""
            response_field_used = "message.content"

    return {
        "node": node,
        "ip": ip,
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "response": response_text,
        "thinking": thinking_text,
        "raw_response_keys": raw_response_keys,
        "response_field_used": response_field_used,
        "response_text_len": len(response_text),
        "thinking_text_len": len(thinking_text),
        "thinking_present": bool(thinking_text),
        "empty_response_text": len(response_text) == 0,
        "thinking_disabled_requested": think is False,
        "done": data.get("done") if isinstance(data, dict) else None,
        "done_reason": data.get("done_reason") if isinstance(data, dict) else None,
        "prompt_eval_count": data.get("prompt_eval_count") if isinstance(data, dict) else None,
        "eval_count": data.get("eval_count") if isinstance(data, dict) else None,
        "raw": data,
    }


async def run_single_generate_test(
    nodes: Dict[str, str],
    model: str,
    temperature: float,
    seed: int,
    num_predict: int,
    think: bool,
) -> Dict[str, Any]:
    node = "C"
    ip = nodes[node]
    prompt = "테스트입니다. 한 문장으로 응답하세요."

    async with aiohttp.ClientSession() as session:
        result = await ollama_generate(
            session=session,
            node=node,
            ip=ip,
            model=model,
            prompt=prompt,
            temperature=temperature,
            seed=seed,
            num_predict=num_predict,
            think=think,
        )

    return result


def response_debug(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "raw_response_keys": result.get("raw_response_keys", []),
        "response_field_used": result.get("response_field_used", "none"),
        "response_text_len": result.get("response_text_len", len(result.get("response", "") or "")),
        "thinking_text_len": result.get("thinking_text_len", len(result.get("thinking", "") or "")),
        "thinking_present": result.get("thinking_present", bool(result.get("thinking"))),
        "empty_response_text": result.get("empty_response_text", not bool(result.get("response"))),
        "thinking_disabled_requested": result.get("thinking_disabled_requested"),
        "done": result.get("done"),
        "done_reason": result.get("done_reason"),
        "prompt_eval_count": result.get("prompt_eval_count"),
        "eval_count": result.get("eval_count"),
    }


async def run_turn_concurrent(
    run_id: str,
    turn_no: int,
    utterance: str,
    nodes: Dict[str, str],
    model: str,
    embedding_model: SentenceTransformer,
    rag_host: str,
    rag_port: int,
    collection_name: str,
    top_k: int,
    temperature: float,
    seed: int,
    num_predict: int,
    think: bool,
) -> Dict[str, Any]:
    rag_result = rag_retrieve(
        embedding_model=embedding_model,
        query=utterance,
        rag_host=rag_host,
        rag_port=rag_port,
        collection_name=collection_name,
        top_k=top_k,
    )

    rag_context = build_rag_context(rag_result)
    chunk_ids = [c.get("chunk_id") for c in rag_result["chunks"] if c.get("chunk_id")]

    prompts = {}
    rag_flags = {}
    prompt_hashes = {}

    for node in nodes:
        prompt, rag_injected, _ = build_prompt(
            node=node,
            utterance=utterance,
            rag_context=rag_context if node in ("A", "B") else None,
        )
        prompts[node] = prompt
        rag_flags[node] = rag_injected
        prompt_hashes[node] = sha256_text(prompt)

    async with aiohttp.ClientSession() as session:
        tasks = []
        for node, ip in nodes.items():
            tasks.append(
                ollama_generate(
                    session=session,
                    node=node,
                    ip=ip,
                    model=model,
                    prompt=prompts[node],
                    temperature=temperature,
                    seed=seed,
                    num_predict=num_predict,
                    think=think,
                )
            )

        started = time.perf_counter()
        responses = await asyncio.gather(*tasks)
        gather_elapsed_ms = (time.perf_counter() - started) * 1000

    turn_rows = []
    for r in responses:
        node = r["node"]
        row = {
            "run_id": run_id,
            "timestamp": now_iso(),
            "turn": turn_no,
            "node": node,
            "node_ip": nodes[node],
            "model": model,
            "temperature": temperature,
            "seed": seed,
            "utterance": utterance,
            "rag_injected": 1 if rag_flags[node] else 0,
            "retrieved_chunk_ids": chunk_ids if rag_flags[node] else [],
            "prompt_sha256": prompt_hashes[node],
            "response_sha256": sha256_text(r.get("response", "")),
            "response_text": r.get("response", ""),
            "thinking_text": r.get("thinking", ""),
            **response_debug(r),
            "elapsed_ms": r.get("elapsed_ms"),
            "ok": r.get("ok"),
            "error_or_raw": r.get("raw") if not r.get("ok") else None,
        }
        turn_rows.append(row)

    return {
        "turn": turn_no,
        "utterance": utterance,
        "rag_result": {
            "collection": rag_result["collection"],
            "collection_count": rag_result["collection_count"],
            "top_k": rag_result["top_k"],
            "chunks": [
                {
                    "rank": c["rank"],
                    "distance": c["distance"],
                    "chunk_id": c["chunk_id"],
                    "source_label": c["source_label"],
                    "metadata": c["metadata"],
                    "document_preview": c["document"][:500],
                }
                for c in rag_result["chunks"]
            ],
        },
        "gather_elapsed_ms": gather_elapsed_ms,
        "rows": turn_rows,
    }


def check_paths(experiment_dir: Path, scenario_dir: Path, scenario_file: Optional[str]) -> Dict[str, Any]:
    result = {
        "experiment_dir": str(experiment_dir),
        "experiment_dir_exists": experiment_dir.exists(),
        "scenario_dir": str(scenario_dir),
        "scenario_dir_exists": scenario_dir.exists(),
        "scenario_file": scenario_file,
        "scenario_file_exists": Path(scenario_file).exists() if scenario_file else None,
    }
    return result


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


async def main_async(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_harness_smoke"

    experiment_dir = Path(args.experiment_dir)
    scenario_dir = Path(args.scenario_dir)
    log_dir = Path(args.log_dir)
    ensure_dir(log_dir)

    turn_log_path = log_dir / f"{run_id}_turn_logs.jsonl"
    rag_log_path = log_dir / f"{run_id}_rag_logs.jsonl"
    summary_path = log_dir / f"{run_id}_summary.json"

    nodes = {
        "A": args.node_a,
        "B": args.node_b,
        "C": args.node_c,
    }

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": now_iso(),
        "internet_assumption": "offline_or_airgap_ready",
        "nodes": nodes,
        "rag_host": args.rag_host,
        "rag_port": args.rag_port,
        "collection": args.collection,
        "embedding_model": args.embedding_model,
        "temperature": args.temperature,
        "seed": args.seed,
        "top_k": args.top_k,
        "num_predict": args.num_predict,
        "think": args.think,
        "thinking_disabled_requested": args.think is False,
        "checks": {},
        "results": {},
    }

    print_section("1. Path check")
    path_check = check_paths(experiment_dir, scenario_dir, args.scenario_file)
    summary["checks"]["paths"] = path_check
    print(json.dumps(path_check, ensure_ascii=False, indent=2))

    print_section("2. Ollama API tags check")
    tag_results = await check_ollama_tags(nodes)
    summary["checks"]["ollama_tags"] = tag_results

    for node, result in tag_results.items():
        print(f"Node {node} {nodes[node]} ok={result['ok']} elapsed_ms={result['elapsed_ms']:.2f}")
        if not result["ok"]:
            print("  payload:", result["payload"])

    if not all(r["ok"] for r in tag_results.values()):
        print("ERROR: Some Ollama nodes are not reachable.")
        write_json(summary_path, summary)
        return 2

    print_section("3. Model/digest consistency check")
    model_info = select_common_model(tag_results, args.model)
    summary["checks"]["model_info"] = model_info
    print(json.dumps({
        "selected_model": model_info["selected_model"],
        "presence": model_info["presence"],
        "digests": model_info["digests"],
        "digest_consistent": model_info["digest_consistent"],
    }, ensure_ascii=False, indent=2))

    if not all(model_info["presence"].values()):
        print("ERROR: Selected model does not exist on all nodes.")
        write_json(summary_path, summary)
        return 3

    if not model_info["digest_consistent"]:
        print("WARNING: Model digest is not consistent across nodes.")
        if args.strict_digest:
            print("ERROR: strict_digest enabled. Stop.")
            write_json(summary_path, summary)
            return 4

    selected_model = model_info["selected_model"]

    print_section("4. Single-node generate test")
    single_result = await run_single_generate_test(
        nodes=nodes,
        model=selected_model,
        temperature=args.temperature,
        seed=args.seed,
        num_predict=args.num_predict,
        think=args.think,
    )
    summary["checks"]["single_generate"] = single_result
    print(json.dumps({
        "node": single_result["node"],
        "ok": single_result["ok"],
        "elapsed_ms": single_result["elapsed_ms"],
        "response_preview": single_result.get("response", "")[:300],
        **response_debug(single_result),
    }, ensure_ascii=False, indent=2))

    if not single_result["ok"]:
        print("ERROR: Single-node generate test failed.")
        write_json(summary_path, summary)
        return 5

    print_section("5. Load embedding model in local_files_only mode")
    try:
        embedding_model = load_embedding_model(args.embedding_model)
        vec = embedding_model.encode("수급자격 확인", normalize_embeddings=True)
        embedding_check = {
            "ok": True,
            "dimension": len(vec),
            "first5": [float(x) for x in vec[:5]],
        }
    except Exception as e:
        embedding_check = {
            "ok": False,
            "error": repr(e),
        }
        summary["checks"]["embedding_model"] = embedding_check
        print(json.dumps(embedding_check, ensure_ascii=False, indent=2))
        write_json(summary_path, summary)
        return 6

    summary["checks"]["embedding_model"] = embedding_check
    print(json.dumps(embedding_check, ensure_ascii=False, indent=2))

    print_section("6. Load scenario")
    turns = load_scenario(args.scenario_file)
    if args.max_turns:
        turns = turns[:args.max_turns]
    summary["checks"]["scenario"] = {
        "turn_count": len(turns),
        "turns": turns,
    }
    print(json.dumps(summary["checks"]["scenario"], ensure_ascii=False, indent=2))

    if not turns:
        print("ERROR: No turns to run.")
        write_json(summary_path, summary)
        return 7

    print_section("7. One-turn concurrent smoke test")
    first = turns[0]
    first_result = await run_turn_concurrent(
        run_id=run_id,
        turn_no=first["turn"],
        utterance=first["utterance"],
        nodes=nodes,
        model=selected_model,
        embedding_model=embedding_model,
        rag_host=args.rag_host,
        rag_port=args.rag_port,
        collection_name=args.collection,
        top_k=args.top_k,
        temperature=args.temperature,
        seed=args.seed,
        num_predict=args.num_predict,
        think=args.think,
    )

    write_jsonl(turn_log_path, first_result["rows"])
    write_jsonl(rag_log_path, [{
        "run_id": run_id,
        "timestamp": now_iso(),
        "turn": first_result["turn"],
        "utterance": first_result["utterance"],
        "rag_result": first_result["rag_result"],
    }])

    print(json.dumps({
        "turn": first_result["turn"],
        "gather_elapsed_ms": first_result["gather_elapsed_ms"],
        "collection_count": first_result["rag_result"]["collection_count"],
        "retrieved_chunk_ids": [c["chunk_id"] for c in first_result["rag_result"]["chunks"]],
        "node_results": [
            {
                "node": r["node"],
                "ok": r["ok"],
                "rag_injected": r["rag_injected"],
                "elapsed_ms": r["elapsed_ms"],
                "response_preview": r["response_text"][:200],
                "response_text_len": r["response_text_len"],
                "thinking_text_len": r["thinking_text_len"],
                "thinking_present": r["thinking_present"],
                "empty_response_text": r["empty_response_text"],
                "response_field_used": r["response_field_used"],
                "thinking_disabled_requested": r["thinking_disabled_requested"],
                "done_reason": r["done_reason"],
                "eval_count": r["eval_count"],
                "prompt_eval_count": r["prompt_eval_count"],
            }
            for r in first_result["rows"]
        ],
    }, ensure_ascii=False, indent=2))

    summary["results"]["one_turn"] = {
        "turn": first_result["turn"],
        "gather_elapsed_ms": first_result["gather_elapsed_ms"],
        "collection_count": first_result["rag_result"]["collection_count"],
        "retrieved_chunk_ids": [c["chunk_id"] for c in first_result["rag_result"]["chunks"]],
        "rows_ok": [r["ok"] for r in first_result["rows"]],
        "response_text_lengths": {r["node"]: r["response_text_len"] for r in first_result["rows"]},
        "thinking_text_lengths": {r["node"]: r["thinking_text_len"] for r in first_result["rows"]},
        "thinking_present": {r["node"]: r["thinking_present"] for r in first_result["rows"]},
        "empty_response_text": {r["node"]: r["empty_response_text"] for r in first_result["rows"]},
        "rag_flags": {r["node"]: r["rag_injected"] for r in first_result["rows"]},
    }

    print_section("8. Mini test")
    mini_results = []

    remaining_turns = turns[1:]
    for turn in remaining_turns:
        result = await run_turn_concurrent(
            run_id=run_id,
            turn_no=turn["turn"],
            utterance=turn["utterance"],
            nodes=nodes,
            model=selected_model,
            embedding_model=embedding_model,
            rag_host=args.rag_host,
            rag_port=args.rag_port,
            collection_name=args.collection,
            top_k=args.top_k,
            temperature=args.temperature,
            seed=args.seed,
            num_predict=args.num_predict,
            think=args.think,
        )

        write_jsonl(turn_log_path, result["rows"])
        write_jsonl(rag_log_path, [{
            "run_id": run_id,
            "timestamp": now_iso(),
            "turn": result["turn"],
            "utterance": result["utterance"],
            "rag_result": result["rag_result"],
        }])

        mini_results.append({
            "turn": result["turn"],
            "gather_elapsed_ms": result["gather_elapsed_ms"],
            "collection_count": result["rag_result"]["collection_count"],
            "retrieved_chunk_ids": [c["chunk_id"] for c in result["rag_result"]["chunks"]],
            "rows_ok": [r["ok"] for r in result["rows"]],
            "response_text_lengths": {r["node"]: r["response_text_len"] for r in result["rows"]},
            "thinking_text_lengths": {r["node"]: r["thinking_text_len"] for r in result["rows"]},
            "thinking_present": {r["node"]: r["thinking_present"] for r in result["rows"]},
            "empty_response_text": {r["node"]: r["empty_response_text"] for r in result["rows"]},
            "rag_flags": {r["node"]: r["rag_injected"] for r in result["rows"]},
        })

        print(json.dumps(mini_results[-1], ensure_ascii=False, indent=2))

    summary["results"]["mini_test"] = mini_results

    print_section("9. Final validation")
    one_turn_generation_quality_ready = all(
        length > 0 for length in summary["results"]["one_turn"]["response_text_lengths"].values()
    )
    mini_generation_quality_ready = all(
        all(length > 0 for length in item["response_text_lengths"].values())
        for item in mini_results
    ) if mini_results else True
    one_turn_thinking_present_rows = sum(
        1 for present in summary["results"]["one_turn"]["thinking_present"].values() if present
    )
    mini_thinking_present_rows = sum(
        1
        for item in mini_results
        for present in item["thinking_present"].values()
        if present
    )
    thinking_present_rows = one_turn_thinking_present_rows + mini_thinking_present_rows
    thinking_control_effective = thinking_present_rows == 0
    path_ready = all([
        summary["results"]["one_turn"]["collection_count"] > 0,
        all(summary["results"]["one_turn"]["rows_ok"]),
        summary["results"]["one_turn"]["rag_flags"] == {"A": 1, "B": 1, "C": 0},
        all(all(item["rows_ok"]) for item in mini_results) if mini_results else True,
        all(item["rag_flags"] == {"A": 1, "B": 1, "C": 0} for item in mini_results) if mini_results else True,
    ])

    validation = {
        "path_ready": path_ready,
        "generation_quality_ready": all([
            one_turn_generation_quality_ready,
            mini_generation_quality_ready,
        ]),
        "thinking_disabled_requested": args.think is False,
        "thinking_present_rows": thinking_present_rows,
        "thinking_control_effective": thinking_control_effective,
        "one_turn_generation_quality_ready": one_turn_generation_quality_ready,
        "mini_generation_quality_ready": mini_generation_quality_ready,
        "rag_collection_ready": summary["results"]["one_turn"]["collection_count"] > 0,
        "one_turn_all_nodes_ok": all(summary["results"]["one_turn"]["rows_ok"]),
        "one_turn_rag_flags_expected": summary["results"]["one_turn"]["rag_flags"] == {"A": 1, "B": 1, "C": 0},
        "mini_all_nodes_ok": all(
            all(item["rows_ok"]) for item in mini_results
        ) if mini_results else True,
        "mini_rag_flags_expected": all(
            item["rag_flags"] == {"A": 1, "B": 1, "C": 0}
            for item in mini_results
        ) if mini_results else True,
        "turn_log_path": str(turn_log_path),
        "rag_log_path": str(rag_log_path),
        "summary_path": str(summary_path),
    }

    validation["overall_ready"] = all([
        validation["path_ready"],
        validation["generation_quality_ready"],
        validation["thinking_control_effective"],
    ])

    summary["validation"] = validation
    summary["finished_at"] = now_iso()

    write_json(summary_path, summary)

    print(json.dumps(validation, ensure_ascii=False, indent=2))

    if validation["overall_ready"]:
        print("\nRESULT: HARNESS_ORCHESTRATION_SMOKE_TEST_READY")
        return 0

    print("\nRESULT: HARNESS_ORCHESTRATION_SMOKE_TEST_FAILED")
    return 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--run-id", default=None)
    parser.add_argument("--experiment-dir", default="/home/morophi/experiment")
    parser.add_argument("--scenario-dir", default="/home/morophi/scenario")
    parser.add_argument("--scenario-file", default=None)
    parser.add_argument("--log-dir", default="/home/morophi/logs/test_run")

    parser.add_argument("--node-a", default="10.1.1.10")
    parser.add_argument("--node-b", default="10.1.1.20")
    parser.add_argument("--node-c", default="10.1.1.30")

    parser.add_argument("--rag-host", default="10.1.1.120")
    parser.add_argument("--rag-port", type=int, default=8000)
    parser.add_argument("--collection", default="lacp_docs")

    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--model", default=None, help="Ollama model name. If omitted, auto-select.")
    parser.add_argument("--strict-digest", action="store_true")

    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-predict", type=int, default=128)
    parser.add_argument(
        "--think",
        type=parse_bool,
        default=False,
        help="Top-level Ollama /api/generate think flag. Defaults to false.",
    )
    parser.add_argument("--max-turns", type=int, default=3)

    return parser.parse_args()


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as e:
        print("FATAL:", repr(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
