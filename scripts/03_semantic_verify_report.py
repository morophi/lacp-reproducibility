"""
Step 03: Semantic verification report.

Purpose:
    Generate a human-readable report before chunking.

Policy basis:
    Chunking must not start until a person can inspect semantic preservation.
    This step reports risks and creates a manual gate file in a non-approved
    state. It does not repair, chunk, or embed content.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")
SEMANTIC_TAG_RE = re.compile(
    r"<!--\s*semantic_tags:\s*(?P<tags>[^;]+);\s*page:\s*(?P<page>[^;]+);\s*markers:\s*(?P<markers>.*?)\s*-->"
)
PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
HEADING_RE = re.compile(r"^#{1,6}\s+")
BULLET_RE = re.compile(r"^\s*[-*]\s+")
NUMBERED_RE = re.compile(r"^\s*(?:\d+|[가-힣]|[A-Za-z])(?:[.)]|[．、])\s+")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
FOOTER_NOISE_RE = re.compile(r"^(?:\d+\s*[╻|]\s*)?$|^보건복지부$|^사회보장급여\s*$")


@dataclass(frozen=True)
class TaggedLine:
    line_number: int
    page: int | None
    tags: tuple[str, ...]
    marker_summary: str
    text: str


@dataclass
class VerificationStats:
    line_count: int = 0
    page_count: int = 0
    heading_count: int = 0
    bullet_count: int = 0
    numbered_count: int = 0
    table_line_count: int = 0
    semantic_comment_count: int = 0
    marker_hit_line_count: int = 0
    tag_counts: Counter[str] = field(default_factory=Counter)
    cooccurrence_counts: Counter[str] = field(default_factory=Counter)
    suspicious: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )


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
        description="Generate a human semantic verification report before chunking."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Canonical markdown path. Defaults to this run's config path, then latest canonical.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Report output path. Defaults to ingest_config.py SEMANTIC_REPORT.",
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=None,
        help="Gate JSON output path. Defaults to ingest_config.py SEMANTIC_GATE.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=12,
        help="Maximum suspicious examples per category.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print planned outputs without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_limit <= 0:
        raise ValueError("--sample-limit must be positive")

    config = load_config()
    input_path, input_selection = resolve_input_path(config, args.input)
    report_path = args.report or config.SEMANTIC_REPORT
    gate_path = args.gate or config.SEMANTIC_GATE

    if args.dry_run:
        payload = build_dry_run_payload(
            config, input_path, input_selection, report_path, gate_path, args.sample_limit
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    config.ensure_output_dirs()
    markdown = input_path.read_text(encoding="utf-8")
    stats, tagged_lines = analyze_markdown(config, markdown, args.sample_limit)
    report = render_report(config, input_path, input_selection, stats, tagged_lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    gate_payload = build_gate_payload(config, input_path, report_path, stats)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(gate_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"semantic_report={report_path}")
    print(f"semantic_gate={gate_path}")
    print(f"approved_for_chunking={gate_payload['approved_for_chunking']}")
    print(f"marker_hit_line_count={stats.marker_hit_line_count}")
    print(f"semantic_comment_count={stats.semantic_comment_count}")
    print(f"risk_category_count={len([v for v in stats.suspicious.values() if v])}")
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
        raise FileNotFoundError(
            "No canonical markdown found. Run 02_canonicalize_md.py first or pass --input."
        )
    return latest, "latest_fallback"


def build_dry_run_payload(
    config: Any,
    input_path: Path,
    input_selection: str,
    report_path: Path,
    gate_path: Path,
    sample_limit: int,
) -> dict[str, Any]:
    return {
        "step": "03_semantic_verify_report",
        "dry_run": True,
        "run": config.describe_run(),
        "input_canonical_md": str(input_path),
        "input_selection": input_selection,
        "input_canonical_md_exists": input_path.exists(),
        "output_report": str(report_path),
        "output_gate": str(gate_path),
        "sample_limit": sample_limit,
        "will_chunk": False,
        "will_embed": False,
        "gate_default_approved_for_chunking": False,
    }


def analyze_markdown(
    config: Any, markdown: str, sample_limit: int
) -> tuple[VerificationStats, list[TaggedLine]]:
    stats = VerificationStats()
    tagged_lines: list[TaggedLine] = []
    current_page: int | None = None
    pending_tags: tuple[str, ...] = ()
    pending_marker_summary = ""
    previous_nonblank = ""

    lines = markdown.splitlines()
    pages_seen: set[int] = set()
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        stats.line_count += 1

        page_match = PAGE_RE.match(stripped)
        if page_match:
            current_page = int(page_match.group(1))
            pages_seen.add(current_page)

        tag_match = SEMANTIC_TAG_RE.match(stripped)
        if tag_match:
            pending_tags = tuple(
                tag.strip() for tag in tag_match.group("tags").split(",") if tag.strip()
            )
            pending_marker_summary = tag_match.group("markers").strip()
            continue

        if not stripped or stripped.startswith("---"):
            previous_nonblank = previous_nonblank if not stripped else stripped
            continue

        if HEADING_RE.match(stripped):
            stats.heading_count += 1
        if BULLET_RE.match(stripped):
            stats.bullet_count += 1
        if NUMBERED_RE.match(stripped):
            stats.numbered_count += 1
        if TABLE_RE.match(stripped):
            stats.table_line_count += 1

        direct_tags = tuple(find_marker_hit_categories(config, stripped))
        effective_tags = pending_tags or direct_tags

        if pending_tags:
            stats.semantic_comment_count += 1

        if direct_tags:
            stats.marker_hit_line_count += 1
            for tag in direct_tags:
                stats.tag_counts[tag] += 1
            if len(direct_tags) > 1:
                stats.cooccurrence_counts["+".join(sorted(direct_tags))] += 1

        if effective_tags:
            tagged_lines.append(
                TaggedLine(
                    line_number=index,
                    page=current_page,
                    tags=effective_tags,
                    marker_summary=pending_marker_summary,
                    text=stripped,
                )
            )
            inspect_tagged_line(
                config, stats, sample_limit, index, current_page, effective_tags, stripped
            )
            pending_tags = ()
            pending_marker_summary = ""
        else:
            inspect_untagged_line(config, stats, sample_limit, index, current_page, stripped)

        inspect_structural_line(
            stats, sample_limit, index, current_page, stripped, previous_nonblank
        )
        previous_nonblank = stripped

    stats.page_count = len(pages_seen)
    inspect_global_coverage(config, stats, sample_limit, tagged_lines)
    return stats, tagged_lines


def inspect_tagged_line(
    config: Any,
    stats: VerificationStats,
    sample_limit: int,
    line_number: int,
    page: int | None,
    tags: tuple[str, ...],
    text: str,
) -> None:
    if "eligibility" in tags and "exception" in tags:
        add_sample(
            stats,
            "eligibility_exception_overlap",
            sample_limit,
            line_number,
            page,
            text,
            "Line contains both eligibility and exception markers; verify boundary is intentional.",
        )
    if "exception" in tags and not any(marker in text for marker in config.CONDITIONAL_MARKERS):
        add_sample(
            stats,
            "exception_without_condition_context",
            sample_limit,
            line_number,
            page,
            text,
            "Exception marker appears without nearby conditional marker in the same line.",
        )
    if len(tags) >= 3:
        add_sample(
            stats,
            "dense_marker_line",
            sample_limit,
            line_number,
            page,
            text,
            f"Line has {len(tags)} semantic tag categories; verify it should remain atomic.",
        )


def inspect_untagged_line(
    config: Any,
    stats: VerificationStats,
    sample_limit: int,
    line_number: int,
    page: int | None,
    text: str,
) -> None:
    if any(hint in text for hint in config.SECTION_HEADER_HINTS) and len(text) <= 100:
        add_sample(
            stats,
            "untagged_section_hint",
            sample_limit,
            line_number,
            page,
            text,
            "Line resembles a protected section header but has no semantic tag.",
        )
    if "해당" in text and ("자" in text or "사람" in text):
        add_sample(
            stats,
            "untagged_eligibility_like_phrase",
            sample_limit,
            line_number,
            page,
            text,
            "Line resembles eligibility language but was not tagged.",
        )


def inspect_structural_line(
    stats: VerificationStats,
    sample_limit: int,
    line_number: int,
    page: int | None,
    text: str,
    previous_nonblank: str,
) -> None:
    if TABLE_RE.match(text) and previous_nonblank and not TABLE_RE.match(previous_nonblank):
        add_sample(
            stats,
            "table_start_sample",
            sample_limit,
            line_number,
            page,
            text,
            "Table-like block starts here; verify header and row continuity.",
        )
    if FOOTER_NOISE_RE.match(text) and len(text) <= 20:
        add_sample(
            stats,
            "possible_footer_noise",
            sample_limit,
            line_number,
            page,
            text,
            "Short repeated line may be page furniture or footer/header noise.",
        )


def inspect_global_coverage(
    config: Any,
    stats: VerificationStats,
    sample_limit: int,
    tagged_lines: list[TaggedLine],
) -> None:
    missing_categories = [
        category for category in config.CANONICAL_MARKER_SETS if stats.tag_counts[category] == 0
    ]
    for category in missing_categories:
        add_sample(
            stats,
            "missing_marker_category",
            sample_limit,
            0,
            None,
            category,
            "No lines were tagged for this marker category.",
        )

    if tagged_lines and stats.heading_count == 0:
        add_sample(
            stats,
            "missing_headings",
            sample_limit,
            0,
            None,
            "heading_count=0",
            "Canonical markdown has semantic tags but no markdown headings.",
        )


def find_marker_hit_categories(config: Any, text: str) -> list[str]:
    categories = []
    for category, markers in config.CANONICAL_MARKER_SETS.items():
        if any(marker in text for marker in markers):
            categories.append(category)
    return categories


def add_sample(
    stats: VerificationStats,
    category: str,
    sample_limit: int,
    line_number: int,
    page: int | None,
    text: str,
    reason: str,
) -> None:
    samples = stats.suspicious[category]
    if len(samples) >= sample_limit:
        return
    samples.append(
        {
            "line": line_number,
            "page": page,
            "text": text[:240],
            "reason": reason,
        }
    )


def render_report(
    config: Any,
    input_path: Path,
    input_selection: str,
    stats: VerificationStats,
    tagged_lines: list[TaggedLine],
) -> str:
    risk_count = len([samples for samples in stats.suspicious.values() if samples])
    lines = [
        "# Semantic Verification Report",
        "",
        "## Gate Status",
        "",
        "- approved_for_chunking: false",
        "- required_action: Human review must approve canonical markdown before chunking.",
        "- next_allowed_step_before_approval: none beyond report inspection",
        "",
        "## Inputs",
        "",
        f"- canonical_md: `{input_path}`",
        f"- input_selection: `{input_selection}`",
        f"- run_id: `{config.RUN_ID}`",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Scope And Impact",
        "",
        "- changes_corpus: report-only, no corpus mutation",
        "- changes_chunks: false",
        "- changes_embeddings: false",
        "- changes_retrieval: false",
        "- experiment_variables_directly_changed: none",
        "- experiment_variables_quality_impact: CDS, SRR, SCI via manual verification gate",
        "",
        "## Structural Counts",
        "",
        f"- line_count: {stats.line_count}",
        f"- page_count: {stats.page_count}",
        f"- heading_count: {stats.heading_count}",
        f"- bullet_count: {stats.bullet_count}",
        f"- numbered_count: {stats.numbered_count}",
        f"- table_line_count: {stats.table_line_count}",
        f"- semantic_comment_count: {stats.semantic_comment_count}",
        f"- marker_hit_line_count: {stats.marker_hit_line_count}",
        f"- risk_category_count: {risk_count}",
        "",
        "## Semantic Tag Counts",
        "",
    ]

    for category in sorted(config.CANONICAL_MARKER_SETS):
        lines.append(f"- {category}: {stats.tag_counts.get(category, 0)}")

    lines.extend(["", "## Tag Cooccurrence Counts", ""])
    if stats.cooccurrence_counts:
        for name, count in sorted(stats.cooccurrence_counts.items()):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Manual Checklist", ""])
    checklist = [
        "Tables preserve headers and row order.",
        "Eligibility blocks remain adjacent to exception and conditional language.",
        "Procedure lines are not merged into benefit amount rules.",
        "Repeated page furniture does not intrude into semantic blocks.",
        "Section headers survive as markdown headings where appropriate.",
        "Numbered and bullet lists preserve item order.",
        "Dense multi-tag lines are reviewed before chunking.",
    ]
    for item in checklist:
        lines.append(f"- [ ] {item}")

    lines.extend(["", "## Suspicious Samples", ""])
    if stats.suspicious:
        for category in sorted(stats.suspicious):
            samples = stats.suspicious[category]
            if not samples:
                continue
            lines.append(f"### {category}")
            lines.append("")
            for sample in samples:
                lines.append(
                    f"- line {sample['line']}, page {sample['page']}: {sample['reason']}"
                )
                lines.append(f"  `{sample['text']}`")
            lines.append("")
    else:
        lines.append("- No suspicious samples collected by heuristics.")

    lines.extend(["## Tagged Line Samples", ""])
    for sample in tagged_lines[:20]:
        lines.append(
            f"- line {sample.line_number}, page {sample.page}, tags={','.join(sample.tags)}"
        )
        lines.append(f"  markers: `{sample.marker_summary}`")
        lines.append(f"  text: `{sample.text[:220]}`")

    lines.extend(
        [
            "",
            "## Determinism Notes",
            "",
            "- Report sample order follows canonical markdown line order.",
            "- No random sampling is used.",
            "- generated_at_utc changes per run and is limited to report/gate metadata.",
            "- If input is selected by latest fallback, future files can change which canonical markdown is reviewed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_gate_payload(
    config: Any, input_path: Path, report_path: Path, stats: VerificationStats
) -> dict[str, Any]:
    return {
        "step": "03_semantic_verify_report",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": config.RUN_ID,
        "approved_for_chunking": False,
        "approval_required_by": "human",
        "canonical_md": str(input_path),
        "semantic_report": str(report_path),
        "semantic_comment_count": stats.semantic_comment_count,
        "marker_hit_line_count": stats.marker_hit_line_count,
        "risk_categories": {
            category: len(samples)
            for category, samples in sorted(stats.suspicious.items())
            if samples
        },
        "next_step_when_approved": "04_chunk_table_aware.py",
        "blocked_steps_until_approved": [
            "04_chunk_table_aware.py",
            "05_embed_chunks.py",
            "06_manifest_snapshot.py",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
