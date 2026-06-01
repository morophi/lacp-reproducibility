"""
Step 04: Table-safe small chunking.

Change reason:
    The v1 large chunk corpus made top-k=3 prompts exceed Ollama num_ctx=4096.
    This stage builds a versioned small retrieval unit corpus while preserving
    table semantics. Tables are split only by rows, and each part repeats title,
    columns, source, section, year, unit, and table identifiers.

Policy basis:
    Existing collections are preserved. This script writes chunk JSONL only; it
    does not embed content or mutate ChromaDB.
"""

from __future__ import annotations

import argparse
import hashlib
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
SEMANTIC_TAG_RE = re.compile(r"<!--\s*semantic_tags:\s*(?P<tags>[^;]+);.*?-->")
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+)$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
FRONT_MATTER_RE = re.compile(r"^---\s*$")
TABLE_LABEL_RE = re.compile(r"(?:표|Table)\s*([0-9]+(?:[-.][0-9]+)?)", re.IGNORECASE)
YEAR_RE = re.compile(r"(20[0-9]{2})\s*년?|(?:year\s*[:=]\s*)(20[0-9]{2})", re.IGNORECASE)
UNIT_RE = re.compile(r"(?:단위\s*[:：]\s*([^)\\n]+)|\((?:단위\s*[:：]\s*)?([^)]+)\))")
SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")


