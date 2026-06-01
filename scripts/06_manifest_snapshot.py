"""
Step 06: Reproducibility manifest snapshot.

Change reason:
    The v2 small-chunk rebuild is an experimental intervention surface, not a
    cosmetic refactor. This stage now writes explicit corpus, collection, chunk
    policy, source hash, chunk hash, embedding model, and build summary files.

Purpose:
    Record hashes, counts, versions, gate status, and runtime metadata for
    reproducibility.

Policy basis:
    The ingest run must record canonical markdown hash, chunking policy,
    embedding model version, chunk and embedding counts, semantic verification
    record, pip freeze snapshot, and run metadata.

This script snapshots artifacts. It does not mutate source artifacts, chunk
content, embeddings, or retrieval indexes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import subprocess
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
    parser = argparse.ArgumentParser(
        description="Write reproducibility manifest and pip freeze snapshot."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest JSON output path. Defaults to ingest_config.py MANIFEST_JSON.",
    )
    parser.add_argument(
        "--pip-freeze",
        type=Path,
        default=None,
        help="pip freeze output path. Defaults to ingest_config.py PIP_FREEZE_TXT.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Markdown summary output path. Defaults to ingest_config.py FINAL_RUN_LOG.",
    )
    parser.add_argument(
        "--require-final-artifacts",
        action="store_true",
        help="Fail if approved chunks or embeddings are missing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned manifest targets and current artifact status without writing.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run deterministic count/hash helper tests without reading corpus artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    if args.self_test:
        run_self_test()
        return 0

    manifest_path = args.manifest or config.MANIFEST_JSON
    pip_freeze_path = args.pip_freeze or config.PIP_FREEZE_TXT
    summary_path = args.summary or config.FINAL_RUN_LOG
    artifact_status = collect_artifact_status(config)
    final_ready = is_final_ready(artifact_status)
    missing_final = final_missing_reasons(artifact_status)

    if args.dry_run:
        payload = {
            "step": "06_manifest_snapshot",
            "dry_run": True,
            "run": config.describe_run(),
            "manifest": str(manifest_path),
            "pip_freeze": str(pip_freeze_path),
            "summary": str(summary_path),
            "require_final_artifacts": args.require_final_artifacts,
            "final_ready": final_ready,
            "missing_final_reasons": missing_final,
            "will_write_manifest": False,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if final_ready or not args.require_final_artifacts else 2

    if args.require_final_artifacts and not final_ready:
        print(
            json.dumps(
                {
                    "step": "06_manifest_snapshot",
                    "status": "blocked",
                    "reason": "required final artifacts are missing or gate is unapproved",
                    "missing_final_reasons": missing_final,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    config.ensure_output_dirs()
    pip_freeze_text = capture_pip_freeze()
    pip_freeze_path.parent.mkdir(parents=True, exist_ok=True)
    pip_freeze_path.write_text(pip_freeze_text, encoding="utf-8")

    manifest = build_manifest(
        config=config,
        manifest_path=manifest_path,
        pip_freeze_path=pip_freeze_path,
        summary_path=summary_path,
        artifact_status=artifact_status,
        final_ready=final_ready,
        missing_final=missing_final,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_required_manifest_files(config, manifest)

    summary = render_summary(manifest)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")

    print(f"manifest_json={manifest_path}")
    print(f"manifest_dir={config.DIRS.manifest}")
    print(f"pip_freeze={pip_freeze_path}")
    print(f"final_summary={summary_path}")
    print(f"final_ready={final_ready}")
    print(f"missing_final_reasons={len(missing_final)}")
    return 0


def collect_artifact_status(config: Any) -> dict[str, dict[str, Any]]:
    candidates = {
        "target_pdf": config.TARGET_PDF,
        "extracted_text": config.PDF_EXTRACT_TEXT,
        "pdf_extract_log": config.PDF_EXTRACT_LOG,
        "canonical_md": config.CANONICAL_MD,
        "canonicalize_log": config.CANONICALIZE_LOG,
        "semantic_report": config.SEMANTIC_REPORT,
        "semantic_gate": config.SEMANTIC_GATE,
        "chunks_jsonl": config.CHUNKS_JSONL,
        "chunk_log": config.CHUNK_LOG,
        "embeddings_npy": config.EMBEDDINGS_NPY,
        "embedding_metadata_jsonl": config.EMBEDDINGS_META_JSONL,
        "embedding_log": config.EMBEDDING_LOG,
    }

    status: dict[str, dict[str, Any]] = {}
    for name, path in candidates.items():
        status[name] = describe_artifact(config, path)

    latest_specs = {
        "latest_extracted_text": (config.DIRS.extracted, "extracted", "txt"),
        "latest_canonical_md": (config.DIRS.canonical_md, "canonical", "md"),
        "latest_semantic_report": (config.DIRS.manifest, "semantic_report", "md"),
        "latest_semantic_gate": (config.DIRS.manifest, "semantic_gate", "json"),
        "latest_chunks_jsonl": (config.DIRS.chunks, "chunks", "jsonl"),
        "latest_embedding_metadata_jsonl": (
            config.DIRS.embeddings,
            "embedding_metadata",
            "jsonl",
        ),
    }
    for name, (directory, suffix, extension) in latest_specs.items():
        latest = config.latest_artifact(directory, suffix, extension)
        status[name] = describe_artifact(config, latest) if latest else {"exists": False}

    enrich_counts(status)
    return status


def describe_artifact(config: Any, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False}
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if path.exists():
        payload.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": config.sha256_file(path),
            }
        )
    return payload


def enrich_counts(status: dict[str, dict[str, Any]]) -> None:
    for key in ("chunks_jsonl", "latest_chunks_jsonl"):
        artifact = status.get(key, {})
        if artifact.get("exists"):
            artifact["jsonl_count"] = count_jsonl(Path(artifact["path"]))

    for key in ("embedding_metadata_jsonl", "latest_embedding_metadata_jsonl"):
        artifact = status.get(key, {})
        if artifact.get("exists"):
            artifact["jsonl_count"] = count_jsonl(Path(artifact["path"]))

    gate = status.get("semantic_gate", {})
    if gate.get("exists"):
        payload = read_json(Path(gate["path"]))
        gate["approved_for_chunking"] = payload.get("approved_for_chunking")
        gate["risk_categories"] = payload.get("risk_categories", {})

    latest_gate = status.get("latest_semantic_gate", {})
    if latest_gate.get("exists"):
        payload = read_json(Path(latest_gate["path"]))
        latest_gate["approved_for_chunking"] = payload.get("approved_for_chunking")
        latest_gate["risk_categories"] = payload.get("risk_categories", {})


def count_jsonl(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_invalid_json": True}


def is_final_ready(status: dict[str, dict[str, Any]]) -> bool:
    required_keys = (
        "canonical_md",
        "semantic_report",
        "semantic_gate",
        "chunks_jsonl",
        "embeddings_npy",
        "embedding_metadata_jsonl",
    )
    if not all(status.get(key, {}).get("exists") for key in required_keys):
        return False
    if status["semantic_gate"].get("approved_for_chunking") is not True:
        return False
    if status["chunks_jsonl"].get("jsonl_count", 0) <= 0:
        return False
    if status["embedding_metadata_jsonl"].get("jsonl_count", 0) != status["chunks_jsonl"].get(
        "jsonl_count", -1
    ):
        return False
    return True


def final_missing_reasons(status: dict[str, dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for key in (
        "canonical_md",
        "semantic_report",
        "semantic_gate",
        "chunks_jsonl",
        "embeddings_npy",
        "embedding_metadata_jsonl",
    ):
        if not status.get(key, {}).get("exists"):
            reasons.append(f"missing:{key}")
    if status.get("semantic_gate", {}).get("exists") and status["semantic_gate"].get(
        "approved_for_chunking"
    ) is not True:
        reasons.append("semantic_gate:not_approved")
    chunk_count = status.get("chunks_jsonl", {}).get("jsonl_count")
    metadata_count = status.get("embedding_metadata_jsonl", {}).get("jsonl_count")
    if chunk_count is not None and chunk_count <= 0:
        reasons.append("chunks_jsonl:empty")
    if chunk_count is not None and metadata_count is not None and chunk_count != metadata_count:
        reasons.append("embedding_metadata_jsonl:count_mismatch")
    return reasons


def capture_pip_freeze() -> str:
    command = [sys.executable, "-m", "pip", "freeze"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def build_manifest(
    config: Any,
    manifest_path: Path,
    pip_freeze_path: Path,
    summary_path: Path,
    artifact_status: dict[str, dict[str, Any]],
    final_ready: bool,
    missing_final: list[str],
) -> dict[str, Any]:
    return {
        "step": "06_manifest_snapshot",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": config.describe_run(),
        "output_manifest": str(manifest_path),
        "output_pip_freeze": str(pip_freeze_path),
        "output_summary": str(summary_path),
        "final_ready": final_ready,
        "missing_final_reasons": missing_final,
        "artifacts": artifact_status,
        "runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "experiment_variable_impact": {
            "LMS": "tracked via embedding model name/version when embeddings exist",
            "MA": "tracked via model/runtime/vector metadata when embeddings exist",
            "CDS": "tracked via canonical/chunk hashes and semantic gate",
            "SRR": "tracked via chunk counts, semantic tags, and gate report",
            "SCI": "tracked via table-aware chunk policy and verification report",
        },
        "rag_impact": {
            "corpus": "hash/count snapshot only",
            "chunks": "hash/count snapshot only",
            "metadata": "manifest, pip freeze, and summary are created",
            "retrieval": "no retrieval index is created or mutated",
        },
        "versioned_collection": {
            "corpus_version": config.CORPUS_VERSION,
            "collection_name": config.COLLECTION_NAME,
            "legacy_collection_name": config.LEGACY_COLLECTION_NAME,
            "legacy_preserved": config.COLLECTION_NAME != config.LEGACY_COLLECTION_NAME,
        },
        "determinism_notes": [
            "Artifact hashes and JSONL counts are deterministic for fixed files.",
            "created_at_utc changes per manifest run.",
            "pip freeze reflects the active Python environment at execution time.",
            "latest_* artifact fields can change as new timestamped artifacts are added.",
        ],
    }


def write_required_manifest_files(config: Any, manifest: dict[str, Any]) -> None:
    config.DIRS.manifest.mkdir(parents=True, exist_ok=True)
    build_summary = build_summary_payload(config, manifest)
    files = {
        "corpus_version.txt": f"{config.CORPUS_VERSION}\n",
        "chunk_policy_v2.json": json.dumps(chunk_policy_payload(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "source_files_sha256.txt": render_source_hashes(manifest),
        "chunks_sha256.txt": render_chunk_hashes(manifest),
        "embedding_model.txt": f"{config.EMBEDDING_MODEL_NAME}\n",
        "embedding_model_version.txt": f"{config.EMBEDDING_MODEL_VERSION}\n",
        "collection_name.txt": f"{config.COLLECTION_NAME}\n",
        "build_timestamp.txt": f"{manifest['created_at_utc']}\n",
        "build_summary.json": json.dumps(build_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    for filename, content in files.items():
        (config.DIRS.manifest / filename).write_text(content, encoding="utf-8")


def chunk_policy_payload(config: Any) -> dict[str, Any]:
    return {
        "corpus_version": config.CORPUS_VERSION,
        "collection_name": config.COLLECTION_NAME,
        "chunk_size_target": config.CHUNK_SIZE_TARGET,
        "chunk_overlap": config.CHUNK_OVERLAP_CHARS,
        "min_chunk_size": config.MIN_CHUNK_CHARS,
        "max_chunk_chars": config.MAX_CHUNK_CHARS,
        "max_table_part_chars": config.MAX_TABLE_PART_CHARS,
        "table_policy": {
            "split": "row-wise",
            "repeat_per_part": [
                "table_id",
                "parent_table_label",
                "table_part_label",
                "table_title",
                "columns",
                "source",
                "section",
                "year",
                "unit",
            ],
            "forbidden": "random character split inside tables",
        },
    }


def render_source_hashes(manifest: dict[str, Any]) -> str:
    lines = []
    for key in ("target_pdf", "canonical_md", "chunks_jsonl"):
        artifact = manifest["artifacts"].get(key, {})
        if artifact.get("exists"):
            lines.append(f"{artifact.get('sha256', '')}  {artifact.get('path', '')}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_chunk_hashes(manifest: dict[str, Any]) -> str:
    chunks = manifest["artifacts"].get("chunks_jsonl", {})
    if not chunks.get("exists"):
        return ""
    path = Path(chunks["path"])
    lines = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            lines.append(f"{row.get('chunk_sha256') or row.get('text_sha256')}  {row.get('chunk_id')}")
    return "\n".join(lines) + ("\n" if lines else "")


def build_summary_payload(config: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    chunks_artifact = manifest["artifacts"].get("chunks_jsonl", {})
    counts = {"text": 0, "table": 0, "mixed": 0}
    lengths: list[int] = []
    if chunks_artifact.get("exists"):
        with Path(chunks_artifact["path"]).open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                metadata = row.get("metadata", {})
                block_type = metadata.get("block_type", row.get("block_type", "text"))
                counts[block_type] = counts.get(block_type, 0) + 1
                lengths.append(int(metadata.get("chunk_chars", row.get("chunk_chars", 0))))
    total_chunks = sum(counts.values())
    return {
        "corpus_version": config.CORPUS_VERSION,
        "collection_name": config.COLLECTION_NAME,
        "total_chunks": total_chunks,
        "text_chunks": counts.get("text", 0),
        "table_chunks": counts.get("table", 0),
        "mixed_chunks": counts.get("mixed", 0),
        "avg_chunk_chars": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        "max_chunk_chars": max(lengths) if lengths else 0,
        "min_chunk_chars": min(lengths) if lengths else 0,
        "chunk_size_target": config.CHUNK_SIZE_TARGET,
        "chunk_overlap": config.CHUNK_OVERLAP_CHARS,
        "table_policy": "row-wise table-safe split with repeated header metadata",
        "embedding_model": config.EMBEDDING_MODEL_NAME,
        "created_at": manifest["created_at_utc"],
    }


def render_summary(manifest: dict[str, Any]) -> str:
    lines = [
        "# Final Run Summary",
        "",
        f"- run_id: `{manifest['run']['run_id']}`",
        f"- final_ready: `{manifest['final_ready']}`",
        f"- missing_final_reasons: `{', '.join(manifest['missing_final_reasons']) or 'none'}`",
        "",
        "## Artifact Status",
        "",
    ]
    for name, artifact in sorted(manifest["artifacts"].items()):
        exists = artifact.get("exists")
        path = artifact.get("path", "")
        extra = ""
        if "jsonl_count" in artifact:
            extra = f", jsonl_count={artifact['jsonl_count']}"
        if "approved_for_chunking" in artifact:
            extra += f", approved_for_chunking={artifact['approved_for_chunking']}"
        lines.append(f"- {name}: exists={exists}{extra} `{path}`")

    lines.extend(
        [
            "",
            "## Determinism Notes",
            "",
        ]
    )
    for note in manifest["determinism_notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def run_self_test() -> None:
    sample_path = Path("<sample>")
    fake_status = {
        "canonical_md": {"exists": True},
        "semantic_report": {"exists": True},
        "semantic_gate": {"exists": True, "approved_for_chunking": True},
        "chunks_jsonl": {"exists": True, "jsonl_count": 2},
        "embeddings_npy": {"exists": True},
        "embedding_metadata_jsonl": {"exists": True, "jsonl_count": 2},
    }
    if not is_final_ready(fake_status):
        raise AssertionError("expected fake complete status to be final_ready")
    fake_status["embedding_metadata_jsonl"]["jsonl_count"] = 1
    reasons = final_missing_reasons(fake_status)
    if "embedding_metadata_jsonl:count_mismatch" not in reasons:
        raise AssertionError("expected count mismatch reason")
    print(
        json.dumps(
            {
                "self_test": "passed",
                "sample_path": str(sample_path),
                "expected": {
                    "complete_status_final_ready": True,
                    "count_mismatch_detected": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
