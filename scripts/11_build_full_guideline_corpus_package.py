"""
Build the full-guideline LACP RAG corpus package without ingesting it.

This script is intentionally a package builder, not an active ChromaDB loader.
It creates a new full-guideline corpus from every source document under
`raw/`, preserves the old basic-living corpus as legacy/test provenance, and
emits a tarball that can later be copied to the RAG node and ingested with the
existing `08_ingest_chromadb.py` script.

Design notes for reproducibility:
    - The previous basic-living-only corpus is not deleted. Its archive
      metadata is recorded so the old smoke/top-k diagnosis trail survives.
    - Every chunk receives both metadata and an in-text source boundary block.
      The metadata is best for database analysis; the short in-text boundary is
      a deliberate fallback so retrieved prompt text still carries source
      traceability even outside Chroma metadata views.
    - HWPX is extracted from its zipped XML payload. HWP 5.x is extracted from
      OLE BodyText streams using the documented paragraph-text record tag. This
      avoids requiring external conversion tools on the iMac.
    - Existing table-aware chunking and embedding scripts are reused instead of
      reimplementing those policies here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


ROOT = Path("/Users/morophi/lacp_rag")
RAW_DIR = ROOT / "raw"
SCRIPTS_DIR = ROOT / "scripts"
PYTHON_BIN = Path(os.environ.get("LACP_RAG_VENV", "/Users/morophi/rag_venv")) / "bin" / "python"

CORPUS_VERSION = "v1_full_guideline_table_safe"
COLLECTION_NAME = "lacp_docs_v1_full_guideline_table_safe"
PACKAGE_PREFIX = "rag_full_guidelines_2026"

# HWP paragraph text records use tag id 67. We only consume this record type so
# control records, binary shapes, and layout metadata cannot leak into chunks as
# noisy pseudo-text.
HWP_TAG_PARA_TEXT = 67


@dataclass(frozen=True)
class SourceDoc:
    index: int
    path: Path
    guideline_id: str
    title: str
    source_format: str
    sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build full-guideline chunks, embeddings, manifests, and RAG-node package."
    )
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_full_guideline_v1"),
        help="Stable run id for all generated full-corpus artifacts.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id
    build_root = ROOT / "full_corpus" / run_id
    dirs = build_dirs(build_root)

    sources = discover_sources()
    plan = {
        "run_id": run_id,
        "corpus_version": CORPUS_VERSION,
        "collection_name": COLLECTION_NAME,
        "source_count": len(sources),
        "sources": [source_summary(src) for src in sources],
        "build_root": str(build_root),
        "will_ingest_to_rag_node": False,
    }
    print(json.dumps({"stage": "plan", **plan}, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    ensure_dirs(dirs.values())
    write_json(dirs["manifest"] / "source_inventory.json", plan)
    write_legacy_archive_manifest(dirs["legacy_archive"], run_id)

    per_source_chunk_paths: list[Path] = []
    for source in sources:
        canonical_path = dirs["canonical"] / f"{source.guideline_id}_canonical.md"
        gate_path = dirs["manifest"] / f"{source.guideline_id}_semantic_gate.json"
        chunk_path = dirs["chunks_by_source"] / f"{source.guideline_id}_chunks.jsonl"
        chunk_log = dirs["logs"] / f"{source.guideline_id}_chunking.json"

        canonical_text = extract_source_to_canonical_markdown(source)
        canonical_path.write_text(canonical_text, encoding="utf-8")
        write_approved_gate(gate_path, source, run_id)

        run_subprocess(
            [
                str(PYTHON_BIN),
                str(SCRIPTS_DIR / "04_chunk_table_aware.py"),
                "--input",
                str(canonical_path),
                "--gate",
                str(gate_path),
                "--output",
                str(chunk_path),
                "--log",
                str(chunk_log),
            ],
            cwd=ROOT,
        )
        per_source_chunk_paths.append(chunk_path)

    full_chunks = dirs["chunks"] / f"{PACKAGE_PREFIX}_{run_id}_chunks.jsonl"
    full_gate = dirs["manifest"] / f"{PACKAGE_PREFIX}_{run_id}_semantic_gate.json"
    combine_chunks(sources, per_source_chunk_paths, full_chunks)
    write_full_gate(full_gate, run_id)

    full_embeddings = dirs["embeddings"] / f"{PACKAGE_PREFIX}_{run_id}_embeddings.npy"
    full_embedding_meta = dirs["embeddings"] / f"{PACKAGE_PREFIX}_{run_id}_embedding_metadata.jsonl"
    full_embedding_log = dirs["logs"] / f"{PACKAGE_PREFIX}_{run_id}_embedding.json"
    run_subprocess(
        [
            str(PYTHON_BIN),
            str(SCRIPTS_DIR / "05_embed_chunks.py"),
            "--chunks",
            str(full_chunks),
            "--gate",
            str(full_gate),
            "--embeddings",
            str(full_embeddings),
            "--metadata",
            str(full_embedding_meta),
            "--log",
            str(full_embedding_log),
        ],
        cwd=ROOT,
    )

    manifest_path = write_full_manifest(
        dirs=dirs,
        run_id=run_id,
        sources=sources,
        full_chunks=full_chunks,
        full_embeddings=full_embeddings,
        full_embedding_meta=full_embedding_meta,
    )
    tar_path = build_package(
        dirs=dirs,
        run_id=run_id,
        full_chunks=full_chunks,
        full_embeddings=full_embeddings,
        full_embedding_meta=full_embedding_meta,
        manifest_path=manifest_path,
    )
    result = {
        "stage": "complete",
        "run_id": run_id,
        "corpus_version": CORPUS_VERSION,
        "collection_name": COLLECTION_NAME,
        "source_count": len(sources),
        "full_chunks": str(full_chunks),
        "full_embeddings": str(full_embeddings),
        "package": str(tar_path),
        "rag_node_ingest_executed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_dirs(build_root: Path) -> dict[str, Path]:
    return {
        "root": build_root,
        "canonical": build_root / "canonical_md",
        "chunks_by_source": build_root / "chunks_by_source",
        "chunks": build_root / "chunks",
        "embeddings": build_root / "embeddings",
        "logs": build_root / "logs",
        "manifest": build_root / "manifest",
        "legacy_archive": build_root / "legacy_archive",
        "package": build_root / "package",
    }


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def discover_sources() -> list[SourceDoc]:
    if not RAW_DIR.exists():
        raise FileNotFoundError(RAW_DIR)
    raw_files = sorted(
        path
        for path in RAW_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".hwp", ".hwpx"}
    )
    if not raw_files:
        raise RuntimeError(f"No source documents found under {RAW_DIR}")
    sources: list[SourceDoc] = []
    for index, path in enumerate(raw_files, start=1):
        title = normalize_title(path.stem)
        sources.append(
            SourceDoc(
                index=index,
                path=path,
                guideline_id=f"g{index:02d}_{ascii_slug(title)}",
                title=title,
                source_format=path.suffix.lower().lstrip("."),
                sha256=sha256(path),
            )
        )
    return sources


def normalize_title(value: str) -> str:
    title = unicodedata.normalize("NFC", value)
    title = title.replace("+", " ").replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def ascii_slug(value: str) -> str:
    # Korean titles do not transliterate safely without an additional dependency.
    # A digest suffix keeps ids deterministic and short while avoiding lossy
    # romanization that would be hard to audit later.
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"src_{digest}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_summary(source: SourceDoc) -> dict[str, Any]:
    return {
        "index": source.index,
        "guideline_id": source.guideline_id,
        "title": source.title,
        "source_file": source.path.name,
        "source_format": source.source_format,
        "sha256": source.sha256,
    }


def extract_source_to_canonical_markdown(source: SourceDoc) -> str:
    suffix = source.path.suffix.lower()
    if suffix == ".pdf":
        body = extract_pdf_markdown(source.path)
    elif suffix == ".hwpx":
        body = extract_hwpx_markdown(source.path)
    elif suffix == ".hwp":
        body = extract_hwp_markdown(source.path)
    else:
        raise ValueError(f"Unsupported source format: {source.path}")

    # The front matter gives downstream chunking a stable source boundary. The
    # comments are intentionally simple markdown/HTML so existing chunk parsing
    # ignores them for page logic while humans can still inspect provenance.
    return "\n".join(
        [
            "---",
            f"source_file: {json.dumps(source.path.name, ensure_ascii=False)}",
            f"source_sha256: {source.sha256}",
            f"guideline_id: {source.guideline_id}",
            f"guideline_title: {json.dumps(source.title, ensure_ascii=False)}",
            f"source_format: {source.source_format}",
            f"corpus_version: {CORPUS_VERSION}",
            "---",
            "",
            f"# {source.title}",
            "",
            body.strip(),
            "",
        ]
    )


def extract_pdf_markdown(path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction.") from exc

    sections: list[str] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = normalize_text(page.get_text("text"))
            sections.append(f"<!-- page: {index} -->\n{text}\n<!-- /page: {index} -->")
    return "\n\n".join(sections)


def extract_hwpx_markdown(path: Path) -> str:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().startswith("contents/section") and name.lower().endswith(".xml")
        )
        for name in names:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError:
                continue
            # HWPX section XML stores actual document flow mainly under hp:p
            # paragraph elements. A naive `root.itertext()` collapses the entire
            # section into a few huge blocks, which then violates chunk-size
            # policy. Iterate paragraph nodes and collect text-bearing hp:t
            # descendants so each form paragraph or table-cell paragraph can
            # become a manageable markdown paragraph before table-aware chunking.
            for paragraph in root.iter():
                if local_name(paragraph.tag) != "p":
                    continue
                pieces: list[str] = []
                for node in paragraph.iter():
                    if local_name(node.tag) == "t" and node.text:
                        pieces.append(node.text)
                text = normalize_text(" ".join(pieces))
                if text:
                    paragraphs.append(text)
    if not paragraphs:
        raise RuntimeError(f"No extractable text found in HWPX: {path}")
    return "\n\n".join(paragraphs)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def extract_hwp_markdown(path: Path) -> str:
    try:
        import olefile
    except ImportError as exc:
        raise RuntimeError("olefile is required for HWP extraction.") from exc

    paragraphs: list[str] = []
    with olefile.OleFileIO(str(path)) as ole:
        compressed = hwp_is_compressed(ole)
        streams = sorted(
            "/".join(stream)
            for stream in ole.listdir()
            if len(stream) == 2 and stream[0] == "BodyText" and stream[1].startswith("Section")
        )
        for stream in streams:
            data = ole.openstream(stream).read()
            if compressed:
                data = zlib.decompress(data, -15)
            for text in iter_hwp_text_records(data):
                cleaned = normalize_text(text)
                if cleaned:
                    paragraphs.append(cleaned)
    if not paragraphs:
        raise RuntimeError(f"No extractable text found in HWP: {path}")
    return "\n\n".join(paragraphs)


def hwp_is_compressed(ole: Any) -> bool:
    try:
        header = ole.openstream("FileHeader").read()
    except Exception:
        return False
    if len(header) < 40:
        return False
    flags = int.from_bytes(header[36:40], "little")
    return bool(flags & 1)


def iter_hwp_text_records(data: bytes) -> Iterable[str]:
    offset = 0
    size_data = len(data)
    while offset + 4 <= size_data:
        header = int.from_bytes(data[offset : offset + 4], "little")
        offset += 4
        tag_id = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if offset + 4 > size_data:
                break
            size = int.from_bytes(data[offset : offset + 4], "little")
            offset += 4
        payload = data[offset : offset + size]
        offset += size
        if tag_id == HWP_TAG_PARA_TEXT and payload:
            yield payload.decode("utf-16le", errors="ignore")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # HWP paragraph text can include private control characters and nulls. Keep
    # whitespace, Hangul, numbers, punctuation, and printable Unicode while
    # collapsing layout-only control noise.
    text = text.replace("\x00", "")
    text = re.sub(r"[\u0001-\u0008\u000b\u000c\u000e-\u001f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write_approved_gate(path: Path, source: SourceDoc, run_id: str) -> None:
    payload = {
        "approved_for_chunking": True,
        "approval_scope": "full_guideline_package_build",
        "approval_note": (
            "Generated by the full-corpus builder after explicit operator instruction. "
            "This approval permits package construction only; retrieval coherence and "
            "TR preflight must be rerun before causal measurement."
        ),
        "run_id": run_id,
        "guideline_id": source.guideline_id,
        "source_file": source.path.name,
        "source_sha256": source.sha256,
    }
    write_json(path, payload)


def write_full_gate(path: Path, run_id: str) -> None:
    write_json(
        path,
        {
            "approved_for_chunking": True,
            "approval_scope": "combined_full_guideline_embedding",
            "approval_note": "Combined chunks are approved for embedding/package build only.",
            "run_id": run_id,
            "corpus_version": CORPUS_VERSION,
        },
    )


def run_subprocess(command: list[str], cwd: Path) -> None:
    print(json.dumps({"stage": "run", "command": command}, ensure_ascii=False))
    subprocess.run(command, cwd=str(cwd), check=True)


def combine_chunks(sources: list[SourceDoc], paths: list[Path], output_path: Path) -> None:
    source_by_id = {source.guideline_id: source for source in sources}
    total = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        for source, path in zip(sources, paths, strict=True):
            local_index = 0
            for row in read_jsonl(path):
                local_index += 1
                total += 1
                metadata = dict(row.get("metadata") or {})
                source_boundary = {
                    "corpus_version": CORPUS_VERSION,
                    "guideline_id": source.guideline_id,
                    "guideline_title": source.title,
                    "source_file": source.path.name,
                    "source_format": source.source_format,
                    "source_sha256": source.sha256,
                    "source_index": source.index,
                    "source_local_chunk_index": local_index,
                }
                metadata.update(source_boundary)
                text = str(row.get("text") or "")
                row["chunk_id"] = f"{CORPUS_VERSION}__{source.guideline_id}__c{local_index:05d}"
                row["text"] = source_boundary_text(source_boundary) + "\n\n" + text
                # `05_embed_chunks.py` deliberately validates text integrity
                # before embedding. Because this combiner prepends the source
                # boundary to make provenance visible even outside metadata, the
                # inherited per-source text hash and character count are no
                # longer valid. Recompute both here so the combined JSONL remains
                # self-verifying and deterministic.
                row["text_sha256"] = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
                row["char_count"] = len(row["text"])
                # The embedder also requires monotonically sorted ordinals. Use a
                # global ordinal across all source files while retaining the
                # per-source ordinal in metadata for source-level audits.
                row["ordinal"] = total
                row["corpus_version"] = CORPUS_VERSION
                # The per-source chunker writes a metadata.chunk_id before the
                # final full-corpus combiner assigns globally unique IDs. Chroma
                # retrieval reports surface metadata fields prominently, so keep
                # those metadata identifiers synchronized with the final top-level
                # row values to avoid stale per-source IDs during local validation
                # and downstream audit reports. `chunk_chars` mirrors the final
                # combined text size, including the source boundary marker.
                metadata["chunk_id"] = row["chunk_id"]
                metadata["top_level_chunk_id"] = row["chunk_id"]
                metadata["chunk_chars"] = row["char_count"]
                metadata["corpus_version"] = CORPUS_VERSION
                row["metadata"] = metadata
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    if total == 0:
        raise RuntimeError("Combined chunk file is empty.")


def source_boundary_text(boundary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "[LACP_SOURCE_BOUNDARY]",
            f"corpus_version: {boundary['corpus_version']}",
            f"guideline_id: {boundary['guideline_id']}",
            f"guideline_title: {boundary['guideline_title']}",
            f"source_file: {boundary['source_file']}",
            f"source_format: {boundary['source_format']}",
            "[/LACP_SOURCE_BOUNDARY]",
        ]
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return rows


def write_legacy_archive_manifest(path: Path, run_id: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    legacy_manifest = {
        "archive_reason": "test-only basic livelihood corpus replaced by full guideline corpus",
        "archived_at_utc": datetime.now(timezone.utc).isoformat(),
        "new_run_id": run_id,
        "legacy_status": "archive_only_not_active",
        "old_collection_candidates": [
            "lacp_docs",
            "lacp_docs_v2_table_safe",
            "lacp_docs_v2_table_safe_topk3",
            "lacp_docs_v2_table_safe_topk5",
        ],
        "used_for": [
            "early retrieval smoke",
            "top-k context-window diagnosis",
            "harness path validation",
            "parser and generation-quality readiness checks",
        ],
        "not_used_for": ["CR", "CR2", "Run B", "CF Runs", "causal effect estimation"],
        "active_retrieval_policy": "Do not point Harness or RAG retrieval at legacy collections for causal runs.",
    }
    write_json(path / "legacy_basic_living_archive_manifest.json", legacy_manifest)


def write_full_manifest(
    dirs: dict[str, Path],
    run_id: str,
    sources: list[SourceDoc],
    full_chunks: Path,
    full_embeddings: Path,
    full_embedding_meta: Path,
) -> Path:
    chunk_rows = read_jsonl(full_chunks)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "corpus_version": CORPUS_VERSION,
        "collection_name": COLLECTION_NAME,
        "source_count": len(sources),
        "chunk_count": len(chunk_rows),
        "embedding_metadata_count": count_jsonl(full_embedding_meta),
        "source_inventory": [source_summary(source) for source in sources],
        "artifacts": {
            "chunks_jsonl": str(full_chunks),
            "chunks_sha256": sha256(full_chunks),
            "embeddings_npy": str(full_embeddings),
            "embeddings_sha256": sha256(full_embeddings),
            "embedding_metadata_jsonl": str(full_embedding_meta),
            "embedding_metadata_sha256": sha256(full_embedding_meta),
        },
        "legacy_policy": {
            "delete_legacy_basic_living": False,
            "exclude_legacy_from_active_retrieval": True,
            "exclude_legacy_from_causal_runs": True,
        },
        "rag_node_ingest_executed": False,
    }
    path = dirs["manifest"] / f"{PACKAGE_PREFIX}_{run_id}_manifest.json"
    write_json(path, manifest)
    (dirs["manifest"] / "corpus_version.txt").write_text(CORPUS_VERSION + "\n", encoding="utf-8")
    (dirs["manifest"] / "collection_name.txt").write_text(COLLECTION_NAME + "\n", encoding="utf-8")
    return path


def count_jsonl(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def build_package(
    dirs: dict[str, Path],
    run_id: str,
    full_chunks: Path,
    full_embeddings: Path,
    full_embedding_meta: Path,
    manifest_path: Path,
) -> Path:
    package_dir = dirs["package"] / f"{PACKAGE_PREFIX}_{run_id}_rag_node_package"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    (package_dir / "chunks").mkdir(parents=True)
    (package_dir / "embeddings").mkdir()
    (package_dir / "manifest").mkdir()
    (package_dir / "scripts").mkdir()
    (package_dir / "logs").mkdir()

    shutil.copy2(full_chunks, package_dir / "chunks" / full_chunks.name)
    shutil.copy2(full_embeddings, package_dir / "embeddings" / full_embeddings.name)
    shutil.copy2(full_embedding_meta, package_dir / "embeddings" / full_embedding_meta.name)
    shutil.copy2(manifest_path, package_dir / "manifest" / manifest_path.name)
    shutil.copytree(dirs["legacy_archive"], package_dir / "legacy_archive")

    for script_name in ["08_ingest_chromadb.py", "09_validate_retrieval.py", "10_prompt_size_test.py", "ingest_config.py"]:
        shutil.copy2(SCRIPTS_DIR / script_name, package_dir / "scripts" / script_name)

    deploy_policy = {
        "run_id": run_id,
        "corpus_version": CORPUS_VERSION,
        "collection_name": COLLECTION_NAME,
        "rag_node_ingest_executed": False,
        "chroma_path_on_rag": "/home/morophi/chromadb_data",
        "ingest_command_for_later_manual_use": (
            f"/home/morophi/RAG/bin/python scripts/08_ingest_chromadb.py "
            f"--chunks chunks/{full_chunks.name} "
            f"--embeddings embeddings/{full_embeddings.name} "
            f"--metadata embeddings/{full_embedding_meta.name} "
            f"--collection-name {COLLECTION_NAME} "
            f"--chroma-path /home/morophi/chromadb_data "
            f"--reset-new-collection"
        ),
        "important": "This package build intentionally stops before RAG-node ingest.",
    }
    write_json(package_dir / "deploy_policy.json", deploy_policy)

    checksums = {
        str(path.relative_to(package_dir)): sha256(path)
        for path in sorted(package_dir.rglob("*"))
        if path.is_file()
    }
    write_json(package_dir / "checksums_sha256.json", checksums)

    tar_path = dirs["package"] / f"{PACKAGE_PREFIX}_{run_id}_rag_node_package.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(package_dir, arcname=package_dir.name)
    return tar_path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
