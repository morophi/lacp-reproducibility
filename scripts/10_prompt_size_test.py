"""
Step 10: Build top-k=3 prompts and measure prompt size.

Change reason:
    The v2 corpus is valid for LACP only if top-k=3 evidence fits within the
    BC-250 + Qwen3 8B + Ollama num_ctx=4096 operating envelope. This script
    stores Harness-ready prompts and records retrieval-trigger exposure metrics.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")
DEFAULT_QUERIES = (
    "수급자격 확인",
    "기초생활보장 생계급여 기준",
    "소득인정액 기준",
    "신청 절차",
    "가구원수별 기준 중위소득",
)
PROMPT_TEMPLATE = """당신은 LACP 실험의 복지정책 판단 에이전트입니다.
아래 RAG 검색 결과만 근거 문서로 사용하되, 문서에 없는 내용은 추정하지 마십시오.

[RAG_CONTEXT]
{rag_context}

[USER_QUERY]
{query_text}

[RESPONSE_INSTRUCTION]
수급자격, 기준, 신청 절차, 예외 조건을 구분해 간결하게 답하십시오.
"""


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("ingest_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create top-k prompts and size logs.")
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--chroma-path", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--query", action="append", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--prompt-dir", type=Path, default=None)
    parser.add_argument("--legacy-final-prompt-chars", type=int, default=5888)
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--ollama-model", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    collection_name = args.collection_name or config.COLLECTION_NAME
    chroma_path = args.chroma_path or config.CHROMADB_PATH
    queries = tuple(args.query or DEFAULT_QUERIES)
    output_path = args.output or config.DIRS.logs / f"{config.ARTIFACT_PREFIX}_{config.RUN_ID}_prompt_size_test.json"
    prompt_dir = args.prompt_dir or config.DIRS.logs / f"{config.ARTIFACT_PREFIX}_{config.RUN_ID}_ab_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    collection_count, retrievals = retrieve(config, chroma_path, collection_name, queries, args.top_k)
    results = []
    for item in retrievals:
        prompt = build_prompt(item["query_text"], item["documents"])
        prompt_path = prompt_dir / f"topk{args.top_k}_{safe_name(item['query_text'])}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        final_prompt_chars = len(prompt)
        reduction = reduction_percent(args.legacy_final_prompt_chars, final_prompt_chars)
        result = {
            **{key: value for key, value in item.items() if key != "documents"},
            "prompt_file": str(prompt_path),
            "final_prompt_chars": final_prompt_chars,
            "doc_lengths": [len(doc) for doc in item["documents"]],
            "rag_context_chars": context_chars(item["documents"]),
            "legacy_final_prompt_chars": args.legacy_final_prompt_chars,
            "prompt_chars_reduction_percent": reduction,
            "under_3500_chars": final_prompt_chars <= 3500,
            "estimated_under_4096_tokens": estimate_tokens(final_prompt_chars) < 4096,
        }
        if args.ollama_url and args.ollama_model:
            result["ollama"] = run_ollama_prompt_eval(args.ollama_url, args.ollama_model, prompt)
        results.append(result)

    payload = {
        "step": "10_prompt_size_test",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_name": collection_name,
        "collection_count": collection_count,
        "corpus_version": config.CORPUS_VERSION,
        "top_k": args.top_k,
        "prompt_dir": str(prompt_dir),
        "results": results,
        "ab_concurrent_generation_command": (
            f"python run_exam_test.py --rag-collection {collection_name} "
            f"--top-k {args.top_k} --prompt-dir {prompt_dir}"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def retrieve(
    config: Any,
    chroma_path: Path,
    collection_name: str,
    queries: tuple[str, ...],
    top_k: int,
) -> tuple[int, list[dict[str, Any]]]:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("chromadb and sentence-transformers are required.") from exc

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_collection(collection_name)
    collection_count = collection.count()
    model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    vectors = model.encode(
        list(queries),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    items = []
    for query_text, vector in zip(queries, vectors):
        response = collection.query(
            query_embeddings=[vector.astype("float32").tolist()],
            n_results=top_k,
            include=["documents", "metadatas"],
        )
        docs = response.get("documents", [[]])[0]
        metas = response.get("metadatas", [[]])[0]
        block_types = [str(meta.get("block_type", "")) for meta in metas]
        table_ids = [str(meta.get("table_id", "")) for meta in metas if meta.get("table_id")]
        items.append(
            {
                "query_text": query_text,
                "top_k": top_k,
                "returned_count": len(docs),
                "retrieved_chunk_ids": [str(meta.get("chunk_id", "")) for meta in metas],
                "block_type_distribution": distribution(block_types),
                "table_id_included": bool(table_ids),
                "table_ids": table_ids,
                "chunk_lengths": [int(meta.get("chunk_chars", len(doc))) for meta, doc in zip(metas, docs)],
                "collection_name": collection_name,
                "corpus_version": config.CORPUS_VERSION,
                "documents": docs,
            }
        )
    return collection_count, items


def build_prompt(query_text: str, documents: list[str]) -> str:
    rag_context = "\n\n---\n\n".join(
        f"[DOC {idx + 1}]\n{doc}" for idx, doc in enumerate(documents)
    )
    return PROMPT_TEMPLATE.format(rag_context=rag_context, query_text=query_text)


def context_chars(documents: list[str]) -> int:
    return len("\n\n---\n\n".join(documents))


def estimate_tokens(chars: int) -> int:
    return int(chars / 1.45)


def reduction_percent(old: int, new: int) -> float:
    if old <= 0:
        return 0.0
    return round((old - new) / old * 100, 2)


def safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
    return safe[:80] or "query"


def distribution(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def run_ollama_prompt_eval(url: str, model: str, prompt: str) -> dict[str, Any]:
    try:
        import requests
    except ImportError:
        return {"status": "skipped", "reason": "requests is not installed"}
    endpoint = url.rstrip("/") + "/api/generate"
    response = requests.post(
        endpoint,
        json={"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": 1}},
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "status": "ok",
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
