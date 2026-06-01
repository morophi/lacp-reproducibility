"""
Step 18: Apply assisted labels to the v2 manual freeze-gate CSV.

This script is a first-pass labeling assistant, not a silent policy freeze. It
fills `manual_labeling_targets_v2.csv` by searching the full chunk JSONL inside
the expected source/guideline and choosing the best evidence chunk for each
query. The subsequent Step 17 evaluator then checks whether the selected
evidence appears in the candidate retrieval result.

Why this is separate from Step 17:
    - Step 17 evaluates labels and must stay read-only.
    - Step 18 writes a labeled CSV, but only under the validation logs path.
    - Active RAG node collections are never touched.

The labels should still be reviewed before declaring formal freeze. The script
marks confidence and notes so weak or ambiguous auto-assisted choices are easy
to inspect.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path("/Users/morophi/lacp_rag")
RUN_ROOT = ROOT / "full_corpus" / "20260525T_full_guideline_v1"
DEFAULT_LABELS = RUN_ROOT / "logs" / "manual_labeling_targets_v2.csv"
DEFAULT_REPORT = (
    RUN_ROOT
    / "logs"
    / "full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json"
)
DEFAULT_CHUNKS = (
    RUN_ROOT
    / "chunks"
    / "rag_full_guidelines_2026_20260525T_full_guideline_v1_chunks.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply assisted labels to manual_labeling_targets_v2.csv.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument(
        "--output",
        type=Path,
        default=RUN_ROOT / "logs" / "manual_labeling_targets_v2_assisted.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    label_rows = read_csv(args.labels)
    report = read_json(args.report)
    report_by_query = {row["query_id"]: row for row in report.get("per_query", [])}
    chunks_by_source = load_chunks_by_source(args.chunks)
    labeled_rows = [
        label_row(row, report_by_query.get(row.get("query_id", ""), {}), chunks_by_source)
        for row in label_rows
    ]
    write_csv(args.output, labeled_rows)
    print(
        json.dumps(
            {
                "input_rows": len(label_rows),
                "labeled_rows": len(labeled_rows),
                "output": str(args.output),
                "judgment_counts": count_values(labeled_rows, "manual_judgment"),
                "confidence_counts": count_values(labeled_rows, "label_confidence"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def load_chunks_by_source(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            metadata = row.get("metadata") or {}
            guideline_id = metadata.get("guideline_id") or parse_guideline_id(row.get("chunk_id", ""))
            chunk = {
                "chunk_id": row.get("chunk_id", ""),
                "text": row.get("text", ""),
                "section": metadata.get("section", ""),
                "block_type": metadata.get("block_type", ""),
                "table_id": metadata.get("table_id", ""),
                "table_title": metadata.get("table_title", ""),
                "guideline_id": guideline_id,
            }
            by_source.setdefault(guideline_id, []).append(chunk)
    return by_source


def label_row(
    row: dict[str, str],
    report_row: dict[str, Any],
    chunks_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    expected_source = row.get("expected_source_id") or row.get("expected_guideline_id")
    candidates = chunks_by_source.get(expected_source, [])
    query_text = row.get("query_text", "")
    query_type = row.get("query_type", "")
    best = choose_best_chunk(query_text, query_type, candidates)
    retrieved_chunk_ids = set(split_pipe_from_notes(row.get("notes", ""), "retrieved_chunk_ids"))
    if report_row:
        retrieved_chunk_ids.update(report_row.get("retrieved_chunk_ids", []))
    manual_judgment = "pass" if best and best["chunk_id"] in retrieved_chunk_ids else "fail"
    confidence = confidence_for(best, query_type)
    labeled = dict(row)
    labeled["expected_section"] = best.get("section", "") if best else ""
    labeled["expected_chunk_id"] = best.get("chunk_id", "") if best else ""
    labeled["expected_block_type"] = expected_block_type(best, query_type)
    labeled["expected_table_id"] = best.get("table_id", "") if best and expected_block_type(best, query_type) == "table" else ""
    labeled["label_confidence"] = confidence
    labeled["manual_judgment"] = manual_judgment
    labeled["notes"] = append_note(
        row.get("notes", ""),
        (
            "assisted_label=true; "
            f"best_score={best.get('score', 0) if best else 0}; "
            f"best_chunk_in_retrieved_top5={manual_judgment == 'pass'}; "
            "requires_human_review_before_formal_freeze=true"
        ),
    )
    return labeled


def choose_best_chunk(query_text: str, query_type: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    terms = query_terms(query_text)
    scored: list[dict[str, Any]] = []
    for chunk in candidates:
        text = compact("\n".join([chunk.get("text", ""), chunk.get("section", ""), chunk.get("table_title", "")]))
        score = 0.0
        score += sum(1.0 for term in terms if term and term in text)
        if query_type == "table_sensitive" and is_table(chunk):
            score += 3.0
        if query_type == "eligibility" and any(token in text for token in ["지원대상", "대상자", "선정기준", "수급권자"]):
            score += 2.0
        if query_type == "exception" and any(token in text for token in ["제외", "중지", "예외", "불가", "제한"]):
            score += 2.0
        if query_type == "procedure" and any(token in text for token in ["신청", "절차", "서류", "의뢰", "처리"]):
            score += 2.0
        if score <= 0:
            continue
        copied = dict(chunk)
        copied["score"] = round(score, 4)
        scored.append(copied)
    scored.sort(key=lambda item: (-float(item["score"]), item["chunk_id"]))
    return scored[0] if scored else {}


def expected_block_type(best: dict[str, Any], query_type: str) -> str:
    if not best:
        return "text"
    if query_type == "table_sensitive" and is_table(best):
        return "table"
    block_type = str(best.get("block_type") or "").strip()
    if block_type in {"table", "text", "procedure", "exception"}:
        return block_type
    if query_type in {"procedure", "exception"}:
        return query_type
    return "text"


def confidence_for(best: dict[str, Any], query_type: str) -> str:
    if not best:
        return "low"
    score = float(best.get("score", 0))
    if query_type == "table_sensitive" and is_table(best) and score >= 5:
        return "high"
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def is_table(chunk: dict[str, Any]) -> bool:
    return chunk.get("block_type") == "table" or bool(chunk.get("table_id"))


def query_terms(value: str) -> list[str]:
    return [compact(part) for part in re.split(r"\s+", value) if len(compact(part)) >= 2]


def compact(value: str) -> str:
    return "".join(str(value or "").lower().split())


def parse_guideline_id(chunk_id: str) -> str:
    parts = chunk_id.split("__")
    return parts[1] if len(parts) >= 3 else ""


def split_pipe_from_notes(notes: str, key: str) -> list[str]:
    marker = f"{key}="
    if marker not in notes:
        return []
    tail = notes.split(marker, 1)[1]
    value = tail.split(";", 1)[0].strip()
    return [part for part in value.split("|") if part]


def append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    return f"{existing}; {note}"


def count_values(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key, "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
