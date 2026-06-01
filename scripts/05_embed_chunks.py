"""
Step 05: Chunk embedding.

Change reason:
    The v2 RAG corpus uses small, table-safe chunks with richer metadata so
    top-k=3 retrieval can stay within Ollama num_ctx=4096 without weakening the
    intervention to top-k=1. This stage preserves that metadata for ChromaDB.

Purpose:
    Create embeddings only from verified, approved chunks.

Policy basis:
    Embedding must happen after canonical markdown, semantic verification, and
    table-aware chunking. Raw PDF text and unapproved chunks must never be
    embedded.

This script refuses to embed unless the semantic gate is approved and a chunk
JSONL artifact exists. It writes vectors under embeddings/ and per-vector
metadata as JSONL.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    ordinal: int
    text: str
    text_sha256: str
    char_count: int
    pages: list[int]
    tags: list[str]
    block_types: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EmbeddingSurface:
    text: str
    text_sha256: str
    char_count: int


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("ingest_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed approved table-aware chunks."
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=None,
        help="Chunk JSONL path. Defaults to this run's path, then latest chunks.",
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=None,
        help="Semantic gate JSON. Defaults to this run's path, then latest gate.",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=None,
        help="Output .npy vector path. Defaults to ingest_config.py EMBEDDINGS_NPY.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Output embedding metadata JSONL. Defaults to ingest_config.py EMBEDDINGS_META_JSONL.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Embedding log JSON. Defaults to ingest_config.py EMBEDDING_LOG.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and policy gates without loading the embedding model.",
    )
    parser.add_argument(
        "--embedding-text-policy",
        choices=("original_with_source_boundary", "body_only_v1", "title_once_body_v1"),
        default="original_with_source_boundary",
        help=(
            "Controls the text surface sent to the embedding model. The chunk JSONL "
            "document text is still preserved for display/ingest; this switch is for "
            "diagnosing whether repeated provenance wrappers bias vector retrieval."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run deterministic chunk validation tests without loading a model.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    if args.self_test:
        run_self_test(config)
        return 0

    chunks_path, chunks_selection = resolve_chunks_path(config, args.chunks)
    gate_path, gate_selection = resolve_gate_path(config, args.gate)
    embeddings_path = args.embeddings or config.EMBEDDINGS_NPY
    metadata_path = args.metadata or config.EMBEDDINGS_META_JSONL
    log_path = args.log or config.EMBEDDING_LOG
    gate_payload = read_json(gate_path)
    gate_approved = gate_payload.get("approved_for_chunking") is True

    if args.dry_run:
        chunks = load_chunks(chunks_path)
        payload = build_dry_run_payload(
            config,
            chunks_path,
            chunks_selection,
            gate_path,
            gate_selection,
            gate_approved,
            embeddings_path,
            metadata_path,
            log_path,
            chunks,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if gate_approved else 2

    if not gate_approved:
        print(
            json.dumps(
                {
                    "step": "05_embed_chunks",
                    "status": "blocked",
                    "reason": "semantic gate is not approved for embedding",
                    "gate": str(gate_path),
                    "approved_for_chunking": gate_payload.get("approved_for_chunking"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    chunks = load_chunks(chunks_path)
    if not chunks:
        raise ValueError(f"No chunks to embed: {chunks_path}")

    config.ensure_output_dirs()
    surfaces = build_embedding_surfaces(chunks, args.embedding_text_policy)
    vectors, model_info = embed_chunks(config, surfaces)
    write_embeddings(embeddings_path, vectors)
    write_embedding_metadata(
        config,
        chunks_path,
        metadata_path,
        chunks,
        surfaces,
        vectors,
        args.embedding_text_policy,
    )
    log_payload = build_log_payload(
        config,
        chunks_path,
        chunks_selection,
        gate_path,
        gate_selection,
        embeddings_path,
        metadata_path,
        chunks,
        surfaces,
        vectors,
        model_info,
        args.embedding_text_policy,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(log_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"embeddings_npy={embeddings_path}")
    print(f"embedding_metadata={metadata_path}")
    print(f"embedding_log={log_path}")
    print(f"chunk_count={len(chunks)}")
    print(f"vector_dimension={len(vectors[0]) if len(vectors) else 0}")
    return 0


def resolve_chunks_path(config: Any, explicit_chunks: Path | None) -> tuple[Path, str]:
    if explicit_chunks is not None:
        if not explicit_chunks.exists():
            raise FileNotFoundError(f"Chunk JSONL not found: {explicit_chunks}")
        return explicit_chunks, "explicit"

    if config.CHUNKS_JSONL.exists():
        return config.CHUNKS_JSONL, "run_id"

    latest = config.latest_artifact(config.DIRS.chunks, "chunks", "jsonl")
    if latest is None:
        raise FileNotFoundError(
            "No chunk JSONL found. Run 04_chunk_table_aware.py after approval or pass --chunks."
        )
    return latest, "latest_fallback"


def resolve_gate_path(config: Any, explicit_gate: Path | None) -> tuple[Path, str]:
    if explicit_gate is not None:
        if not explicit_gate.exists():
            raise FileNotFoundError(f"Semantic gate not found: {explicit_gate}")
        return explicit_gate, "explicit"

    if config.SEMANTIC_GATE.exists():
        return config.SEMANTIC_GATE, "run_id"

    latest = config.latest_artifact(config.DIRS.manifest, "semantic_gate", "json")
    if latest is None:
        raise FileNotFoundError(
            "No semantic gate found. Run 03_semantic_verify_report.py first or pass --gate."
        )
    return latest, "latest_fallback"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}") from exc


def load_chunks(path: Path) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
            chunks.append(chunk_from_payload(payload, path, line_number))

    ordinals = [chunk.ordinal for chunk in chunks]
    if ordinals != sorted(ordinals):
        raise ValueError("Chunk ordinals must be sorted for deterministic embedding")
    if len(set(chunk.chunk_id for chunk in chunks)) != len(chunks):
        raise ValueError("Chunk IDs must be unique")
    return chunks


def chunk_from_payload(payload: dict[str, Any], path: Path, line_number: int) -> ChunkRecord:
    required = ("chunk_id", "ordinal", "text", "text_sha256", "char_count")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing keys {missing} at {path}:{line_number}")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Chunk text is empty at {path}:{line_number}")
    observed_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if observed_hash != payload["text_sha256"]:
        raise ValueError(f"Chunk text hash mismatch at {path}:{line_number}")
    if len(text) != payload["char_count"]:
        raise ValueError(f"Chunk char_count mismatch at {path}:{line_number}")
    return ChunkRecord(
        chunk_id=str(payload["chunk_id"]),
        ordinal=int(payload["ordinal"]),
        text=text,
        text_sha256=str(payload["text_sha256"]),
        char_count=int(payload["char_count"]),
        pages=list(payload.get("pages", [])),
        tags=list(payload.get("tags", [])),
        block_types=list(payload.get("block_types", [])),
        metadata=dict(payload.get("metadata", {})),
    )


def build_dry_run_payload(
    config: Any,
    chunks_path: Path,
    chunks_selection: str,
    gate_path: Path,
    gate_selection: str,
    gate_approved: bool,
    embeddings_path: Path,
    metadata_path: Path,
    log_path: Path,
    chunks: list[ChunkRecord],
) -> dict[str, Any]:
    return {
        "step": "05_embed_chunks",
        "dry_run": True,
        "run": config.describe_run(),
        "chunks_jsonl": str(chunks_path),
        "chunks_selection": chunks_selection,
        "chunk_count": len(chunks),
        "gate": str(gate_path),
        "gate_selection": gate_selection,
        "approved_for_embedding": gate_approved,
        "embedding_model_name": config.EMBEDDING_MODEL_NAME,
        "embedding_model_version": config.EMBEDDING_MODEL_VERSION,
        "embedding_batch_size": config.EMBEDDING_BATCH_SIZE,
        "output_embeddings_npy": str(embeddings_path),
        "output_metadata_jsonl": str(metadata_path),
        "output_log": str(log_path),
        "will_load_model": gate_approved,
        "will_write_embeddings": False,
    }


def build_embedding_surfaces(
    chunks: list[ChunkRecord],
    embedding_text_policy: str,
) -> list[EmbeddingSurface]:
    surfaces: list[EmbeddingSurface] = []
    for chunk in chunks:
        text = embedding_text_for_policy(chunk, embedding_text_policy)
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        surfaces.append(EmbeddingSurface(text=text, text_sha256=text_hash, char_count=len(text)))
    return surfaces


def embedding_text_for_policy(chunk: ChunkRecord, embedding_text_policy: str) -> str:
    if embedding_text_policy == "original_with_source_boundary":
        return chunk.text

    # The full-corpus combiner prepends a visible source-boundary block for
    # provenance. That is useful in retrieved prompt text, but it may teach the
    # embedding model to over-attend to repeated source wrappers. Variant
    # policies strip only that wrapper while leaving the stored chunk text
    # untouched so Chroma documents remain auditable and display-safe.
    body = strip_source_boundary(chunk.text).strip()
    if embedding_text_policy == "body_only_v1":
        return body

    if embedding_text_policy == "title_once_body_v1":
        # This variant keeps one lightweight semantic anchor per chunk without
        # repeating the full provenance block. It lets us test whether a single
        # source/section title helps recall without recreating boundary-driven
        # source dominance.
        metadata = chunk.metadata
        pieces = [
            str(metadata.get("guideline_title") or "").strip(),
            str(metadata.get("section") or "").strip(),
            body,
        ]
        return "\n\n".join(part for part in pieces if part)

    raise ValueError(f"Unsupported embedding_text_policy: {embedding_text_policy}")


def strip_source_boundary(text: str) -> str:
    end_marker = "[/LACP_SOURCE_BOUNDARY]"
    if text.startswith("[LACP_SOURCE_BOUNDARY]") and end_marker in text:
        return text.split(end_marker, 1)[1].lstrip()
    return text


def embed_chunks(config: Any, surfaces: list[EmbeddingSurface]) -> tuple[Any, dict[str, Any]]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers and numpy are required for embedding generation."
        ) from exc

    model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    texts = [surface.text for surface in surfaces]
    vectors = model.encode(
        texts,
        batch_size=config.EMBEDDING_BATCH_SIZE,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    vectors = np.asarray(vectors, dtype="float32")
    model_info = {
        "model_name": config.EMBEDDING_MODEL_NAME,
        "model_version": config.EMBEDDING_MODEL_VERSION,
        "sentence_transformers_class": model.__class__.__name__,
        "vector_dimension": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        "normalized": True,
    }
    return vectors, model_info


def write_embeddings(path: Path, vectors: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)


def write_embedding_metadata(
    config: Any,
    chunks_path: Path,
    metadata_path: Path,
    chunks: list[ChunkRecord],
    surfaces: list[EmbeddingSurface],
    vectors: Any,
    embedding_text_policy: str,
) -> None:
    if len(chunks) != len(surfaces):
        raise ValueError("Chunk and embedding surface counts differ.")
    chunks_hash = config.sha256_file(chunks_path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8") as handle:
        for index, (chunk, surface) in enumerate(zip(chunks, surfaces, strict=True)):
            payload = {
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "chunk_text_sha256": chunk.text_sha256,
                "chunk_chars": chunk.char_count,
                "embedding_text_policy": embedding_text_policy,
                "embedding_text_sha256": surface.text_sha256,
                "embedding_text_chars": surface.char_count,
                "embedding_index": index,
                "embedding_model_name": config.EMBEDDING_MODEL_NAME,
                "embedding_model_version": config.EMBEDDING_MODEL_VERSION,
                "vector_dimension": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
                "source_chunks_jsonl": str(chunks_path),
                "source_chunks_sha256": chunks_hash,
                "pages": chunk.pages,
                "tags": chunk.tags,
                "block_types": chunk.block_types,
                "metadata": {
                    **chunk.metadata,
                    "chunk_id": chunk.chunk_id,
                    "chunk_sha256": chunk.text_sha256,
                    "chunk_chars": chunk.char_count,
                    "corpus_version": chunk.metadata.get(
                        "corpus_version", config.CORPUS_VERSION
                    ),
                    "collection_name": config.COLLECTION_NAME,
                    "embedding_model": config.EMBEDDING_MODEL_NAME,
                    "embedding_model_version": config.EMBEDDING_MODEL_VERSION,
                    "embedding_text_policy": embedding_text_policy,
                    "embedding_text_sha256": surface.text_sha256,
                    "embedding_text_chars": surface.char_count,
                },
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_log_payload(
    config: Any,
    chunks_path: Path,
    chunks_selection: str,
    gate_path: Path,
    gate_selection: str,
    embeddings_path: Path,
    metadata_path: Path,
    chunks: list[ChunkRecord],
    surfaces: list[EmbeddingSurface],
    vectors: Any,
    model_info: dict[str, Any],
    embedding_text_policy: str,
) -> dict[str, Any]:
    return {
        "step": "05_embed_chunks",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": config.describe_run(),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "semantic_gate": {
            "path": str(gate_path),
            "selection": gate_selection,
            "sha256": config.sha256_file(gate_path),
        },
        "chunks_jsonl": {
            "path": str(chunks_path),
            "selection": chunks_selection,
            "sha256": config.sha256_file(chunks_path),
            "size_bytes": chunks_path.stat().st_size,
        },
        "embeddings_npy": {
            "path": str(embeddings_path),
            "sha256": config.sha256_file(embeddings_path),
            "size_bytes": embeddings_path.stat().st_size,
        },
        "metadata_jsonl": {
            "path": str(metadata_path),
            "sha256": config.sha256_file(metadata_path),
            "size_bytes": metadata_path.stat().st_size,
        },
        "chunk_count": len(chunks),
        "embedding_text_policy": embedding_text_policy,
        "embedding_surface": {
            "min_chars": min((surface.char_count for surface in surfaces), default=0),
            "max_chars": max((surface.char_count for surface in surfaces), default=0),
            "avg_chars": round(
                sum(surface.char_count for surface in surfaces) / len(surfaces), 4
            )
            if surfaces
            else 0.0,
        },
        "vector_shape": list(vectors.shape),
        "model": model_info,
        "determinism_notes": [
            "Chunk order is JSONL ordinal order and must be sorted before embedding.",
            "Chunk text hashes are validated before embedding.",
            "Embedding determinism depends on model weights, sentence-transformers version, backend, and device.",
            "created_at_utc changes per run and affects only the log artifact.",
        ],
    }


def run_self_test(config: Any) -> None:
    text = "지원대상 예시"
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = {
        "chunk_id": "sample:00001",
        "ordinal": 1,
        "text": text,
        "text_sha256": text_hash,
        "char_count": len(text),
        "pages": [1],
        "tags": ["eligibility"],
        "block_types": ["paragraph"],
    }
    chunk = chunk_from_payload(payload, Path("<self-test>"), 1)
    expected = {
        "chunk_id": "sample:00001",
        "ordinal": 1,
        "text_sha256": text_hash,
        "model_name": config.EMBEDDING_MODEL_NAME,
        "model_version": config.EMBEDDING_MODEL_VERSION,
    }
    print(
        json.dumps(
            {
                "self_test": "passed",
                "chunk": {
                    "chunk_id": chunk.chunk_id,
                    "ordinal": chunk.ordinal,
                    "char_count": chunk.char_count,
                    "tags": chunk.tags,
                },
                "expected": expected,
                "model_loaded": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
