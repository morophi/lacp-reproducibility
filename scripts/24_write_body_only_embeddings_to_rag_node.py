"""Copy body-only full-corpus embeddings to the RAG node and ingest Chroma.

This script is the controlled bridge from the iMac build artifacts to the RAG
node.  It intentionally does not require the harness API: harness is only needed
for E2E experiment execution, while this script writes the retrieval substrate
directly on the RAG node through SSH/SCP.

Safety model:
    * The target collection must be a versioned `lacp_docs_v*` name.
    * The legacy `lacp_docs` collection is never accepted.
    * A dry run is the default; actual RAG-node Chroma write requires
      `--confirm-rag-write`.
    * Input file hashes and row counts are recorded before transfer.
    * The RAG-side ingest uses `scripts/08_ingest_chromadb.py --ingest-scope
      rag_node` so collection metadata is distinguishable from local validation
      collections.

The current formal candidate uses body-only embeddings with a separate hybrid
retrieval policy.  Chroma stores the body-only vectors and normal display-safe
chunk documents; hybrid lexical/RRF behavior remains a retrieval runtime policy
and is not implemented by this write script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ID = "20260525T_full_guideline_v1"
CORPUS_VERSION = "v1_full_guideline_table_safe"
EMBEDDING_TEXT_POLICY = "body_only_v1"
COLLECTION_NAME = "lacp_docs_v1_full_guideline_table_safe_body_only_v1"
PACKAGE_PREFIX = "rag_full_guidelines_2026"


@dataclass(frozen=True)
class ArtifactSet:
    chunks: Path
    embeddings: Path
    metadata: Path
    ingest_script: Path
    ingest_config: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("/Users/morophi/lacp_rag/full_corpus") / RUN_ID,
    )
    parser.add_argument("--collection-name", default=COLLECTION_NAME)
    parser.add_argument("--corpus-version", default=CORPUS_VERSION)
    parser.add_argument("--embedding-text-policy", default=EMBEDDING_TEXT_POLICY)
    parser.add_argument("--rag-host", default="rag")
    parser.add_argument("--rag-python", default="/home/morophi/RAG/bin/python")
    parser.add_argument("--rag-chroma-path", default="/home/morophi/chromadb_data")
    parser.add_argument(
        "--rag-stage-root",
        default=f"/home/morophi/lacp_rag_ingest/full_corpus/{RUN_ID}",
    )
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument(
        "--reset-new-collection",
        action="store_true",
        help="Delete and recreate only the target versioned collection on the RAG node.",
    )
    parser.add_argument(
        "--confirm-rag-write",
        action="store_true",
        help="Actually run the RAG-node Chroma ingest. Without this flag, only audit and dry-run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/Users/morophi/lacp_rag/full_corpus")
        / RUN_ID
        / "logs"
        / "rag_node_body_only_write_manifest.json",
    )
    return parser.parse_args()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash potentially large embeddings without loading the whole file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl_head(path: Path, limit: int = 3) -> list[dict[str, Any]]:
    """Read a few rows for schema sanity without materializing the corpus."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def count_jsonl(path: Path) -> int:
    """Count non-empty JSONL rows to verify chunk/metadata alignment."""
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def validate_collection_name(collection_name: str) -> None:
    """Preserve the legacy active collection guard during RAG-node writes."""
    if collection_name == "lacp_docs" or not collection_name.startswith("lacp_docs_v"):
        raise ValueError(
            "Refusing unsafe collection name. Use a versioned lacp_docs_v* collection, never lacp_docs."
        )


def resolve_artifacts(run_root: Path) -> ArtifactSet:
    chunks = run_root / "chunks" / f"{PACKAGE_PREFIX}_{RUN_ID}_chunks.jsonl"
    embeddings = (
        run_root
        / "embeddings"
        / f"{PACKAGE_PREFIX}_{RUN_ID}_{EMBEDDING_TEXT_POLICY}_embeddings.npy"
    )
    metadata = (
        run_root
        / "embeddings"
        / f"{PACKAGE_PREFIX}_{RUN_ID}_{EMBEDDING_TEXT_POLICY}_embedding_metadata.jsonl"
    )
    scripts_dir = Path(__file__).resolve().parent
    return ArtifactSet(
        chunks=chunks,
        embeddings=embeddings,
        metadata=metadata,
        ingest_script=scripts_dir / "08_ingest_chromadb.py",
        ingest_config=scripts_dir / "ingest_config.py",
    )


