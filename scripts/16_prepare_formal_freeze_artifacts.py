"""
Step 16: Prepare pre-CR formal retrieval-freeze review artifacts.

This is a read-only artifact builder. It converts the selected formal-candidate
coverage report into review files:

1. `source_aware_table_diagnostic.csv`
   A table-sensitive slice focused on whether the source-aware table route
   actually exposed table evidence without damaging expected-source retrieval.

2. `manual_labeling_targets_v1.csv`
   A compact 10-20 query queue for manual section/chunk/table labels. These
   labels are preserved as the earlier sanity-check set when already present.

3. `manual_labeling_targets_v2.csv`
   A stratified 40-query pre-CR freeze gate set. This is the final manual review
   queue unless a critical failure cluster is discovered.

The script does not query ChromaDB, rebuild embeddings, ingest data, or change
retrieval policy. It only reshapes existing Step 12 JSON reports.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs")
DEFAULT_REPORT = (
    DEFAULT_LOG_DIR
    / "full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare source-aware table diagnostics and manual label targets."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--manual-target-count", type=int, default=20)
    parser.add_argument("--manual-v2-target-count", type=int, default=40)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = read_json(args.report)
    rows = payload.get("per_query", [])
    table_rows = [row for row in rows if row.get("table_sensitive")]
    source_aware_rows = build_source_aware_table_rows(table_rows)
    manual_targets = build_manual_labeling_targets(rows, args.manual_target_count)
    manual_targets_v2, v2_counts = build_manual_labeling_targets_v2(rows, args.manual_v2_target_count)

    write_csv(args.output_dir / "source_aware_table_diagnostic.csv", source_aware_rows)
    # Preserve the original v1 sanity-check queue once it exists. The v2 file is
    # now the pre-CR formal gate set, so rerunning this script should not rewrite
    # a previously reviewed v1 artifact.
    v1_path = args.output_dir / "manual_labeling_targets_v1.csv"
    if not v1_path.exists():
        write_csv(v1_path, manual_targets)
    write_csv(args.output_dir / "manual_labeling_targets_v2.csv", manual_targets_v2)
    print(
        json.dumps(
            {
                "source_aware_table_diagnostic_rows": len(source_aware_rows),
                "manual_labeling_targets_v1_preserved": v1_path.exists(),
                "manual_labeling_targets_v2": len(manual_targets_v2),
                "manual_labeling_targets_v2_counts": v2_counts,
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_source_aware_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item.get("query_id", "")):
        table_results = [
            item
            for item in row.get("results", [])
            if item.get("block_type") == "table" or item.get("table_id") or item.get("table_lexical_rank")
        ]
        output.append(
            {
                "query_id": row.get("query_id", ""),
                "query": row.get("query", ""),
                "query_type": row.get("query_type", ""),
                "primary_expected_guideline_id": row.get("primary_expected_guideline_id", ""),
                "expected_guideline_ids": join(row.get("expected_guideline_ids", [])),
                "expected_source_in_top5": row.get("expected_source_in_top5", False),
                "table_exposure_hit": row.get("table_exposure_hit", False),
                "top1_source": row.get("top1_source", ""),
                "top5_sources": join(row.get("top5_sources", [])),
                "retrieved_chunk_ids": join(row.get("retrieved_chunk_ids", [])),
                "table_candidate_count_in_final_top5": len(table_results),
                "table_candidate_chunk_ids": join(item.get("chunk_id", "") for item in table_results),
                "table_candidate_sources": join(item.get("guideline_id", "") for item in table_results),
                "table_candidate_routes": join(route_string(item) for item in table_results),
                "diagnostic_status": table_status(row),
            }
        )
    return output


def build_manual_labeling_targets(
    rows: list[dict[str, Any]],
    manual_target_count: int,
) -> list[dict[str, Any]]:
    # Prioritize table-sensitive rows first because source-level labels are too
    # coarse for deciding whether table exposure is truly useful. Then add
    # remaining expected-source failures from exception/procedure-heavy queries
    # until the requested compact review queue is full.
    ordered = sorted(rows, key=lambda row: (not row.get("table_sensitive"), row.get("query_id", "")))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ordered:
        if row.get("table_sensitive"):
            selected.append(manual_target_row(row, "table_sensitive_validation"))
            seen.add(row.get("query_id", ""))
    for row in sorted(rows, key=failure_priority):
        if len(selected) >= manual_target_count:
            break
        query_id = row.get("query_id", "")
        if query_id in seen:
            continue
        if not row.get("expected_source_in_top5") or row.get("query_type") in {"exception", "procedure"}:
            selected.append(manual_target_row(row, "source_or_section_failure_review"))
            seen.add(query_id)
    return selected[:manual_target_count]


def build_manual_labeling_targets_v2(
    rows: list[dict[str, Any]],
    target_count: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    # The v2 set is stratified because formal freeze risks are not evenly
    # distributed. Table, eligibility, exception, and procedure queries carry
    # more causal interpretation risk than title-direct sanity checks. If a
    # requested stratum has fewer available rows in the curated query set, the
    # deficit is filled from previous failures/borderline rows to keep the gate
    # at 40 without inventing new queries.
    quotas = [
        ("table_sensitive", 10, lambda row: bool(row.get("table_sensitive"))),
        ("eligibility", 8, lambda row: row.get("query_type") == "eligibility"),
        ("exception", 8, lambda row: row.get("query_type") == "exception"),
        ("procedure", 6, lambda row: row.get("query_type") == "procedure"),
        ("concept", 4, lambda row: row.get("query_type") == "concept"),
        ("title_direct", 2, lambda row: row.get("query_type") == "title_direct"),
        (
            "previous_failure_borderline",
            2,
            lambda row: is_failure_or_borderline(row),
        ),
    ]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    deficits = 0
    for stratum, quota, predicate in quotas:
        candidates = [row for row in sorted(rows, key=stratified_priority) if predicate(row)]
        added = add_candidates(selected, seen, candidates, quota, stratum)
        counts[stratum] = added
        deficits += max(quota - added, 0)

    if len(selected) < target_count:
        filler = [
            row
            for row in sorted(rows, key=stratified_priority)
            if row.get("query_id", "") not in seen
        ]
        counts["deficit_filled_by_borderline_pool"] = add_candidates(
            selected,
            seen,
            filler,
            target_count - len(selected),
            "quota_deficit_borderline_fill",
        )
    counts["quota_deficit_count"] = deficits
    return selected[:target_count], counts


def add_candidates(
    selected: list[dict[str, Any]],
    seen: set[str],
    candidates: list[dict[str, Any]],
    quota: int,
    stratum: str,
) -> int:
    added = 0
    for row in candidates:
        if added >= quota:
            break
        query_id = row.get("query_id", "")
        if query_id in seen:
            continue
        selected.append(manual_target_row_v2(row, stratum))
        seen.add(query_id)
        added += 1
    return added


def manual_target_row_v2(row: dict[str, Any], stratum: str) -> dict[str, Any]:
    expected_sources = row.get("expected_guideline_ids", [])
    primary_expected = row.get("primary_expected_guideline_id", "")
    return {
        "query_id": row.get("query_id", ""),
        "query_type": row.get("query_type", ""),
        "query_text": row.get("query", ""),
        "expected_source_id": primary_expected,
        "expected_guideline_id": primary_expected,
        "expected_section": "",
        "expected_chunk_id": "",
        "expected_block_type": "",
        "expected_table_id": "",
        "minimum_acceptable_evidence": minimum_acceptable_evidence(row),
        "criticality": criticality(row),
        "label_confidence": "",
        "manual_judgment": "",
        "notes": (
            f"stratum={stratum}; expected_any={join(expected_sources)}; "
            f"current_rank={row.get('expected_source_rank', '')}; "
            f"table_exposure={row.get('table_exposure_hit', False)}; "
            f"top5_sources={join(row.get('top5_sources', []))}; "
            f"retrieved_chunk_ids={join(row.get('retrieved_chunk_ids', []))}"
        ),
    }


def minimum_acceptable_evidence(row: dict[str, Any]) -> str:
    query_type = row.get("query_type")
    if row.get("table_sensitive"):
        return "Correct expected source plus correct table or table-equivalent numeric/criteria evidence."
    if query_type == "eligibility":
        return "Correct expected source plus eligibility criteria, 대상자, 선정기준, or equivalent support scope."
    if query_type == "exception":
        return "Correct expected source plus exclusion, exception, stop, or non-eligibility condition."
    if query_type == "procedure":
        return "Correct expected source plus application, document, referral, processing, or workflow evidence."
    if query_type == "concept":
        return "Correct expected source plus concept definition or semantically equivalent guideline passage."
    return "Correct expected source and enough local evidence to identify the requested guideline topic."


def criticality(row: dict[str, Any]) -> str:
    if row.get("table_sensitive"):
        return "critical"
    if row.get("query_type") in {"eligibility", "exception"}:
        return "critical"
    if not row.get("expected_source_in_top5"):
        return "critical"
    if row.get("query_type") == "procedure":
        return "major"
    return "minor"


def is_failure_or_borderline(row: dict[str, Any]) -> bool:
    rank = row.get("expected_source_rank")
    return (
        not row.get("expected_source_in_top5")
        or rank in {4, 5}
        or (row.get("table_sensitive") and not row.get("table_exposure_hit"))
        or row.get("query_type") in {"eligibility", "exception"}
    )


def stratified_priority(row: dict[str, Any]) -> tuple[int, int, str]:
    rank = row.get("expected_source_rank")
    rank_value = int(rank) if isinstance(rank, int) else 999
    failure_bucket = 0 if not row.get("expected_source_in_top5") else 1
    if row.get("table_sensitive") and not row.get("table_exposure_hit"):
        failure_bucket = -1
    return (failure_bucket, -rank_value, row.get("query_id", ""))


def manual_target_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "query_id": row.get("query_id", ""),
        "query": row.get("query", ""),
        "query_type": row.get("query_type", ""),
        "labeling_reason": reason,
        "primary_expected_guideline_id": row.get("primary_expected_guideline_id", ""),
        "expected_guideline_ids": join(row.get("expected_guideline_ids", [])),
        "current_expected_source_rank": row.get("expected_source_rank", ""),
        "current_expected_source_in_top5": row.get("expected_source_in_top5", False),
        "current_table_exposure_hit": row.get("table_exposure_hit", False),
        "top5_sources": join(row.get("top5_sources", [])),
        "retrieved_chunk_ids": join(row.get("retrieved_chunk_ids", [])),
        "expected_section_manual": "",
        "expected_chunk_id_manual": "",
        "expected_block_type_manual": "",
        "expected_table_id_manual": "",
        "manual_label_notes": "",
    }


def failure_priority(row: dict[str, Any]) -> tuple[int, str]:
    if not row.get("expected_source_in_top5"):
        return (0, row.get("query_id", ""))
    if row.get("query_type") == "exception":
        return (1, row.get("query_id", ""))
    if row.get("query_type") == "procedure":
        return (2, row.get("query_id", ""))
    return (3, row.get("query_id", ""))


def table_status(row: dict[str, Any]) -> str:
    if row.get("expected_source_in_top5") and row.get("table_exposure_hit"):
        return "expected_source_and_table_exposed"
    if row.get("expected_source_in_top5"):
        return "expected_source_without_table_exposure"
    if row.get("table_exposure_hit"):
        return "table_exposed_but_expected_source_missed"
    return "expected_source_and_table_missed"


def route_string(item: dict[str, Any]) -> str:
    routes = "+".join(item.get("source_routes", []))
    return (
        f"{item.get('chunk_id', '')}:"
        f"{routes}:"
        f"v{item.get('vector_rank', '')}:"
        f"l{item.get('lexical_rank', '')}:"
        f"t{item.get('table_lexical_rank', '')}:"
        f"rrf{item.get('rrf_score', '')}"
    )


def join(values: Any) -> str:
    return "|".join(str(value) for value in values if str(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
