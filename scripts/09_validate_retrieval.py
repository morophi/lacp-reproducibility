"""
Step 09: Validate top-k=3 retrieval against the v2 ChromaDB collection.

Change reason:
    LACP treats RAG evidence as a causal intervention, so small chunking can
    change trigger exposure. This script logs retrieval composition, table
    presence, context size, and chunk lengths for contamination review.
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
        docs = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        chunk_ids = [str(meta.get("chunk_id", "")) for meta in metadatas]
        chunk_lengths = [int(meta.get("chunk_chars", len(doc))) for meta, doc in zip(metadatas, docs)]
        block_types = [str(meta.get("block_type", "")) for meta in metadatas]
        table_ids = [str(meta.get("table_id", "")) for meta in metadatas if meta.get("table_id")]
        rag_context_chars = context_chars(docs)
        result = {
            "query_text": query_text,
            "top_k": top_k,
            "returned_count": len(docs),
            "retrieved_chunk_ids": chunk_ids,
            "block_type_distribution": distribution(block_types),
            "table_id_included": bool(table_ids),
            "table_ids": table_ids,
            "rag_context_chars": rag_context_chars,
            "estimated_prompt_chars": estimate_prompt_chars(query_text, docs),
            "chunk_lengths": chunk_lengths,
            "collection_name": collection_name,
            "corpus_version": config.CORPUS_VERSION,
            "results": [
                {
                    "rank": idx + 1,
                    "chunk_id": chunk_ids[idx],
                    "block_type": block_types[idx],
                    "table_id": metadatas[idx].get("table_id", ""),
                    "chunk_chars": chunk_lengths[idx],
                    "distance": distances[idx] if idx < len(distances) else None,
                    "text_head": docs[idx][:head_chars],
                }
                for idx in range(len(docs))
            ],
        }
        results.append(result)
    return collection_count, results


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
