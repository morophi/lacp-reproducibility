"""
Step 02: Canonical Markdown generation.

Purpose:
    Convert extracted PDF text into canonical markdown before chunking.

Policy basis:
    Every RAG document must become canonical markdown before embedding.
    Eligibility, exception, conditional, benefit, and procedure boundaries must
    be tagged early enough for later semantic verification and chunking.

This script reads page-preserving output from 01_pdf_extract.py and writes a
canonical markdown artifact plus a normalization JSON log. It does not chunk or
embed content.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")
PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
END_PAGE_RE = re.compile(r"<!--\s*/page:\s*(\d+)\s*-->")
COMMENT_RE = re.compile(r"<!--.*?-->")
NUMBERED_RE = re.compile(r"^\s*(?:\d+|[가-힣]|[A-Za-z])(?:[.)]|[．、])\s+")
BULLET_RE = re.compile(r"^\s*(?:[-*•·⚫]|[○◦▪▫■□▶▷])\s*")
SECTION_NUMBER_RE = re.compile(r"^\s*(?:제\s*\d+\s*[장절관항]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[. ]|\d+(?:\.\d+)*[.)]?)\s+")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")


@dataclass
class LineRecord:
    page: int | None
    raw: str
    text: str
    kind: str
    tags: list[str] = field(default_factory=list)
    markers: dict[str, list[str]] = field(default_factory=dict)


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
        description="Normalize extracted text into canonical markdown."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Extraction text path. Defaults to this run's config path, then latest extraction.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Canonical markdown output path. Defaults to ingest_config.py path.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Normalization JSON log output path. Defaults to ingest_config.py path.",
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
    input_path, input_selection = resolve_input_path(config, args.input)
    output_path = args.output or config.CANONICAL_MD
    log_path = args.log or config.CANONICALIZE_LOG

    if args.dry_run:
        payload = build_dry_run_payload(
            config, input_path, input_selection, output_path, log_path
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    config.ensure_output_dirs()
    extracted_text = input_path.read_text(encoding="utf-8")
    records = canonicalize_lines(config, extracted_text)
    markdown = render_canonical_markdown(config, input_path, records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    log_payload = build_log_payload(
        config, input_path, input_selection, output_path, records
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(log_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"canonical_md={output_path}")
    print(f"canonicalize_log={log_path}")
    print(f"line_count={log_payload['line_count']}")
    print(f"tagged_line_count={log_payload['tagged_line_count']}")
    print(f"table_like_line_count={log_payload['kind_counts'].get('table_like', 0)}")
    return 0


def resolve_input_path(config: Any, explicit_input: Path | None) -> tuple[Path, str]:
    if explicit_input is not None:
        if not explicit_input.exists():
            raise FileNotFoundError(f"Extraction input not found: {explicit_input}")
        return explicit_input, "explicit"

    if config.PDF_EXTRACT_TEXT.exists():
        return config.PDF_EXTRACT_TEXT, "run_id"

    latest = config.latest_artifact(config.DIRS.extracted, "extracted", "txt")
    if latest is None:
        raise FileNotFoundError(
            "No extracted text found. Run 01_pdf_extract.py first or pass --input."
        )
    return latest, "latest_fallback"


def build_dry_run_payload(
    config: Any,
    input_path: Path,
    input_selection: str,
    output_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    return {
        "step": "02_canonicalize_md",
        "dry_run": True,
        "run": config.describe_run(),
        "input_text": str(input_path),
        "input_selection": input_selection,
        "input_text_exists": input_path.exists(),
        "output_canonical_md": str(output_path),
        "output_log": str(log_path),
        "will_chunk": False,
        "will_embed": False,
    }


def canonicalize_lines(config: Any, extracted_text: str) -> list[LineRecord]:
    records: list[LineRecord] = []
    current_page: int | None = None

    for raw_line in extracted_text.splitlines():
        page_match = PAGE_RE.match(raw_line.strip())
        if page_match:
            current_page = int(page_match.group(1))
            records.append(
                LineRecord(
                    page=current_page,
                    raw=raw_line,
                    text=f"<!-- page: {current_page} -->",
                    kind="page_marker",
                )
            )
            continue

        end_page_match = END_PAGE_RE.match(raw_line.strip())
        if end_page_match:
            records.append(
                LineRecord(
                    page=current_page,
                    raw=raw_line,
                    text=f"<!-- /page: {end_page_match.group(1)} -->",
                    kind="page_marker",
                )
            )
            current_page = None
            continue

        text = normalize_text_line(raw_line)
        if not text:
            append_blank(records, current_page, raw_line)
            continue
        if COMMENT_RE.fullmatch(text):
            continue

        kind = classify_line(config, text)
        markers = find_marker_hits(config, text)
        tags = sorted(markers)
        records.append(
            LineRecord(
                page=current_page,
                raw=raw_line,
                text=render_line_text(text, kind),
                kind=kind,
                tags=tags,
                markers=markers,
            )
        )

    return collapse_blank_lines(records)


def normalize_text_line(raw_line: str) -> str:
    text = raw_line.replace("\u00a0", " ").replace("\ufeff", "")
    text = text.strip()
    text = MULTISPACE_RE.sub(" ", text)
    return text


def append_blank(records: list[LineRecord], page: int | None, raw_line: str) -> None:
    if records and records[-1].kind == "blank":
        return
    records.append(LineRecord(page=page, raw=raw_line, text="", kind="blank"))


def collapse_blank_lines(records: list[LineRecord]) -> list[LineRecord]:
    collapsed: list[LineRecord] = []
    for record in records:
        if record.kind == "blank" and (not collapsed or collapsed[-1].kind == "blank"):
            continue
        collapsed.append(record)
    while collapsed and collapsed[-1].kind == "blank":
        collapsed.pop()
    return collapsed


def classify_line(config: Any, text: str) -> str:
    if is_table_like_line(text):
        return "table_like"
    if BULLET_RE.match(text):
        return "bullet_line"
    if NUMBERED_RE.match(text):
        return "numbered_line"
    if looks_like_heading(config, text):
        return "heading"
    return "paragraph"


def is_table_like_line(text: str) -> bool:
    if "|" in text and text.count("|") >= 2:
        return True
    if "\t" in text:
        return True
    spaced_columns = re.split(r"\s{2,}", text)
    if len([part for part in spaced_columns if part.strip()]) >= 3:
        return True
    return False


def looks_like_heading(config: Any, text: str) -> bool:
    if len(text) > 80:
        return False
    if SECTION_NUMBER_RE.match(text):
        return True
    return any(hint in text for hint in config.SECTION_HEADER_HINTS)


def find_marker_hits(config: Any, text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for category, markers in config.CANONICAL_MARKER_SETS.items():
        matched = [marker for marker in markers if marker in text]
        if matched:
            hits[category] = matched
    return hits


def render_line_text(text: str, kind: str) -> str:
    if kind == "heading":
        return f"## {text.lstrip('#').strip()}"
    if kind == "bullet_line":
        return "- " + BULLET_RE.sub("", text, count=1).strip()
    if kind == "numbered_line":
        return normalize_numbered_line(text)
    if kind == "table_like":
        return normalize_table_like_line(text)
    return text


def normalize_numbered_line(text: str) -> str:
    stripped = text.strip()
    match = NUMBERED_RE.match(stripped)
    if not match:
        return stripped
    prefix = match.group(0).strip()
    body = stripped[match.end() :].strip()
    return f"{prefix} {body}".strip()


def normalize_table_like_line(text: str) -> str:
    if "|" in text and text.count("|") >= 2:
        cells = [cell.strip() for cell in text.strip("|").split("|")]
    elif "\t" in text:
        cells = [cell.strip() for cell in text.split("\t")]
    else:
        cells = [cell.strip() for cell in re.split(r"\s{2,}", text)]
    cells = [cell for cell in cells if cell]
    if len(cells) < 2:
        return text
    return "| " + " | ".join(cells) + " |"


def render_canonical_markdown(
    config: Any, input_path: Path, records: list[LineRecord]
) -> str:
    lines = [
        "---",
        f"source_pdf: {config.TARGET_PDF_NAME}",
        f"extracted_text: {input_path}",
        f"canonicalization_step: 02_canonicalize_md",
        "policy: no_chunking_no_embedding",
        "---",
        "",
    ]

    previous_tags: tuple[str, ...] = ()
    for record in records:
        if record.kind == "blank":
            lines.append("")
            previous_tags = ()
            continue

        tags = tuple(record.tags)
        if tags and tags != previous_tags:
            marker_summary = "; ".join(
                f"{category}={','.join(markers)}"
                for category, markers in sorted(record.markers.items())
            )
            lines.append(
                f"<!-- semantic_tags: {','.join(tags)}; page: {record.page}; markers: {marker_summary} -->"
            )

        lines.append(record.text)
        previous_tags = tags

    return "\n".join(lines).rstrip() + "\n"


def build_log_payload(
    config: Any,
    input_path: Path,
    input_selection: str,
    output_path: Path,
    records: list[LineRecord],
) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    marker_hits: dict[str, dict[str, int]] = {}

    for record in records:
        kind_counts[record.kind] = kind_counts.get(record.kind, 0) + 1
        for tag in record.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for category, markers in record.markers.items():
            category_hits = marker_hits.setdefault(category, {})
            for marker in markers:
                category_hits[marker] = category_hits.get(marker, 0) + 1

    return {
        "step": "02_canonicalize_md",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": config.describe_run(),
        "policy": {
            "direct_pdf_chunking": False,
            "direct_pdf_embedding": False,
            "next_required_step": "03_semantic_verify_report",
            "semantic_marker_categories": sorted(config.CANONICAL_MARKER_SETS),
        },
        "input_text": {
            "path": str(input_path),
            "selection": input_selection,
            "sha256": config.sha256_file(input_path),
            "size_bytes": input_path.stat().st_size,
        },
        "output_canonical_md": {
            "path": str(output_path),
            "sha256": config.sha256_file(output_path),
            "size_bytes": output_path.stat().st_size,
        },
        "line_count": len(records),
        "tagged_line_count": sum(1 for record in records if record.tags),
        "kind_counts": dict(sorted(kind_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "marker_hits": {
            category: dict(sorted(markers.items()))
            for category, markers in sorted(marker_hits.items())
        },
        "determinism_notes": [
            "Canonical output depends on explicit input text bytes and marker policy in ingest_config.py.",
            "When --input is omitted, latest_fallback can vary as new extraction files are added.",
            "created_at_utc changes per run and affects only the log artifact.",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
