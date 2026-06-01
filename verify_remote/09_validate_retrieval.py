"""
Step 09: Validate retrieval against the v2 ChromaDB collection.

Change reason:
    LACP treats RAG evidence as a causal intervention, so small chunking can
    change trigger exposure. This script logs retrieval composition, table
    presence, context size, and chunk lengths for contamination review.

    The hybrid fallback added here does not mutate chunks or ChromaDB content.
    It only validates table exposure by adding lexical table candidates when
    table-sensitive queries fail to surface table chunks in vector top-k.
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
TABLE_SENSITIVE_TERMS = (
    "기준 중위소득",
    "가구원수",
    "가구원 수",
    "생계급여 기준",
    "소득인정액",
    "선정기준",
    "금액",
    "원",
    "2026",
)


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("ingest_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval sanity checks.")
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--chroma-path", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--query", action="append", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--head-chars", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    collection_name = args.collection_name or config.COLLECTION_NAME
    chroma_path = args.chroma_path or config.CHROMADB_PATH
    queries = tuple(args.query or DEFAULT_QUERIES)
    output_path = args.output or config.DIRS.logs / f"{config.ARTIFACT_PREFIX}_{config.RUN_ID}_retrieval_validation.json"

    collection_count, results = run_validation(config, chroma_path, collection_name, queries, args.top_k, args.head_chars)
    payload = {
        "step": "09_validate_retrieval",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_name": collection_name,
        "collection_count": collection_count,
        "corpus_version": config.CORPUS_VERSION,
        "top_k": args.top_k,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_validation(
    config: Any,
    chroma_path: Path,
    collection_name: str,
    queries: tuple[str, ...],
    top_k: int,
    head_chars: int,
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
    query_vectors = model.encode(
        list(queries),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    results: list[dict[str, Any]] = []
    for query_text, vector in zip(queries, query_vectors):
        response = collection.query(
            query_embeddings=[vector.astype("float32").tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        vector_items = response_items(response)
        vector_summary = summarize_items(
            query_text,
            vector_items,
            top_k,
            collection_name,
            config.CORPUS_VERSION,
            head_chars,
        )
        table_sensitive = is_table_sensitive_query(query_text)
        lexical_items = lexical_table_candidates(collection, query_text, limit=max(top_k, 5))
        final_items, retrieval_method = merge_with_table_fallback(
            vector_items,
            lexical_items,
            top_k,
            table_sensitive,
        )
        docs = [item["document"] for item in final_items]
        metadatas = [item["metadata"] for item in final_items]
        distances = [item.get("distance") for item in final_items]
        sources = [item["source"] for item in final_items]
        chunk_ids = [str(meta.get("chunk_id", "")) for meta in metadatas]
        chunk_lengths = [int(meta.get("chunk_chars", len(doc))) for meta, doc in zip(metadatas, docs)]
        block_types = [str(meta.get("block_type", "")) for meta in metadatas]
        table_ids = [str(meta.get("table_id", "")) for meta in metadatas if meta.get("table_id")]
        rag_context_chars = context_chars(docs)
        result = {
            "query_text": query_text,
            "top_k": top_k,
            "returned_count": len(docs),
            "table_sensitive_query": table_sensitive,
            "retrieval_method": retrieval_method,
            "table_exposure": bool(table_ids),
            "retrieved_chunk_ids": chunk_ids,
            "block_type_distribution": distribution(block_types),
            "table_id_included": bool(table_ids),
            "table_ids": table_ids,
            "rag_context_chars": rag_context_chars,
            "estimated_prompt_chars": estimate_prompt_chars(query_text, docs),
            "chunk_lengths": chunk_lengths,
            "retrieval_sources": distribution(sources),
            "collection_name": collection_name,
            "corpus_version": config.CORPUS_VERSION,
            "vector_only_result": vector_summary,
            "lexical_table_candidate_count": len(lexical_items),
            "lexical_table_candidate_ids": [
                str(item["metadata"].get("chunk_id", "")) for item in lexical_items[:top_k]
            ],
            "results": [
                {
                    "rank": idx + 1,
                    "chunk_id": chunk_ids[idx],
                    "block_type": block_types[idx],
                    "table_id": metadatas[idx].get("table_id", ""),
                    "chunk_chars": chunk_lengths[idx],
                    "distance": distances[idx] if idx < len(distances) else None,
                    "retrieval_source": sources[idx],
                    "text_head": docs[idx][:head_chars],
                }
                for idx in range(len(docs))
            ],
        }
        results.append(result)
    return collection_count, results


def response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    docs = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]
    return [
        {
            "document": docs[idx],
            "metadata": metadatas[idx],
            "distance": distances[idx] if idx < len(distances) else None,
            "source": "vector",
        }
        for idx in range(len(docs))
    ]


def summarize_items(
    query_text: str,
    items: list[dict[str, Any]],
    top_k: int,
    collection_name: str,
    corpus_version: str,
    head_chars: int,
) -> dict[str, Any]:
    docs = [item["document"] for item in items]
    metadatas = [item["metadata"] for item in items]
    chunk_ids = [str(meta.get("chunk_id", "")) for meta in metadatas]
    chunk_lengths = [
        int(meta.get("chunk_chars", len(doc))) for meta, doc in zip(metadatas, docs)
    ]
    block_types = [str(meta.get("block_type", "")) for meta in metadatas]
    table_ids = [str(meta.get("table_id", "")) for meta in metadatas if meta.get("table_id")]
    return {
        "query_text": query_text,
        "top_k": top_k,
        "returned_count": len(items),
        "retrieval_method": "vector_only",
        "table_exposure": bool(table_ids),
        "retrieved_chunk_ids": chunk_ids,
        "block_type_distribution": distribution(block_types),
        "table_id_included": bool(table_ids),
        "table_ids": table_ids,
        "rag_context_chars": context_chars(docs),
        "estimated_prompt_chars": estimate_prompt_chars(query_text, docs),
        "chunk_lengths": chunk_lengths,
        "collection_name": collection_name,
        "corpus_version": corpus_version,
        "results": [
            {
                "rank": idx + 1,
                "chunk_id": chunk_ids[idx],
                "block_type": block_types[idx],
                "table_id": metadatas[idx].get("table_id", ""),
                "chunk_chars": chunk_lengths[idx],
                "distance": items[idx].get("distance"),
                "retrieval_source": "vector",
                "text_head": docs[idx][:head_chars],
            }
            for idx in range(len(items))
        ],
    }


def is_table_sensitive_query(query_text: str) -> bool:
    normalized = compact_spaces(query_text)
    return any(compact_spaces(term) in normalized for term in TABLE_SENSITIVE_TERMS)


def compact_spaces(value: str) -> str:
    return "".join((value or "").split())


def lexical_table_candidates(collection: Any, query_text: str, limit: int) -> list[dict[str, Any]]:
    if not is_table_sensitive_query(query_text):
        return []
    try:
        response = collection.get(
            where={"block_type": "table"},
            include=["documents", "metadatas"],
        )
    except Exception:
        return []
    docs = response.get("documents", [])
    metas = response.get("metadatas", [])
    ids = response.get("ids", [])
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, (doc, meta) in enumerate(zip(docs, metas)):
        score = lexical_score(query_text, doc, meta)
        if score <= 0:
            continue
        if "id" not in meta and idx < len(ids):
            meta = {**meta, "id": ids[idx]}
        scored.append(
            (
                score,
                -int(meta.get("chunk_chars", len(doc))),
                {
                    "document": doc,
                    "metadata": meta,
                    "distance": None,
                    "source": "lexical",
                    "lexical_score": score,
                },
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in scored[:limit]]


def lexical_score(query_text: str, document: str, metadata: dict[str, Any]) -> int:
    query = compact_spaces(query_text)
    haystack = compact_spaces(
        "\n".join(
            [
                document,
                str(metadata.get("table_title", "")),
                str(metadata.get("columns", "")),
                str(metadata.get("section", "")),
                str(metadata.get("year", "")),
                str(metadata.get("unit", "")),
            ]
        )
    )
    score = 0
    for term in TABLE_SENSITIVE_TERMS:
        normalized_term = compact_spaces(term)
        if normalized_term in query and normalized_term in haystack:
            score += 10
        elif normalized_term in query:
            score += 1 if normalized_term in haystack else 0
    for token in query_terms(query_text):
        if token and compact_spaces(token) in haystack:
            score += 2
    return score


def query_terms(query_text: str) -> list[str]:
    return [term for term in re_split_query(query_text) if len(compact_spaces(term)) >= 2]


def re_split_query(query_text: str) -> list[str]:
    return [part.strip() for part in query_text.replace("별", " ").split()]


def merge_with_table_fallback(
    vector_items: list[dict[str, Any]],
    lexical_items: list[dict[str, Any]],
    top_k: int,
    table_sensitive: bool,
) -> tuple[list[dict[str, Any]], str]:
    vector_table_exposure = any(item["metadata"].get("table_id") for item in vector_items)
    if not table_sensitive or vector_table_exposure or not lexical_items:
        mark_hybrid_overlaps(vector_items, lexical_items)
        return vector_items[:top_k], "vector_only"

    used_ids = {str(item["metadata"].get("chunk_id", "")) for item in vector_items}
    lexical_additions = [
        item for item in lexical_items if str(item["metadata"].get("chunk_id", "")) not in used_ids
    ]
    if not lexical_additions:
        mark_hybrid_overlaps(vector_items, lexical_items)
        return vector_items[:top_k], "vector_only"

    keep_count = max(top_k - 1, 0)
    final_items = vector_items[:keep_count] + [lexical_additions[0]]
    mark_hybrid_overlaps(final_items, lexical_items)
    return final_items[:top_k], "hybrid_table_fallback"


def mark_hybrid_overlaps(
    final_items: list[dict[str, Any]],
    lexical_items: list[dict[str, Any]],
) -> None:
    lexical_ids = {str(item["metadata"].get("chunk_id", "")) for item in lexical_items}
    for item in final_items:
        chunk_id = str(item["metadata"].get("chunk_id", ""))
        if item.get("source") == "vector" and chunk_id in lexical_ids:
            item["source"] = "hybrid"


def context_chars(documents: list[str]) -> int:
    return len("\n\n---\n\n".join(documents))


def estimate_prompt_chars(query_text: str, documents: list[str]) -> int:
    template_overhead = 1200
    return template_overhead + len(query_text) + context_chars(documents)


def distribution(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
