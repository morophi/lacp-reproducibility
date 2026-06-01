"""
Step 19: Analyze evidence-localization diagnostic failures.

This read-only analyzer joins the evidence-localized Step 12 report with the
assisted/manual v2 labels and classifies each failed query into a stage:

- source_miss
- source_hit_but_section_miss
- section_hit_but_chunk_miss
- chunk_candidate_but_ranked_out
- table_candidate_missing
- table_candidate_ranked_out
- evidence_hit

It writes detailed and grouped CSVs so the next fix can target localization
rather than destabilizing the source-level retrieval policy.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


RUN_ROOT = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1")
DEFAULT_REPORT = (
    RUN_ROOT
    / "logs"
    / "full_guideline_retrieval_coverage_body_only_v1_evidence_localization_v1_report.json"
)
DEFAULT_LABELS = RUN_ROOT / "logs" / "manual_labeling_targets_v2_assisted.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze evidence localization failure stages.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path, default=RUN_ROOT / "logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = read_json(args.report)
    labels = read_csv(args.labels)
    report_by_query = {row["query_id"]: row for row in report.get("per_query", [])}
    rows = [diagnose(label, report_by_query.get(label["query_id"], {})) for label in labels]
    write_csv(args.output_dir / "evidence_localization_diagnostic.csv", rows)
    write_csv(args.output_dir / "failure_stage_breakdown.csv", breakdown(rows, ["failure_stage"]))
    write_csv(args.output_dir / "query_type_failure_stage_breakdown.csv", breakdown(rows, ["query_type", "failure_stage"]))
    print(
        json.dumps(
            {
                "rows": len(rows),
                "failure_stage_counts": dict(Counter(row["failure_stage"] for row in rows)),
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def diagnose(label: dict[str, str], report_row: dict[str, Any]) -> dict[str, Any]:
    expected_source = label.get("expected_source_id", "")
    expected_section = label.get("expected_section", "")
    expected_chunk_id = label.get("expected_chunk_id", "")
    expected_table_id = label.get("expected_table_id", "")
    expected_block_type = label.get("expected_block_type", "")
    results = report_row.get("results", [])
    candidate_ids = set(report_row.get("candidate_chunk_ids", []))
    top5_ids = set(report_row.get("retrieved_chunk_ids", []))
    top5_sources = set(report_row.get("top5_sources", []))
    source_hit = expected_source in top5_sources
    section_hit = any(expected_section and expected_section in str(item.get("section", "")) for item in results)
    chunk_hit = expected_chunk_id in top5_ids
    table_hit = bool(expected_table_id and any(expected_table_id == item.get("table_id") for item in results))
    table_candidate_present = any(
        item.get("block_type") == "table" or item.get("table_id") for item in results
    )
    if not source_hit:
        stage = "source_miss"
    elif expected_block_type == "table" and not table_candidate_present:
        stage = "table_candidate_missing"
    elif expected_block_type == "table" and expected_table_id and not table_hit:
        stage = "table_candidate_ranked_out" if expected_chunk_id in candidate_ids else "table_candidate_missing"
    elif expected_chunk_id and chunk_hit:
        stage = "evidence_hit"
    elif expected_section and not section_hit:
        stage = "source_hit_but_section_miss"
    elif expected_chunk_id and expected_chunk_id in candidate_ids:
        stage = "chunk_candidate_but_ranked_out"
    else:
        stage = "section_hit_but_chunk_miss"
    return {
        "query_id": label.get("query_id", ""),
        "query_type": label.get("query_type", ""),
        "expected_source_id": expected_source,
        "expected_section": expected_section,
        "expected_chunk_id": expected_chunk_id,
        "expected_block_type": expected_block_type,
        "expected_table_id": expected_table_id,
        "source_hit": source_hit,
        "section_hit": section_hit,
        "chunk_hit": chunk_hit,
        "table_hit": table_hit,
        "table_candidate_present": table_candidate_present,
        "failure_stage": stage,
        "top5_sources": "|".join(report_row.get("top5_sources", [])),
        "retrieved_chunk_ids": "|".join(report_row.get("retrieved_chunk_ids", [])),
    }


def breakdown(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, ...]] = Counter(tuple(str(row[key]) for key in keys) for row in rows)
    return [
        {**{key: value for key, value in zip(keys, values)}, "count": count}
        for values, count in sorted(counts.items())
    ]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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
