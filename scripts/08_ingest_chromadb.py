"""
Step 08: Ingest embeddings into a protected, versioned ChromaDB collection.

Change reason:
    The original `lacp_docs` large-chunk collection must remain intact. This
    script writes only to a new versioned collection such as
    `lacp_docs_v1_full_guideline_table_safe` or `lacp_docs_v2_table_safe` and
    refuses to target the legacy collection name.
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


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("ingest_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load chunk embeddings into ChromaDB.")
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--embeddings", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--chroma-path", type=Path, default=None)
    parser.add_argument(
        "--corpus-version",
        default=None,
        help=(
            "Corpus version to stamp on the Chroma collection metadata. "
            "Use this for local validation packages whose version differs from ingest_config defaults."
        ),
    )
    parser.add_argument(
        "--embedding-text-policy",
        default=None,
        help=(
            "Optional collection-level note describing what text was embedded, "
            "for example original_with_source_boundary."
        ),
    )
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument(
        "--ingest-scope",
        choices=("validation", "rag_node"),
        default="validation",
        help=(
            "Stamp the collection metadata with the operational scope of this ingest. "
            "The default remains validation so existing local Chroma checks keep their "
            "non-active identity. Use rag_node only from the explicit RAG-node write "
            "automation after the target collection/path have been audited."
        ),
    )
    parser.add_argument(
        "--reset-new-collection",
        action="store_true",
        help="Delete and recreate only the configured versioned collection.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    collection_name = args.collection_name or config.COLLECTION_NAME
    chroma_path = args.chroma_path or config.CHROMADB_PATH
    chunks_path = args.chunks or config.CHUNKS_JSONL
    embeddings_path = args.embeddings or config.EMBEDDINGS_NPY
    metadata_path = args.metadata or config.EMBEDDINGS_META_JSONL
    corpus_version = args.corpus_version or config.CORPUS_VERSION
    embedding_text_policy = args.embedding_text_policy or "unspecified"

    payload = {
        "step": "08_ingest_chromadb",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "collection_name": collection_name,
        "legacy_collection_name": config.LEGACY_COLLECTION_NAME,
        "chromadb_path": str(chroma_path),
        "chunks_jsonl": str(chunks_path),
        "embeddings_npy": str(embeddings_path),
        "embedding_metadata_jsonl": str(metadata_path),
        "corpus_version": corpus_version,
        "embedding_text_policy": embedding_text_policy,
        "ingest_scope": args.ingest_scope,
        "chunks_jsonl_exists": chunks_path.exists(),
        "embeddings_npy_exists": embeddings_path.exists(),
        "embedding_metadata_jsonl_exists": metadata_path.exists(),
        "reset_new_collection": args.reset_new_collection,
    }

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    validate_collection_name(config, collection_name)
    chunks = load_jsonl(chunks_path)
    metadata_rows = load_jsonl(metadata_path)
    validate_inputs(chunks, metadata_rows)
    payload["chunk_count"] = len(chunks)

    try:
        import chromadb
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("chromadb and numpy are required for ChromaDB ingest.") from exc

    vectors = np.load(embeddings_path)
    if vectors.shape[0] != len(chunks):
        raise ValueError(
            f"Embedding row count mismatch: vectors={vectors.shape[0]} chunks={len(chunks)}"
        )

    client = chromadb.PersistentClient(path=str(chroma_path))
    if args.reset_new_collection:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            # Collection-level metadata is used by readiness audits to confirm
            # that the Chroma index identity matches the package manifest. Do
            # not rely only on ingest_config defaults here: local validation may
            # intentionally ingest a full-corpus v1 package while the reusable
            # ingest config still defaults to a v2 table-safe smoke corpus.
            "corpus_version": corpus_version,
            "embedding_model": config.EMBEDDING_MODEL_NAME,
            "embedding_dimension": int(vectors.shape[1]) if len(vectors.shape) > 1 else 0,
            "embedding_text_policy": embedding_text_policy,
            "created_by": "scripts/08_ingest_chromadb.py",
            # Keep validation and RAG-node writes distinguishable at collection
            # metadata level.  This is important for later readiness audits:
            # local validation collections must never be mistaken for an active
            # RAG-node collection, while an explicitly requested RAG-node write
            # should leave a positive, queryable provenance marker.
            "ingest_scope": args.ingest_scope,
            "validation_only": args.ingest_scope == "validation",
            "rag_node_ingest_executed": args.ingest_scope == "rag_node",
        },
    )

    ids = [row["chunk_id"] for row in chunks]
    documents = [row["text"] for row in chunks]
    metadatas = [flatten_metadata(row.get("metadata", {})) for row in chunks]
    embeddings = vectors.astype("float32").tolist()

    for start in range(0, len(ids), args.batch_size):
        end = start + args.batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )

    payload["collection_count"] = collection.count()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def validate_collection_name(config: Any, collection_name: str) -> None:
    if collection_name == config.LEGACY_COLLECTION_NAME or collection_name == "lacp_docs":
        raise ValueError(
            "Refusing to write to legacy active collection. Use a versioned lacp_docs_v*_ collection name."
        )

    # Keep the hard guard around the legacy active collection names above: this
    # script is often used during rebuild validation, and accidentally targeting
    # the active `lacp_docs` collection would mix experimental corpus rows into a
    # production-facing store. At the same time, local full-corpus validation may
    # legitimately use earlier or later versioned names such as
    # `lacp_docs_v1_full_guideline_table_safe` or `lacp_docs_v2_table_safe`.
    # Accept only that explicit versioned namespace so validation collections can
    # be created without weakening the legacy collection protection.
    if not collection_name.startswith("lacp_docs_v"):
        raise ValueError(
            "Collection name must start with lacp_docs_v* and must not be the legacy active collection."
        )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return rows


def validate_inputs(chunks: list[dict[str, Any]], metadata_rows: list[dict[str, Any]]) -> None:
    if not chunks:
        raise ValueError("No chunks to ingest.")
    if len(chunks) != len(metadata_rows):
        raise ValueError("Chunk JSONL and embedding metadata JSONL counts differ.")
    chunk_ids = [row["chunk_id"] for row in chunks]
    metadata_ids = [row["chunk_id"] for row in metadata_rows]
    if chunk_ids != metadata_ids:
        raise ValueError("Chunk order differs from embedding metadata order.")
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("Chunk IDs must be unique.")


def flatten_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    flattened: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            flattened[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            flattened[key] = value
        else:
            flattened[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return flattened


if __name__ == "__main__":
    raise SystemExit(main())
