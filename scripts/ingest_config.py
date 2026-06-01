"""
Shared configuration for the production RAG ingest pipeline.

Change reason:
    LACP top-k=3 experiments exceeded the Ollama num_ctx=4096 prompt limit with
    the original large chunk corpus. This config now defaults to a versioned,
    table-safe small-chunk corpus while preserving existing collections.

This module defines paths, policy constants, runtime naming, and lightweight
helpers only. It must not perform extraction, canonicalization, chunking, or
embedding work at import time.
"""

from __future__ import annotations

import os
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

VENV_DIR = Path(os.environ.get("LACP_RAG_VENV", "/Users/morophi/rag_venv"))
PYTHON_BIN = VENV_DIR / "bin" / "python"

SOURCE_ENV = os.environ.get("LACP_RAG_SOURCE", "")
SOURCE_LABEL_ENV = os.environ.get("LACP_RAG_SOURCE_LABEL", "")


def _resolve_source_path(value: str) -> Path:
    if not value:
        return PROJECT_ROOT / "raw" / "__unset_source__.pdf"
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if len(path.parts) > 1:
        return PROJECT_ROOT / path
    return PROJECT_ROOT / "raw" / path


def _artifact_slug(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_")


def _source_label(path: Path, explicit: str) -> str:
    explicit_slug = _artifact_slug(explicit)
    if explicit_slug:
        return explicit_slug
    stem_slug = _artifact_slug(path.stem)
    if stem_slug:
        return stem_slug
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    return f"source_{digest}"


TARGET_PDF = _resolve_source_path(SOURCE_ENV)
TARGET_PDF_NAME = TARGET_PDF.name
SOURCE_LABEL = _source_label(TARGET_PDF, SOURCE_LABEL_ENV)
ARTIFACT_PREFIX = f"rag_{SOURCE_LABEL}"


@dataclass(frozen=True)
class OutputDirs:
    raw: Path
    extracted: Path
    canonical_md: Path
    cleaned: Path
    chunks: Path
    embeddings: Path
    manifest: Path
    logs: Path

    def all(self) -> tuple[Path, ...]:
        return (
            self.raw,
            self.extracted,
            self.canonical_md,
            self.cleaned,
            self.chunks,
            self.embeddings,
            self.manifest,
            self.logs,
        )


DIRS = OutputDirs(
    raw=PROJECT_ROOT / "raw",
    extracted=PROJECT_ROOT / "extracted",
    canonical_md=PROJECT_ROOT / "canonical_md",
    cleaned=PROJECT_ROOT / "cleaned",
    chunks=PROJECT_ROOT / "chunks",
    embeddings=PROJECT_ROOT / "embeddings",
    manifest=PROJECT_ROOT / "manifest",
    logs=PROJECT_ROOT / "logs",
)


RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"
RUN_ID = os.environ.get("LACP_RAG_RUN_ID") or datetime.now(timezone.utc).strftime(
    RUN_ID_FORMAT
)


PDF_EXTRACT_TEXT = DIRS.extracted / f"{ARTIFACT_PREFIX}_{RUN_ID}_extracted.txt"
PDF_EXTRACT_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_pdf_extract.json"
CANONICAL_MD = DIRS.canonical_md / f"{ARTIFACT_PREFIX}_{RUN_ID}_canonical.md"
CANONICALIZE_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_canonicalize.json"
SEMANTIC_REPORT = DIRS.manifest / f"{ARTIFACT_PREFIX}_{RUN_ID}_semantic_report.md"
SEMANTIC_GATE = DIRS.manifest / f"{ARTIFACT_PREFIX}_{RUN_ID}_semantic_gate.json"
CHUNKS_JSONL = DIRS.chunks / f"{ARTIFACT_PREFIX}_{RUN_ID}_chunks.jsonl"
CHUNK_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_chunking.json"
EMBEDDINGS_NPY = DIRS.embeddings / f"{ARTIFACT_PREFIX}_{RUN_ID}_embeddings.npy"
EMBEDDINGS_META_JSONL = (
    DIRS.embeddings / f"{ARTIFACT_PREFIX}_{RUN_ID}_embedding_metadata.jsonl"
)
EMBEDDING_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_embedding.json"
MANIFEST_JSON = DIRS.manifest / f"{ARTIFACT_PREFIX}_{RUN_ID}_manifest.json"
PIP_FREEZE_TXT = DIRS.manifest / f"{ARTIFACT_PREFIX}_{RUN_ID}_pip_freeze.txt"
FINAL_RUN_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_final_summary.md"


DBLOG_HOST = os.environ.get("LACP_DBLOG_HOST", "dblog")
DBLOG_REMOTE_ROOT = os.environ.get("LACP_DBLOG_REMOTE_ROOT", "lacp_logs/imac_embedding")
DBLOG_SYNC_LOG = DIRS.logs / f"{ARTIFACT_PREFIX}_{RUN_ID}_dblog_sync.json"


CORPUS_VERSION = os.environ.get("LACP_RAG_CORPUS_VERSION", "v2_table_safe")
COLLECTION_NAME = os.environ.get(
    "LACP_RAG_COLLECTION_NAME", "lacp_docs_v2_table_safe"
)
LEGACY_COLLECTION_NAME = os.environ.get(
    "LACP_RAG_LEGACY_COLLECTION_NAME", "lacp_docs"
)
CHROMADB_PATH = Path(os.environ.get("LACP_CHROMADB_PATH", "/data/chromadb"))


EMBEDDING_MODEL_NAME = os.environ.get(
    "LACP_RAG_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
EMBEDDING_MODEL_VERSION = os.environ.get("LACP_RAG_EMBEDDING_MODEL_VERSION", "locked")
EMBEDDING_BATCH_SIZE = int(os.environ.get("LACP_RAG_EMBEDDING_BATCH_SIZE", "32"))


CHUNK_SIZE_TARGET = int(os.environ.get("LACP_RAG_CHUNK_SIZE_TARGET", "900"))
MAX_CHUNK_CHARS = int(os.environ.get("LACP_RAG_MAX_CHUNK_CHARS", "1000"))
MIN_CHUNK_CHARS = int(os.environ.get("LACP_RAG_MIN_CHUNK_CHARS", "250"))
CHUNK_OVERLAP_CHARS = int(os.environ.get("LACP_RAG_CHUNK_OVERLAP_CHARS", "120"))
MAX_TABLE_PART_CHARS = int(os.environ.get("LACP_RAG_MAX_TABLE_PART_CHARS", "1100"))
MAX_TABLE_CHARS = int(os.environ.get("LACP_RAG_MAX_TABLE_CHARS", "12000"))
PROMPT_SIZE_TARGET_CHARS = int(os.environ.get("LACP_RAG_PROMPT_SIZE_TARGET_CHARS", "3500"))
PROMPT_SIZE_HARD_LIMIT_TOKENS = int(os.environ.get("LACP_RAG_PROMPT_SIZE_HARD_LIMIT_TOKENS", "4096"))

PRESERVE_TABLES = True
PRESERVE_TABLE_HEADERS = True
REQUIRE_SEMANTIC_VERIFICATION = True
ALLOW_CHUNKING_WITHOUT_GATE = False

PROTECTED_BLOCK_LABELS = (
    "table",
    "section_header",
    "eligibility",
    "exception",
    "conditional",
    "benefit",
    "procedure",
    "bullet_list",
    "numbered_list",
)

ELIGIBILITY_MARKERS = (
    "지원대상",
    "신청대상",
    "급여대상",
    "서비스대상",
    "대상자",
    "적용대상",
    "수급대상",
    "보장대상",
    "보호대상",
    "선정기준",
    "선정 기준",
    "선정요건",
    "선정 요건",
    "자격",
    "수급자격",
    "신청자격",
    "지원요건",
    "지원 요건",
    "급여요건",
    "급여 요건",
    "인정기준",
    "인정 기준",
    "판정기준",
    "판정 기준",
    "수급권자",
    "수급자",
    "지원대상자",
    "차상위계층",
    "기준대상자",
    "법정저소득층",
    "등록장애인",
    "한부모가족",
    "조손가족",
    "해당하는 자",
    "해당하는 사람",
    "해당되는 자",
    "해당되는 사람",
    "다음에 해당",
    "아래에 해당",
    "요건을 충족",
    "기준을 충족",
    "인정하는 자",
    "필요하다고 인정하는 자",
)

EXCEPTION_MARKERS = (
    "제외",
    "제외대상",
    "제외 대상",
    "예외",
    "불가",
    "제한",
    "중지",
    "중단",
    "해당하지 아니",
    "해당하지 않",
    "인정하지 아니",
    "인정하지 않",
    "지원하지 아니",
    "지원하지 않",
    "지급하지 아니",
    "지급하지 않",
    "적용하지 아니",
    "적용하지 않",
    "대상 제외",
    "지원 제외",
    "지급 제외",
    "산정 제외",
    "자격 상실",
    "지급 정지",
    "급여 중지",
    "서비스 중지",
    "지원 중단",
    "보장 중지",
    "환수",
    "환수 대상",
    "중복 불가",
    "중복지원 불가",
    "중복 지원 불가",
    "중복 제한",
    "타 서비스로 연계",
    "다른 공적 돌봄 서비스를 받고 있지 않는 경우",
    "요건 미달",
    "미충족",
    "부적합",
    "불인정",
    "초과하는 경우",
    "기준을 초과",
    "선정기준을 초과",
)

CONDITIONAL_MARKERS = (
    "경우",
    "한 경우",
    "하는 경우",
    "해당 시",
    "충족 시",
    "미충족 시",
    "초과 시",
    "이하",
    "미만",
    "이상",
    "초과",
    "다만",
    "단,",
    "조건으로",
    "원칙",
    "예외적으로",
    "필요시",
    "사유 발생 시",
)

BENEFIT_MARKERS = (
    "급여",
    "급여액",
    "지원액",
    "서비스 내용",
    "서비스내용",
    "지급액",
    "지급일",
    "급여 개시일",
    "최초급여",
    "산정방법",
    "지급",
    "지원",
    "제공",
    "바우처",
    "본인부담금",
    "차등 적용",
)

PROCEDURE_MARKERS = (
    "신청",
    "접수",
    "상담",
    "조사",
    "공적자료",
    "조회",
    "실태조사",
    "보장결정",
    "결정",
    "통지",
    "급여지급",
    "변동사항",
    "변동 관리",
    "확인조사",
    "전자결재",
    "지급의뢰",
)

SECTION_HEADER_HINTS = (
    "지원대상",
    "대상",
    "소득",
    "재산",
    "부양의무자",
    "기타자격",
    "서비스욕구",
    "선정기준",
    "급여·서비스 기준",
    "급여･서비스 기준",
    "업무처리 절차",
)

MARKER_PRIORITY = {
    "section_header": 3.0,
    "table_header": 2.5,
    "bullet_line": 1.5,
    "inline_sentence": 1.0,
    "footnote": 0.5,
}

NEGATION_PRIORITY_BOOST = 1.5
CONDITIONAL_PRIORITY_BOOST = 1.2

CANONICAL_MARKER_SETS = {
    "eligibility": ELIGIBILITY_MARKERS,
    "exception": EXCEPTION_MARKERS,
    "conditional": CONDITIONAL_MARKERS,
    "benefit": BENEFIT_MARKERS,
    "procedure": PROCEDURE_MARKERS,
}


def ensure_output_dirs() -> None:
    """Create the shared output directories used by the ingest pipeline."""

    for directory in DIRS.all():
        directory.mkdir(parents=True, exist_ok=True)


def require_target_pdf() -> Path:
    """Return the target PDF path, raising a clear error when it is missing."""

    if not SOURCE_ENV:
        raise ValueError(
            "No source document configured. Set LACP_RAG_SOURCE or run "
            "scripts/run_ingest.py --source raw/<file.pdf>."
        )
    if TARGET_PDF.suffix.lower() != ".pdf":
        raise ValueError(
            f"Only PDF extraction is implemented in this pipeline stage: {TARGET_PDF}"
        )
    if not TARGET_PDF.exists():
        raise FileNotFoundError(f"Target PDF not found: {TARGET_PDF}")
    return TARGET_PDF


def run_artifact(directory: Path, suffix: str, extension: str) -> Path:
    """Build a standard output path for this run."""

    clean_suffix = _slugify(suffix)
    clean_extension = extension.lstrip(".")
    return directory / f"{ARTIFACT_PREFIX}_{RUN_ID}_{clean_suffix}.{clean_extension}"


def latest_artifact(directory: Path, suffix: str, extension: str) -> Path | None:
    """Return the newest matching artifact by filename sort order."""

    clean_suffix = _slugify(suffix)
    clean_extension = extension.lstrip(".")
    pattern = f"{ARTIFACT_PREFIX}_*_{clean_suffix}.{clean_extension}"
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute a SHA-256 hash without loading large artifacts into memory."""

    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_gate_allows_chunking(gate_path: Path = SEMANTIC_GATE) -> bool:
    """
    Return True only when a gate file explicitly approves chunking.

    The gate format is intentionally small JSON and is expected to contain
    {"approved_for_chunking": true} after human review.
    """

    if ALLOW_CHUNKING_WITHOUT_GATE:
        return True
    if not gate_path.exists():
        return False

    import json

    try:
        payload = json.loads(gate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("approved_for_chunking") is True


def describe_run() -> dict[str, object]:
    """Return serializable metadata shared by logs and manifests."""

    return {
        "run_id": RUN_ID,
        "project_root": str(PROJECT_ROOT),
        "scripts_dir": str(SCRIPTS_DIR),
        "target_pdf": str(TARGET_PDF),
            "target_pdf_name": TARGET_PDF_NAME,
            "source_env": SOURCE_ENV,
            "source_label": SOURCE_LABEL,
            "artifact_prefix": ARTIFACT_PREFIX,
        "corpus_version": CORPUS_VERSION,
        "collection_name": COLLECTION_NAME,
        "legacy_collection_name": LEGACY_COLLECTION_NAME,
        "chromadb_path": str(CHROMADB_PATH),
        "embedding_model_name": EMBEDDING_MODEL_NAME,
        "embedding_model_version": EMBEDDING_MODEL_VERSION,
        "chunk_policy": {
            "chunk_size_target": CHUNK_SIZE_TARGET,
            "max_chunk_chars": MAX_CHUNK_CHARS,
            "min_chunk_chars": MIN_CHUNK_CHARS,
            "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
            "max_table_part_chars": MAX_TABLE_PART_CHARS,
            "max_table_chars": MAX_TABLE_CHARS,
            "preserve_tables": PRESERVE_TABLES,
            "preserve_table_headers": PRESERVE_TABLE_HEADERS,
            "protected_block_labels": PROTECTED_BLOCK_LABELS,
        },
        "canonical_marker_policy": {
            "marker_sets": CANONICAL_MARKER_SETS,
            "eligibility_markers": ELIGIBILITY_MARKERS,
            "exception_markers": EXCEPTION_MARKERS,
            "conditional_markers": CONDITIONAL_MARKERS,
            "benefit_markers": BENEFIT_MARKERS,
            "procedure_markers": PROCEDURE_MARKERS,
            "section_header_hints": SECTION_HEADER_HINTS,
            "marker_priority": MARKER_PRIORITY,
            "negation_priority_boost": NEGATION_PRIORITY_BOOST,
            "conditional_priority_boost": CONDITIONAL_PRIORITY_BOOST,
        },
        "semantic_verification": {
            "required": REQUIRE_SEMANTIC_VERIFICATION,
            "gate_path": str(SEMANTIC_GATE),
            "chunking_allowed": semantic_gate_allows_chunking(),
        },
    }


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    return lowered.strip("_") or "artifact"


def validate_policy_constants() -> None:
    """Fail fast when chunking constants are internally inconsistent."""

    if MIN_CHUNK_CHARS <= 0:
        raise ValueError("MIN_CHUNK_CHARS must be positive")
    if MAX_CHUNK_CHARS < MIN_CHUNK_CHARS:
        raise ValueError("MAX_CHUNK_CHARS must be greater than MIN_CHUNK_CHARS")
    if CHUNK_OVERLAP_CHARS < 0:
        raise ValueError("CHUNK_OVERLAP_CHARS must not be negative")
    if CHUNK_OVERLAP_CHARS >= MAX_CHUNK_CHARS:
        raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than MAX_CHUNK_CHARS")
    if CHUNK_SIZE_TARGET <= 0:
        raise ValueError("CHUNK_SIZE_TARGET must be positive")
    if MAX_TABLE_PART_CHARS < MIN_CHUNK_CHARS:
        raise ValueError("MAX_TABLE_PART_CHARS must be at least MIN_CHUNK_CHARS")
    if COLLECTION_NAME == LEGACY_COLLECTION_NAME:
        raise ValueError("COLLECTION_NAME must not equal LEGACY_COLLECTION_NAME")
    if EMBEDDING_BATCH_SIZE <= 0:
        raise ValueError("EMBEDDING_BATCH_SIZE must be positive")


def existing_paths(paths: Iterable[Path]) -> list[Path]:
    """Return the subset of paths that currently exist."""

    return [path for path in paths if path.exists()]


validate_policy_constants()