def validate_artifacts(artifacts: ArtifactSet) -> dict[str, Any]:
    """Check local artifact presence, counts, policy markers, and hashes."""
    for path in (
        artifacts.chunks,
        artifacts.embeddings,
        artifacts.metadata,
        artifacts.ingest_script,
        artifacts.ingest_config,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    chunk_count = count_jsonl(artifacts.chunks)
    metadata_count = count_jsonl(artifacts.metadata)
    if chunk_count != metadata_count:
        raise ValueError(
            f"Chunk/metadata row count mismatch: chunks={chunk_count}, metadata={metadata_count}"
        )

    head = load_jsonl_head(artifacts.metadata)
    policies = {row.get("embedding_text_policy") for row in head}
    if policies != {EMBEDDING_TEXT_POLICY}:
        raise ValueError(f"Unexpected embedding_text_policy in metadata head: {policies}")

    return {
        "chunk_count": chunk_count,
        "metadata_count": metadata_count,
        "chunks_sha256": sha256_file(artifacts.chunks),
        "embeddings_sha256": sha256_file(artifacts.embeddings),
        "metadata_sha256": sha256_file(artifacts.metadata),
        "ingest_script_sha256": sha256_file(artifacts.ingest_script),
        "ingest_config_sha256": sha256_file(artifacts.ingest_config),
        "metadata_head_chunk_ids": [row.get("chunk_id") for row in head],
    }


def run_command(args: list[str], timeout_sec: int = 300) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without shell interpolation and keep audit output."""
    return subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout_sec)


def require_success(proc: subprocess.CompletedProcess[str], label: str) -> None:
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed with returncode={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def ssh(rag_host: str, remote_command: str, timeout_sec: int = 300) -> subprocess.CompletedProcess[str]:
    return run_command(["ssh", rag_host, remote_command], timeout_sec=timeout_sec)


def scp_to_rag(local_path: Path, rag_host: str, remote_path: str, timeout_sec: int = 600) -> None:
    proc = run_command(["scp", str(local_path), f"{rag_host}:{remote_path}"], timeout_sec=timeout_sec)
    require_success(proc, f"scp {local_path.name}")


def quote_join(parts: list[str]) -> str:
    """Build a remote shell command with explicit argument quoting."""
    return " ".join(shlex.quote(part) for part in parts)


def transfer_and_ingest(args: argparse.Namespace, artifacts: ArtifactSet) -> dict[str, Any]:
    """Copy artifacts to the RAG node and optionally execute the Chroma ingest."""
    stage = args.rag_stage_root.rstrip("/")
    remote_paths = {
        "chunks": f"{stage}/chunks/{artifacts.chunks.name}",
        "embeddings": f"{stage}/embeddings/{artifacts.embeddings.name}",
        "metadata": f"{stage}/embeddings/{artifacts.metadata.name}",
        "ingest_script": f"{stage}/scripts/08_ingest_chromadb.py",
        "ingest_config": f"{stage}/scripts/ingest_config.py",
    }

    mkdir_cmd = quote_join(["mkdir", "-p", f"{stage}/chunks", f"{stage}/embeddings", f"{stage}/scripts", f"{stage}/logs"])
    require_success(ssh(args.rag_host, mkdir_cmd), "rag stage mkdir")

    scp_to_rag(artifacts.chunks, args.rag_host, remote_paths["chunks"])
    scp_to_rag(artifacts.embeddings, args.rag_host, remote_paths["embeddings"], timeout_sec=1200)
    scp_to_rag(artifacts.metadata, args.rag_host, remote_paths["metadata"])
    scp_to_rag(artifacts.ingest_script, args.rag_host, remote_paths["ingest_script"])
    scp_to_rag(artifacts.ingest_config, args.rag_host, remote_paths["ingest_config"])

    py_compile_cmd = quote_join(
        [
            args.rag_python,
            "-m",
            "py_compile",
            remote_paths["ingest_script"],
            remote_paths["ingest_config"],
        ]
    )
    py_compile = ssh(args.rag_host, py_compile_cmd)
    require_success(py_compile, "rag py_compile")

    ingest_base = [
        args.rag_python,
        remote_paths["ingest_script"],
        "--chunks",
        remote_paths["chunks"],
        "--embeddings",
        remote_paths["embeddings"],
        "--metadata",
        remote_paths["metadata"],
        "--collection-name",
        args.collection_name,
        "--chroma-path",
        args.rag_chroma_path,
        "--corpus-version",
        args.corpus_version,
        "--embedding-text-policy",
        args.embedding_text_policy,
        "--ingest-scope",
        "rag_node",
        "--batch-size",
        str(args.batch_size),
    ]
    if args.reset_new_collection:
        ingest_base.append("--reset-new-collection")

    dry_run_cmd = quote_join([*ingest_base, "--dry-run"])
    dry_run = ssh(args.rag_host, dry_run_cmd)
    require_success(dry_run, "rag ingest dry-run")

    write_result: dict[str, Any] | None = None
    if args.confirm_rag_write:
        write = ssh(args.rag_host, quote_join(ingest_base), timeout_sec=3600)
        require_success(write, "rag ingest write")
        try:
            write_result = json.loads(write.stdout)
        except json.JSONDecodeError:
            write_result = {"raw_stdout": write.stdout}

    return {
        "remote_stage_root": stage,
        "remote_paths": remote_paths,
        "rag_py_compile_stdout": py_compile.stdout.strip(),
        "rag_ingest_dry_run": json.loads(dry_run.stdout),
        "rag_ingest_write_executed": bool(args.confirm_rag_write),
        "rag_ingest_write_result": write_result,
    }


def main() -> int:
    args = parse_args()
    validate_collection_name(args.collection_name)
    artifacts = resolve_artifacts(args.run_root)
    local_audit = validate_artifacts(artifacts)

    report: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "body_only_v1 embedding write to RAG node",
        "run_id": RUN_ID,
        "corpus_version": args.corpus_version,
        "collection_name": args.collection_name,
        "embedding_text_policy": args.embedding_text_policy,
        "rag_host": args.rag_host,
        "rag_chroma_path": args.rag_chroma_path,
        "confirm_rag_write": args.confirm_rag_write,
        "reset_new_collection": args.reset_new_collection,
        "local_artifacts": {key: str(value) for key, value in artifacts.__dict__.items()},
        "local_audit": local_audit,
        "notes": [
            "Harness API is not required for this RAG-node write path.",
            "Legacy lacp_docs collection is protected by collection-name validation.",
            "Hybrid RRF is a runtime retrieval policy; this script writes the body-only vector substrate.",
        ],
    }

    report["remote"] = transfer_and_ingest(args, artifacts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "write_executed": args.confirm_rag_write}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