@dataclass
class Block:
    block_id: int
    kind: str
    lines: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    tags: set[str] = field(default_factory=set)
    section: str = "document"
    heading_level: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ChunkDraft:
    text: str
    block_type: str
    pages: list[int]
    section: str
    source_file: str
    source_hash: str
    chunk_index: int = 0
    table_meta: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    block_kinds: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_table_text: str = ""
    enhanced_caption: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)


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
        description="Create table-safe small chunks from approved canonical markdown."
    )
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--gate", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    if args.self_test:
        run_self_test(config)
        return 0

    input_path, input_selection = resolve_input_path(config, args.input)
    gate_path, gate_selection = resolve_gate_path(config, args.gate)
    output_path = args.output or config.CHUNKS_JSONL
    log_path = args.log or config.CHUNK_LOG
    gate_payload = read_json(gate_path)
    gate_approved = gate_payload.get("approved_for_chunking") is True

    if args.dry_run:
        payload = {
            "step": "04_chunk_table_aware",
            "dry_run": True,
            "run": config.describe_run(),
            "input_canonical_md": str(input_path),
            "input_selection": input_selection,
            "gate": str(gate_path),
            "gate_selection": gate_selection,
            "approved_for_chunking": gate_approved,
            "output_chunks_jsonl": str(output_path),
            "output_log": str(log_path),
            "will_write_chunks": False,
            "chunk_policy": chunk_policy(config),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if gate_approved else 2

    if not gate_approved:
        print(
            json.dumps(
                {
                    "step": "04_chunk_table_aware",
                    "status": "blocked",
                    "reason": "semantic gate is not approved for chunking",
                    "gate": str(gate_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    config.ensure_output_dirs()
    canonical_md = input_path.read_text(encoding="utf-8")
    source_hash = source_file_hash(config, input_path)
    source_file = source_file_name(config, input_path)
    blocks = parse_blocks(canonical_md)
    chunks, warnings = build_chunks(config, blocks, source_file, source_hash)
    write_chunks(config, input_path, output_path, chunks)
    log_payload = build_log_payload(
        config,
        input_path,
        input_selection,
        gate_path,
        gate_selection,
        output_path,
        blocks,
        chunks,
        warnings,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(log_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"chunks_jsonl={output_path}")
    print(f"chunk_log={log_path}")
    print(f"chunk_count={len(chunks)}")
    print(f"table_chunk_count={sum(1 for chunk in chunks if chunk.block_type == 'table')}")
    print(f"warnings={len(warnings)}")
    return 0


def resolve_input_path(config: Any, explicit_input: Path | None) -> tuple[Path, str]:
    if explicit_input is not None:
        if not explicit_input.exists():
            raise FileNotFoundError(f"Canonical markdown not found: {explicit_input}")
        return explicit_input, "explicit"
    if config.CANONICAL_MD.exists():
        return config.CANONICAL_MD, "run_id"
    latest = config.latest_artifact(config.DIRS.canonical_md, "canonical", "md")
    if latest is None:
        raise FileNotFoundError("No canonical markdown found.")
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
        raise FileNotFoundError("No semantic gate found.")
    return latest, "latest_fallback"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}") from exc


def source_file_name(config: Any, input_path: Path) -> str:
    if getattr(config, "TARGET_PDF_NAME", "") and "__unset_source__" not in config.TARGET_PDF_NAME:
        return config.TARGET_PDF_NAME
    return input_path.name


def source_file_hash(config: Any, input_path: Path) -> str:
    target_pdf = getattr(config, "TARGET_PDF", None)
    if target_pdf is not None and Path(target_pdf).exists():
        return config.sha256_file(Path(target_pdf))
    return config.sha256_file(input_path)


def parse_blocks(markdown: str) -> list[Block]:
    blocks: list[Block] = []
    current_page: int | None = None
    pending_tags: set[str] = set()
    active: Block | None = None
    section_stack: dict[int, str] = {}
    current_section = "document"
    in_front_matter = False

    def flush() -> None:
        nonlocal active
        if active is not None and active.text:
            blocks.append(active)
        active = None

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if FRONT_MATTER_RE.match(stripped):
            in_front_matter = not in_front_matter
            flush()
            continue
        if in_front_matter:
            continue

        page_match = PAGE_RE.match(stripped)
        if page_match:
            flush()
            current_page = int(page_match.group(1))
            continue
        if END_PAGE_RE.match(stripped):
            flush()
            current_page = None
            continue

        tag_match = SEMANTIC_TAG_RE.match(stripped)
        if tag_match:
            pending_tags = {
                tag.strip() for tag in tag_match.group("tags").split(",") if tag.strip()
            }
            continue

        if not stripped or stripped.startswith("<!--"):
            flush()
            continue

        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            heading = heading_match.group("title").strip()
            section_stack = {
                key: value for key, value in section_stack.items() if key < level
            }
            section_stack[level] = heading
            current_section = " > ".join(section_stack[key] for key in sorted(section_stack))
            blocks.append(
                Block(
                    block_id=len(blocks) + 1,
                    kind="heading",
                    lines=[stripped],
                    page_start=current_page,
                    page_end=current_page,
                    tags=set(pending_tags),
                    section=current_section,
                    heading_level=level,
                )
            )
            pending_tags = set()
            continue

        kind = "table" if TABLE_RE.match(stripped) else classify_text_line(stripped)
        if active is None or not can_merge(active.kind, kind):
            flush()
            active = Block(
                block_id=len(blocks) + 1,
                kind=kind,
                page_start=current_page,
                page_end=current_page,
                tags=set(pending_tags),
                section=current_section,
            )
        active.lines.append(stripped)
        active.page_end = current_page
        active.tags.update(pending_tags)
        pending_tags = set()

    flush()
    return coalesce_loose_tables(blocks)


def coalesce_loose_tables(blocks: list[Block]) -> list[Block]:
    """
    Merge PDF-extracted loose table lines into the preceding one-cell table.

    Some Korean policy PDFs extract table titles as a one-cell markdown table
    and the actual header/value lines as plain paragraphs or headings. Leaving
    those as text chunks breaks the requirement that table chunks are standalone.
    """

    merged: list[Block] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if not is_single_cell_table(block):
            merged.append(block)
            index += 1
            continue

        loose_lines: list[str] = []
        pages = set(pages_for_blocks([block]))
        tags = set(block.tags)
        section = block.section
        cursor = index + 1
        while cursor < len(blocks):
            candidate = blocks[cursor]
            if candidate.kind == "table":
                break
            candidate_pages = set(pages_for_blocks([candidate]))
            if pages and candidate_pages and not pages.intersection(candidate_pages):
                break
            candidate_text = candidate.text.strip()
            if not candidate_text:
                break
            candidate_lines = [line.lstrip("#").strip() for line in candidate.lines if line.strip()]
            if candidate_lines and is_loose_table_stop(candidate_lines[0], bool(loose_lines)):
                break
            if not candidate_lines or not all(
                looks_like_loose_table_line(line, bool(loose_lines))
                for line in candidate_lines
            ):
                break
            loose_lines.extend(candidate.lines)
            pages.update(candidate_pages)
            tags.update(candidate.tags)
            cursor += 1

        if loose_lines:
            merged.append(
                Block(
                    block_id=block.block_id,
                    kind="table",
                    lines=block.lines + loose_lines,
                    page_start=min(pages) if pages else block.page_start,
                    page_end=max(pages) if pages else block.page_end,
                    tags=tags,
                    section=section,
                    heading_level=block.heading_level,
                )
            )
            index = cursor
        else:
            merged.append(block)
            index += 1
    return merged


def is_single_cell_table(block: Block) -> bool:
    if block.kind != "table":
        return False
    rows = [parse_table_row(line) for line in block.lines if TABLE_RE.match(line)]
    return bool(rows) and all(len(row) == 1 for row in rows)


def is_loose_table_stop(text: str, has_rows: bool) -> bool:
    stripped = text.strip()
    if stripped.startswith("## ※") or stripped.startswith("※"):
        return True
    if has_rows and stripped.startswith("## ") and not re.search(r"기준|소득|급여|[0-9]", stripped):
        return True
    return False


def looks_like_loose_table_line(text: str, has_rows: bool) -> bool:
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return False
    cleaned = stripped.lstrip("#").strip()
    if cleaned in {"가구규모", "구분"}:
        return True
    if re.match(r"^[1-9][0-9]?인가구$", cleaned):
        return True
    if re.match(r"^[0-9,]+$", cleaned):
        return True
    if "단위" in cleaned and len(cleaned) <= 30:
        return True
    if re.search(r"기준\s*중위소득|기준중위소득|생계급여|의료급여|주거급여|교육급여", cleaned):
        return True
    return not has_rows and len(cleaned) <= 40


def classify_text_line(text: str) -> str:
    if re.match(r"^\s*[-*]\s+", text):
        return "bullet_list"
    if re.match(r"^\s*(?:\d+|[A-Za-z])(?:[.)])\s+", text):
        return "numbered_list"
    return "paragraph"


def can_merge(active_kind: str, next_kind: str) -> bool:
    return active_kind == next_kind and active_kind in {
        "paragraph",
        "bullet_list",
        "numbered_list",
        "table",
    }


def build_chunks(
    config: Any,
    blocks: list[Block],
    source_file: str,
    source_hash: str,
) -> tuple[list[ChunkDraft], list[dict[str, Any]]]:
    chunks: list[ChunkDraft] = []
    warnings: list[dict[str, Any]] = []
    text_buffer: list[Block] = []

    def flush_text(reason: str) -> None:
        nonlocal text_buffer
        if not text_buffer:
            return
        for draft in split_text_blocks(config, text_buffer, source_file, source_hash, reason):
            chunks.append(draft)
        text_buffer = []

    for block in blocks:
        if block.kind == "table":
            flush_text("before_table")
            table_chunks, table_warnings = split_table_block(
                config, block, source_file, source_hash
            )
            chunks.extend(table_chunks)
            warnings.extend(table_warnings)
            continue

        if block.kind == "heading":
            if text_buffer and block.section != text_buffer[-1].section:
                flush_text("new_section")
            text_buffer.append(block)
            continue

        candidate_chars = buffered_text_chars(text_buffer) + (2 if text_buffer else 0) + block.char_count
        if text_buffer and candidate_chars > config.MAX_CHUNK_CHARS:
            flush_text("max_chars")
        text_buffer.append(block)

    flush_text("end")

    for index, chunk in enumerate(chunks, start=1):
        chunk.chunk_index = index
        if chunk.char_count > max(config.MAX_CHUNK_CHARS, config.MAX_TABLE_PART_CHARS):
            chunk.warnings.append("chunk_exceeds_policy_max")
            warnings.append(
                {
                    "code": "chunk_exceeds_policy_max",
                    "chunk_index": index,
                    "chunk_chars": chunk.char_count,
                }
            )
    return chunks, warnings


def buffered_text_chars(blocks: list[Block]) -> int:
    return len("\n\n".join(block.text for block in blocks if block.text))


def split_text_blocks(
    config: Any,
    blocks: list[Block],
    source_file: str,
    source_hash: str,
    reason: str,
) -> list[ChunkDraft]:
    section = most_recent_section(blocks)
    prefix = f"[SECTION]\nsource: {source_file}\nsection: {section}\n\n"
    units: list[str] = []
    for block in blocks:
        text = block.text
        if block.kind == "heading":
            continue
        units.extend(paragraph_units(text))

    if not units:
        headings = [block.text for block in blocks if block.kind == "heading"]
        units = headings or [blocks[-1].text]

    drafts: list[ChunkDraft] = []
    current: list[str] = []
    overlap_tail = ""
    max_body_chars = max(200, config.MAX_CHUNK_CHARS - len(prefix))

    for unit in units:
        candidate = "\n\n".join(part for part in current + [unit] if part).strip()
        if current and len(candidate) > max_body_chars:
            body = "\n\n".join(current).strip()
            drafts.append(
                make_text_draft(prefix, body, blocks, source_file, source_hash, reason)
            )
            overlap_tail = tail_by_chars(body, config.CHUNK_OVERLAP_CHARS)
            current = [overlap_tail, unit] if overlap_tail else [unit]
        else:
            current.append(unit)

    if current:
        body = "\n\n".join(current).strip()
        drafts.append(make_text_draft(prefix, body, blocks, source_file, source_hash, reason))

    return drafts


def paragraph_units(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if len(parts) > 1:
        return parts
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines
    sentences = re.split(r"(?<=[.!?。！？다])\s+", text.strip())
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def tail_by_chars(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text if limit > 0 else ""
    tail = text[-limit:]
    boundary = max(tail.find("\n"), tail.find(". "), tail.find(" "))
    return tail[boundary + 1 :].strip() if boundary >= 0 else tail.strip()


def make_text_draft(
    prefix: str,
    body: str,
    blocks: list[Block],
    source_file: str,
    source_hash: str,
    reason: str,
) -> ChunkDraft:
    text = f"{prefix}{body}".strip()
    block_kinds = sorted({block.kind for block in blocks})
    return ChunkDraft(
        text=text,
        block_type="mixed" if len(set(block_kinds) - {"heading"}) > 1 else "text",
        pages=pages_for_blocks(blocks),
        section=most_recent_section(blocks),
        source_file=source_file,
        source_hash=source_hash,
        tags=sorted({tag for block in blocks for tag in block.tags}),
        block_kinds=block_kinds,
        warnings=[] if reason else [],
    )


def split_table_block(
    config: Any,
    block: Block,
    source_file: str,
    source_hash: str,
) -> tuple[list[ChunkDraft], list[dict[str, Any]]]:
    if any(not TABLE_RE.match(line) for line in block.lines):
        return split_loose_table_block(config, block, source_file, source_hash)

    lines = [line for line in block.lines if TABLE_RE.match(line)]
    rows = [parse_table_row(line) for line in lines]
    rows = [row for row in rows if row]
    if not rows:
        return [], [{"code": "empty_table_block", "block_id": block.block_id}]

    header = rows[0]
    data_rows = [row for row in rows[1:] if not is_separator_row(row)]
    if not data_rows:
        data_rows = rows[1:]

    table_label = infer_table_label(block)
    table_no = stable_table_no(block, table_label)
    table_title = infer_table_title(block, table_label)
    table_id = f"tbl_{table_no:03d}_{slugify(table_title)}"
    year = infer_year(block.text, block.section, source_file)
    unit = infer_unit(block.text)
    columns = " | ".join(header)

    drafts: list[ChunkDraft] = []
    parts: list[list[list[str]]] = []
    current_rows: list[list[str]] = []
    for row in data_rows:
        candidate_rows = current_rows + [row]
        candidate_text = render_table_text(
            source_file=source_file,
            section=block.section,
            table_id=table_id,
            parent_table_label=table_label,
            table_part_label=f"{table_label}-X",
            table_part="X/Y",
            table_title=table_title,
            columns=columns,
            unit=unit,
            year=year,
            header=header,
            rows=candidate_rows,
            enhanced_caption=table_description(table_title, columns),
        )
        if current_rows and len(candidate_text) > config.MAX_TABLE_PART_CHARS:
            parts.append(current_rows)
            current_rows = [row]
        else:
            current_rows = candidate_rows
    if current_rows:
        parts.append(current_rows)
    if not parts:
        parts.append([])

    total = len(parts)
    for idx, part_rows in enumerate(parts, start=1):
        part_label = f"{table_label}-{idx}"
        enhanced_caption = table_description(table_title, columns)
        text = render_table_text(
            source_file=source_file,
            section=block.section,
            table_id=table_id,
            parent_table_label=table_label,
            table_part_label=part_label,
            table_part=f"{idx}/{total}",
            table_title=table_title,
            columns=columns,
            unit=unit,
            year=year,
            header=header,
            rows=part_rows,
            enhanced_caption=enhanced_caption,
        )
        drafts.append(
            ChunkDraft(
                text=text,
                block_type="table",
                pages=pages_for_blocks([block]),
                section=block.section,
                source_file=source_file,
                source_hash=source_hash,
                tags=sorted(block.tags),
                block_kinds=["table"],
                original_table_text=block.text,
                enhanced_caption=enhanced_caption,
                table_meta={
                    "table_id": table_id,
                    "parent_table_label": table_label,
                    "table_part_label": part_label,
                    "table_part_no": idx,
                    "table_part_total": total,
                    "table_title": table_title,
                    "columns": columns,
                    "unit": unit,
                    "year": year,
                    "is_table_part": True,
                    "embedding_surface_enhanced": True,
                    "enhancement_type": "natural_language_table_caption",
                    "source_value_modified": False,
                },
            )
        )

    warnings = []
    for draft in drafts:
        if draft.char_count > config.MAX_TABLE_PART_CHARS:
            warnings.append(
                {
                    "code": "table_part_exceeds_max_chars",
                    "block_id": block.block_id,
                    "table_id": table_id,
                    "chunk_chars": draft.char_count,
                    "max_table_part_chars": config.MAX_TABLE_PART_CHARS,
                }
            )
    return drafts, warnings


def split_loose_table_block(
    config: Any,
    block: Block,
    source_file: str,
    source_hash: str,
) -> tuple[list[ChunkDraft], list[dict[str, Any]]]:
    pipe_rows = [parse_table_row(line) for line in block.lines if TABLE_RE.match(line)]
    title = " ".join(cell for row in pipe_rows for cell in row if cell).strip()
    loose = [line.lstrip("#").strip() for line in block.lines if not TABLE_RE.match(line)]
    columns = infer_loose_columns(loose) or title
    rows = infer_loose_rows(loose, columns)
    table_label = infer_table_label(block)
    table_no = stable_table_no(block, table_label)
    table_title = title or infer_table_title(block, table_label)
    table_id = f"tbl_{table_no:03d}_{slugify(table_title)}"
    unit = infer_unit("\n".join(block.lines))
    year = infer_year(title, block.text, block.section, source_file)
    parts = split_loose_rows_for_size(
        config,
        rows,
        source_file,
        block.section,
        table_id,
        table_label,
        table_title,
        columns,
        unit,
        year,
    )
    total = len(parts) or 1
    drafts: list[ChunkDraft] = []
    for idx, part_rows in enumerate(parts or [rows], start=1):
        part_label = f"{table_label}-{idx}"
        enhanced_caption = table_description(table_title, columns)
        text = render_loose_table_text(
            source_file=source_file,
            section=block.section,
            table_id=table_id,
            parent_table_label=table_label,
            table_part_label=part_label,
            table_part=f"{idx}/{total}",
            table_title=table_title,
            columns=columns,
            unit=unit,
            year=year,
            rows=part_rows,
            enhanced_caption=enhanced_caption,
        )
        drafts.append(
            ChunkDraft(
                text=text,
                block_type="table",
                pages=pages_for_blocks([block]),
                section=block.section,
                source_file=source_file,
                source_hash=source_hash,
                tags=sorted(block.tags),
                block_kinds=["table"],
                original_table_text=block.text,
                enhanced_caption=enhanced_caption,
                table_meta={
                    "table_id": table_id,
                    "parent_table_label": table_label,
                    "table_part_label": part_label,
                    "table_part_no": idx,
                    "table_part_total": total,
                    "table_title": table_title,
                    "columns": columns,
                    "unit": unit,
                    "year": year,
                    "is_table_part": True,
                    "embedding_surface_enhanced": True,
                    "enhancement_type": "natural_language_table_caption",
                    "source_value_modified": False,
                },
            )
        )
    return drafts, []


def infer_loose_columns(lines: list[str]) -> str:
    household_cols = [line for line in lines if re.match(r"^[1-9][0-9]?인가구$", line)]
    if household_cols:
        return "구분 | " + " | ".join(household_cols)
    return " | ".join(lines[:8])


def infer_loose_rows(lines: list[str], columns: str) -> list[str]:
    useful = [
        line for line in lines
        if line and "단위" not in line and line not in {"가구규모", "구분"}
    ]
    household_count = max(0, columns.count("인가구"))
    rows: list[str] = []
    index = 0
    while index < len(useful):
        label = useful[index]
        if re.match(r"^[1-9][0-9]?인가구$", label):
            index += 1
            continue
        values = useful[index + 1 : index + 1 + household_count]
        if household_count and len(values) == household_count and all(re.match(r"^[0-9,]+$", value) for value in values):
            rows.append(f"{label} | " + " | ".join(values))
            index += 1 + household_count
        else:
            rows.append(label)
            index += 1
    return rows


def split_loose_rows_for_size(
    config: Any,
    rows: list[str],
    source_file: str,
    section: str,
    table_id: str,
    table_label: str,
    table_title: str,
    columns: str,
    unit: str,
    year: str,
) -> list[list[str]]:
    parts: list[list[str]] = []
    current: list[str] = []
    for row in rows:
        candidate = current + [row]
        text = render_loose_table_text(
            source_file=source_file,
            section=section,
            table_id=table_id,
            parent_table_label=table_label,
            table_part_label=f"{table_label}-X",
            table_part="X/Y",
            table_title=table_title,
            columns=columns,
            unit=unit,
            year=year,
            rows=candidate,
            enhanced_caption=table_description(table_title, columns),
        )
        if current and len(text) > config.MAX_TABLE_PART_CHARS:
            parts.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def render_loose_table_text(
    *,
    source_file: str,
    section: str,
    table_id: str,
    parent_table_label: str,
    table_part_label: str,
    table_part: str,
    table_title: str,
    columns: str,
    unit: str,
    year: str,
    rows: list[str],
    enhanced_caption: str,
) -> str:
    metadata = [
        "[TABLE_START]",
        f"table_id: {table_id}",
        f"parent_table_label: {parent_table_label}",
        f"table_part_label: {table_part_label}",
        f"table_part: {table_part}",
        f"source: {source_file}",
        f"section: {section}",
        f"table_title: {table_title}",
        f"columns: {columns}",
        f"unit: {unit}",
        f"year: {year}",
        "",
        "[ENHANCED_TABLE_CAPTION]",
        enhanced_caption,
        "",
        "[ORIGINAL_TABLE_TEXT]",
        columns,
    ]
    return "\n".join(metadata + rows + ["", "[TABLE_END]"]).strip()


def table_search_terms(table_title: str, columns: str) -> str:
    terms = [table_title, columns]
    compact = f"{table_title} {columns}"
    if "인가구" in compact or "가구규모" in compact:
        terms.append("가구원수별 가구규모 1인가구 2인가구 3인가구 4인가구 5인가구 6인가구 7인가구")
    if "기준 중위소득" in compact or "기준중위소득" in compact:
        terms.append("기준 중위소득 기준중위소득 중위소득")
    if "선정기준" in compact:
        terms.append("수급자 선정기준 급여별 선정기준")
    return " | ".join(dict.fromkeys(term for term in terms if term))


def table_description(table_title: str, columns: str) -> str:
    compact = f"{table_title} {columns}"
    descriptions = [f"이 표는 {table_title} 정보를 담고 있다."]
    if "인가구" in compact or "가구규모" in compact:
        descriptions.append("가구원수별, 가구규모별 값을 1인가구부터 7인가구까지 비교할 때 사용하는 표이다.")
    if "기준 중위소득" in compact or "기준중위소득" in compact:
        descriptions.append("기준 중위소득과 가구원수별 중위소득 금액을 확인할 때 사용하는 표이다.")
    if "선정기준" in compact:
        descriptions.append("수급자 선정기준과 급여별 선정기준을 확인할 때 사용하는 표이다.")
    return " ".join(descriptions)


def parse_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def is_separator_row(row: list[str]) -> bool:
    return bool(row) and all(SEPARATOR_CELL_RE.match(cell.strip()) for cell in row)


def infer_table_label(block: Block) -> str:
    context = "\n".join(block.lines[:2] + [block.section])
    match = TABLE_LABEL_RE.search(context)
    if match:
        return f"표 {match.group(1)}"
    return f"표 {block.block_id}"


def stable_table_no(block: Block, label: str) -> int:
    digits = re.sub(r"\D+", "", label)
    if digits:
        return int(digits[:6])
    return block.block_id


def infer_table_title(block: Block, table_label: str) -> str:
    section = block.section or "table"
    if table_label in section:
        return section
    return f"{section} {table_label}".strip()


def infer_year(*values: str) -> str:
    for value in values:
        match = YEAR_RE.search(value or "")
        if match:
            return next(group for group in match.groups() if group)
    return "not_specified"


def infer_unit(text: str) -> str:
    match = UNIT_RE.search(text)
    if match:
        return (match.group(1) or match.group(2) or "").strip()
    if "원" in text:
        return "원"
    if "%" in text:
        return "%"
    return "not_specified"


def render_table_text(
    *,
    source_file: str,
    section: str,
    table_id: str,
    parent_table_label: str,
    table_part_label: str,
    table_part: str,
    table_title: str,
    columns: str,
    unit: str,
    year: str,
    header: list[str],
    rows: list[list[str]],
    enhanced_caption: str,
) -> str:
    body_lines = [" | ".join(header)]
    body_lines.extend(" | ".join(row) for row in rows)
    metadata = [
        "[TABLE_START]",
        f"table_id: {table_id}",
        f"parent_table_label: {parent_table_label}",
        f"table_part_label: {table_part_label}",
        f"table_part: {table_part}",
        f"source: {source_file}",
        f"section: {section}",
        f"table_title: {table_title}",
        f"columns: {columns}",
        f"unit: {unit}",
        f"year: {year}",
        "",
        "[ENHANCED_TABLE_CAPTION]",
        enhanced_caption,
        "",
        "[ORIGINAL_TABLE_TEXT]",
    ]
    return "\n".join(metadata + body_lines + ["", "[TABLE_END]"]).strip()


def most_recent_section(blocks: list[Block]) -> str:
    for block in reversed(blocks):
        if block.section:
            return block.section
    return "document"


def pages_for_blocks(blocks: list[Block]) -> list[int]:
    pages: set[int] = set()
    for block in blocks:
        if block.page_start is not None:
            pages.add(block.page_start)
        if block.page_end is not None:
            pages.add(block.page_end)
    return sorted(pages)


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", lowered)
    lowered = lowered.strip("_")
    if not lowered:
        return "table"
    return lowered[:80]


def write_chunks(
    config: Any,
    input_path: Path,
    output_path: Path,
    chunks: list[ChunkDraft],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            chunk_sha256 = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            chunk_id = (
                f"{config.COLLECTION_NAME}:{config.CORPUS_VERSION}:"
                f"{chunk.source_hash[:12]}:{chunk.chunk_index:05d}"
            )
            metadata = {
                "chunk_id": chunk_id,
                "corpus_version": config.CORPUS_VERSION,
                "source_file": chunk.source_file,
                "source_hash": chunk.source_hash,
                "page": page_value(chunk.pages),
                "page_range": page_range(chunk.pages),
                "section": chunk.section,
                "block_type": chunk.block_type,
                "chunk_index": chunk.chunk_index,
                "chunk_chars": chunk.char_count,
                "chunk_sha256": chunk_sha256,
                **chunk.table_meta,
            }
            payload = {
                "chunk_id": chunk_id,
                "ordinal": chunk.chunk_index,
                "text": chunk.text,
                "original_table_text": chunk.original_table_text,
                "enhanced_caption": chunk.enhanced_caption,
                "text_sha256": chunk_sha256,
                "chunk_sha256": chunk_sha256,
                "char_count": chunk.char_count,
                "chunk_chars": chunk.char_count,
                "pages": chunk.pages,
                "page": metadata["page"],
                "page_range": metadata["page_range"],
                "section": chunk.section,
                "block_type": chunk.block_type,
                "block_types": chunk.block_kinds,
                "tags": chunk.tags,
                "warnings": chunk.warnings,
                "metadata": metadata,
                "source": {
                    "canonical_md": str(input_path),
                    "canonical_sha256": chunk.source_hash,
                    "source_file": chunk.source_file,
                },
                "policy": chunk_policy(config),
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def page_value(pages: list[int]) -> int | None:
    return pages[0] if len(pages) == 1 else None


def page_range(pages: list[int]) -> str:
    if not pages:
        return ""
    if len(pages) == 1:
        return str(pages[0])
    return f"{min(pages)}-{max(pages)}"


def chunk_policy(config: Any) -> dict[str, Any]:
    return {
        "corpus_version": config.CORPUS_VERSION,
        "collection_name": config.COLLECTION_NAME,
        "chunk_size_target": config.CHUNK_SIZE_TARGET,
        "chunk_overlap": config.CHUNK_OVERLAP_CHARS,
        "min_chunk_size": config.MIN_CHUNK_CHARS,
        "max_chunk_chars": config.MAX_CHUNK_CHARS,
        "max_table_part_chars": config.MAX_TABLE_PART_CHARS,
        "table_policy": "row-wise split; repeat title, columns, source, section, year, unit, table_id per part",
    }


def build_log_payload(
    config: Any,
    input_path: Path,
    input_selection: str,
    gate_path: Path,
    gate_selection: str,
    output_path: Path,
    blocks: list[Block],
    chunks: list[ChunkDraft],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    block_counts: dict[str, int] = {}
    chunk_counts: dict[str, int] = {}
    for block in blocks:
        block_counts[block.kind] = block_counts.get(block.kind, 0) + 1
    for chunk in chunks:
        chunk_counts[chunk.block_type] = chunk_counts.get(chunk.block_type, 0) + 1

    return {
        "step": "04_chunk_table_aware",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": config.describe_run(),
        "input_canonical_md": {
            "path": str(input_path),
            "selection": input_selection,
            "sha256": config.sha256_file(input_path),
            "size_bytes": input_path.stat().st_size,
        },
        "semantic_gate": {
            "path": str(gate_path),
            "selection": gate_selection,
            "sha256": config.sha256_file(gate_path),
        },
        "output_chunks_jsonl": {
            "path": str(output_path),
            "sha256": config.sha256_file(output_path),
            "size_bytes": output_path.stat().st_size,
        },
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "block_counts": dict(sorted(block_counts.items())),
        "chunk_counts": dict(sorted(chunk_counts.items())),
        "chunk_char_counts": [chunk.char_count for chunk in chunks],
        "table_chunk_count": chunk_counts.get("table", 0),
        "warnings": warnings,
        "policy": chunk_policy(config),
    }


def run_self_test(config: Any) -> None:
    sample = """---
source_pdf: sample.pdf
---

<!-- page: 1 -->
## 생계급여 선정기준
신청자는 소득인정액과 가구 특성을 함께 확인한다. 긴 문단은 문장 단위로 나뉘어야 한다.

| 가구원수 | 기준중위소득 | 생계급여 |
| --- | --- | --- |
| 1인가구 | 2,000,000 | 700,000 |
| 2인가구 | 3,000,000 | 1,100,000 |
| 3인가구 | 4,000,000 | 1,500,000 |
<!-- /page: 1 -->
"""
    blocks = parse_blocks(sample)
    chunks, warnings = build_chunks(config, blocks, "sample.pdf", "a" * 64)
    table_chunks = [chunk for chunk in chunks if chunk.block_type == "table"]
    if not table_chunks:
        raise AssertionError("expected table chunks")
    for chunk in table_chunks:
        for needle in ("[TABLE_START]", "table_id:", "columns:", "가구원수 | 기준중위소득 | 생계급여"):
            if needle not in chunk.text:
                raise AssertionError(f"missing table-safe marker: {needle}")
        if chunk.table_meta.get("embedding_surface_enhanced") is not True:
            raise AssertionError("expected embedding_surface_enhanced metadata")
        if chunk.table_meta.get("source_value_modified") is not False:
            raise AssertionError("source_value_modified must be false")
        if not chunk.original_table_text or not chunk.enhanced_caption:
            raise AssertionError("expected separate original table text and enhanced caption")
    if len({chunk.table_meta["table_id"] for chunk in table_chunks}) != 1:
        raise AssertionError("split table parts must retain one table_id")
    print(
        json.dumps(
            {
                "self_test": "passed",
                "block_count": len(blocks),
                "chunk_count": len(chunks),
                "table_chunk_count": len(table_chunks),
                "warnings": warnings,
                "policy": chunk_policy(config),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
