"""
Step 01: PDF text extraction.

Purpose:
    Extract text from the target PDF into an intermediate text artifact.

Policy basis:
    PDF direct chunking is forbidden.
    The pipeline must go PDF -> text extraction -> markdown normalization.

This script writes page-preserving plain text under extracted/ and a JSON log
under logs/. It does not chunk, canonicalize, or embed content.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")
PAGE_SEPARATOR = "\n\n\f\n\n"


@dataclass(frozen=True)
class PageExtraction:
    page_number: int
    char_count: int
    word_count: int
    is_empty: bool
    text: str


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
        description="Extract page-preserving text from the exam target PDF."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional extraction text output path. Defaults to ingest_config.py path.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional JSON log output path. Defaults to ingest_config.py path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print planned outputs without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    pdf_path = config.require_target_pdf()
    output_path = args.output or config.PDF_EXTRACT_TEXT
    log_path = args.log or config.PDF_EXTRACT_LOG

    if args.dry_run:
        print(json.dumps(build_dry_run_payload(config, pdf_path, output_path, log_path), ensure_ascii=False, indent=2))
        return 0

    config.ensure_output_dirs()
    pages, parser_info = extract_pages(pdf_path)
    write_extracted_text(pdf_path, output_path, pages)
    log_payload = build_log_payload(config, pdf_path, output_path, pages, parser_info)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(log_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"extracted_text={output_path}")
    print(f"extract_log={log_path}")
    print(f"page_count={log_payload['page_count']}")
    print(f"empty_pages={len(log_payload['empty_pages'])}")
    return 0


def build_dry_run_payload(
    config: Any, pdf_path: Path, output_path: Path, log_path: Path
) -> dict[str, Any]:
    return {
        "step": "01_pdf_extract",
        "dry_run": True,
        "run": config.describe_run(),
        "input_pdf": str(pdf_path),
        "input_pdf_exists": pdf_path.exists(),
        "output_text": str(output_path),
        "output_log": str(log_path),
        "will_chunk": False,
        "will_embed": False,
    }


def extract_pages(pdf_path: Path) -> tuple[list[PageExtraction], dict[str, str]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for deterministic page text extraction in this step."
        ) from exc

    parser_info = {
        "parser": "PyMuPDF",
        "pymupdf_version": getattr(fitz, "version", ("unknown",))[0],
    }

    pages: list[PageExtraction] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            text = normalize_page_text(page.get_text("text"))
            pages.append(
                PageExtraction(
                    page_number=index,
                    char_count=len(text),
                    word_count=len(text.split()),
                    is_empty=(text.strip() == ""),
                    text=text,
                )
            )
    return pages, parser_info


def normalize_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def write_extracted_text(
    pdf_path: Path, output_path: Path, pages: list[PageExtraction]
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        f"<!-- source_pdf: {pdf_path.name} -->",
        "<!-- extraction_step: 01_pdf_extract -->",
        "<!-- policy: no_chunking_no_embedding -->",
    ]

    for page in pages:
        sections.append(
            "\n".join(
                (
                    f"<!-- page: {page.page_number} -->",
                    page.text,
                    f"<!-- /page: {page.page_number} -->",
                )
            )
        )

    output_path.write_text(PAGE_SEPARATOR.join(sections) + "\n", encoding="utf-8")


def build_log_payload(
    config: Any,
    pdf_path: Path,
    output_path: Path,
    pages: list[PageExtraction],
    parser_info: dict[str, str],
) -> dict[str, Any]:
    empty_pages = [page.page_number for page in pages if page.is_empty]
    warnings = []
    if empty_pages:
        warnings.append(
            {
                "code": "empty_pages",
                "message": "One or more pages produced no extractable text.",
                "pages": empty_pages,
            }
        )

    return {
        "step": "01_pdf_extract",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": config.describe_run(),
        "policy": {
            "direct_pdf_chunking": False,
            "direct_pdf_embedding": False,
            "next_required_step": "02_canonicalize_md",
        },
        "parser": parser_info,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "input_pdf": {
            "path": str(pdf_path),
            "name": pdf_path.name,
            "sha256": config.sha256_file(pdf_path),
            "size_bytes": pdf_path.stat().st_size,
        },
        "output_text": {
            "path": str(output_path),
            "sha256": config.sha256_file(output_path),
            "size_bytes": output_path.stat().st_size,
        },
        "page_count": len(pages),
        "total_chars": sum(page.char_count for page in pages),
        "empty_pages": empty_pages,
        "pages": [
            {
                "page_number": page.page_number,
                "char_count": page.char_count,
                "word_count": page.word_count,
                "is_empty": page.is_empty,
            }
            for page in pages
        ],
        "warnings": warnings,
    }


if __name__ == "__main__":
    raise SystemExit(main())
