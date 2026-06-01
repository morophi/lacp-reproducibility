#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build the fixed CDS reference artifact from stored Chroma embeddings.

This is an offline corpus-freeze artifact step. It reads the RAG node's frozen
Chroma collection embeddings and writes only the reference vector, hash, and
manifest that Harness consumes read-only during runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import chromadb
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chroma-path", default="/home/morophi/chromadb_data")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=512)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "reference_embedding.npy"
    hash_path = args.output_dir / "reference_embedding.sha256"
    manifest_path = args.output_dir / "reference_embedding_manifest.json"

    client = chromadb.PersistentClient(path=args.chroma_path)
    collection = client.get_collection(args.collection)
    count = collection.count()
    print(json.dumps({"event": "collection_loaded", "collection": args.collection, "count": count}))

    sum_vec: np.ndarray | None = None
    seen = 0
    source_embedding_hash = hashlib.sha256()
    sample_metadatas = []
    for offset in range(0, count, args.batch_size):
        batch = collection.get(include=["embeddings", "metadatas"], limit=args.batch_size, offset=offset)
        embeddings = batch.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            continue
        arr = np.asarray(embeddings, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D embeddings batch, got shape={arr.shape}")
        source_embedding_hash.update(np.ascontiguousarray(arr).tobytes())
        batch_sum = arr.sum(axis=0, dtype=np.float64)
        sum_vec = batch_sum if sum_vec is None else sum_vec + batch_sum
        seen += arr.shape[0]
        if len(sample_metadatas) < 3:
            sample_metadatas.extend((batch.get("metadatas") or [])[: 3 - len(sample_metadatas)])
        if seen % 2048 < args.batch_size:
            print(json.dumps({"event": "progress", "seen": seen, "count": count}))

    if sum_vec is None or seen == 0:
        raise SystemExit("No stored Chroma embeddings were found")

    reference = (sum_vec / float(seen)).astype(np.float32)
    norm = float(np.linalg.norm(reference))
    if norm != 0.0:
        reference = reference / norm
    np.save(out_path, reference)
    output_sha256 = file_sha256(out_path)
    hash_path.write_text(f"{output_sha256}  reference_embedding.npy\n", encoding="utf-8")
    manifest = {
        "artifact_role": "cds_reference_embedding",
        "artifact_policy": "offline RAG/corpus freeze artifact; Harness consumes read-only",
        "generation_method": "mean of stored Chroma embeddings, L2-normalized",
        "collection_name": args.collection,
        "collection_count": count,
        "embedded_vectors": seen,
        "embedding_model": args.embedding_model,
        "source_embedding_stream_sha256": source_embedding_hash.hexdigest(),
        "sample_metadata_hash": stable_hash(sample_metadatas),
        "output": str(out_path),
        "output_sha256": output_sha256,
        "shape": list(reference.shape),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"event": "done", **manifest}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
