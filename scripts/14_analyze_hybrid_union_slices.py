"""
Step 14: Analyze hybrid-union diagnostic slices before policy freeze.

This is a read-only report builder. It compares existing Step 12 coverage
outputs for lexical_only and hybrid_union_rrf_v1, then writes focused slices for
the remaining formal-readiness risks: lexical hits that RRF missed, dominant
wrong-top1 source behavior, route-level RRF effects, and table-sensitive
failures. It does not query ChromaDB, rebuild embeddings, ingest collections, or
change retrieval policy.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs")
DEFAULT_QUERY_FILE = Path("/Users/morophi/lacp_rag/validation_queries/full_guideline_coverage_queries_v1.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create focused hybrid_union_rrf_v1 diagnostic slices."
    )
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    parser.add_argument(
        "--hybrid-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_hybrid_union_rrf_v1_report.json",
    )
    parser.add_argument(
        "--lexical-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_lexical_only_report.json",
    )
    parser.add_argument(
        "--source-overrepresentation",
        type=Path,
        default=DEFAULT_LOG_DIR / "source_overrepresentation.csv",
    )
    parser.add_argument(
        "--source-chunk-distribution",
        type=Path,
        default=DEFAULT_LOG_DIR / "source_chunk_distribution.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument(
        "--output-prefix",
        default="hybrid_union_rrf_v1",
        help="Prefix used for slice output filenames so multiple variants can be compared without overwriting.",
    )
    parser.add_argument("--dominant-guideline-id", default="g04_src_19cd6bb8")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    queries = load_queries(args.queries)
    hybrid = read_json(args.hybrid_report)
    lexical = read_json(args.lexical_report)
    hybrid_rows = {row["query_id"]: row for row in hybrid.get("per_query", [])}
    lexical_rows = {row["query_id"]: row for row in lexical.get("per_query", [])}

    lexical_misses = build_lexical_hit_union_miss(queries, lexical_rows, hybrid_rows)
    g04_diagnostic, g04_cases = build_dominant_source_diagnostic(
        queries=queries,
        hybrid_rows=hybrid_rows,
        source_chunk_distribution=read_csv(args.source_chunk_distribution),
        source_overrepresentation=read_csv(args.source_overrepresentation),
        guideline_id=args.dominant_guideline_id,
    )
    g04_wrong_rows, g04_route_rows, correct_rank_rows = build_g04_wrong_top1_diagnostics(
        dominant_guideline_id=args.dominant_guideline_id,
        hybrid_rows=hybrid_rows,
    )
    table_slice = build_table_sensitive_slice(queries, hybrid_rows)
    summary = {
        "step": "14_analyze_hybrid_union_slices",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "hybrid_report": str(args.hybrid_report),
        "lexical_report": str(args.lexical_report),
        "dominant_guideline_id": args.dominant_guideline_id,
        "lexical_hit_union_miss_count": len(lexical_misses),
        "g04_wrong_top1_count": g04_diagnostic["g04_wrong_top1_count"],
        "g04_correct_top1_count": g04_diagnostic["g04_correct_top1_count"],
        "table_sensitive_query_count": len(table_slice),
        "table_sensitive_expected_any_top5_hit_rate": rate(table_slice, "expected_source_in_top5"),
        "table_sensitive_table_exposure_hit_rate": rate(table_slice, "table_exposure_hit"),
    }

    prefix = args.output_prefix
    write_csv(args.output_dir / f"{prefix}_vs_lexical_miss.csv", lexical_misses)
    write_json(args.output_dir / f"{prefix}_g04_diagnostic.json", g04_diagnostic)
    write_csv(args.output_dir / f"{prefix}_g04_top1_cases.csv", g04_cases)
    write_csv(args.output_dir / f"{prefix}_g04_wrong_top1_diagnostic.csv", g04_wrong_rows)
    write_csv(args.output_dir / f"{prefix}_g04_route_breakdown.csv", g04_route_rows)
    write_csv(args.output_dir / f"{prefix}_correct_source_rank_when_g04_wrong_top1.csv", correct_rank_rows)
    write_csv(args.output_dir / f"{prefix}_table_sensitive_slice.csv", table_slice)
    write_json(args.output_dir / f"{prefix}_slice_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def load_queries(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("expected_guideline_ids", [row["primary_expected_guideline_id"]])
            rows[row["query_id"]] = row
    return rows


def build_lexical_hit_union_miss(
    queries: dict[str, dict[str, Any]],
    lexical_rows: dict[str, dict[str, Any]],
    hybrid_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    misses: list[dict[str, Any]] = []
    for query_id, lexical in lexical_rows.items():
        hybrid = hybrid_rows.get(query_id)
        if not hybrid:
            continue
        if lexical.get("expected_source_in_top5") and not hybrid.get("expected_source_in_top5"):
            query = queries.get(query_id, {})
            misses.append(
                {
                    "query_id": query_id,
                    "query": lexical.get("query", ""),
                    "query_type": lexical.get("query_type", ""),
                    "primary_expected_guideline_id": lexical.get("primary_expected_guideline_id", ""),
                    "expected_guideline_ids": "|".join(lexical.get("expected_guideline_ids", [])),
                    "lexical_expected_rank": lexical.get("expected_source_rank"),
                    "hybrid_expected_rank": hybrid.get("expected_source_rank"),
                    "lexical_top5_sources": "|".join(lexical.get("top5_sources", [])),
                    "hybrid_top5_sources": "|".join(hybrid.get("top5_sources", [])),
                    "hybrid_top1_source": hybrid.get("top1_source", ""),
                    "table_sensitive": query.get("table_sensitive", False),
                    "hypothesis": (
                        "Lexical route found an expected source, but RRF interleaving or vector candidates "
                        "pushed it below top5."
                    ),
                }
            )
    return misses


def build_dominant_source_diagnostic(
    queries: dict[str, dict[str, Any]],
    hybrid_rows: dict[str, dict[str, Any]],
    source_chunk_distribution: list[dict[str, str]],
    source_overrepresentation: list[dict[str, str]],
    guideline_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    chunk_row = first_row(source_chunk_distribution, "guideline_id", guideline_id)
    overrep_row = first_matching_row(
        source_overrepresentation,
        {"retrieval_mode": "hybrid_union_rrf_v1", "guideline_id": guideline_id},
    )
    expected_label_count = sum(
        1 for query in queries.values() if guideline_id in set(query.get("expected_guideline_ids", []))
    )
    cases: list[dict[str, Any]] = []
    for query_id, row in sorted(hybrid_rows.items()):
        if row.get("top1_source") != guideline_id:
            continue
        expected_sources = set(row.get("expected_guideline_ids", []))
        is_correct = guideline_id in expected_sources
        cases.append(
            {
                "query_id": query_id,
                "query": row.get("query", ""),
                "query_type": row.get("query_type", ""),
                "primary_expected_guideline_id": row.get("primary_expected_guideline_id", ""),
                "expected_guideline_ids": "|".join(row.get("expected_guideline_ids", [])),
                "top1_source": guideline_id,
                "top1_correct": is_correct,
                "expected_source_rank": row.get("expected_source_rank"),
                "top5_sources": "|".join(row.get("top5_sources", [])),
                "retrieved_chunk_ids": "|".join(row.get("retrieved_chunk_ids", [])),
            }
        )
    correct = sum(1 for row in cases if row["top1_correct"])
    wrong = len(cases) - correct
    query_count = len(hybrid_rows)
    diagnostic = {
        "guideline_id": guideline_id,
        "retrieval_mode": "hybrid_union_rrf_v1",
        "corpus_chunk_count": int(float(chunk_row.get("source_chunk_count", 0) or 0)),
        "corpus_chunk_share": float(chunk_row.get("corpus_chunk_share", 0) or 0),
        "expected_label_count": expected_label_count,
        "expected_label_share": round(expected_label_count / len(queries), 6) if queries else 0.0,
        "retrieval_top1_count": len(cases),
        "retrieval_top1_share": round(len(cases) / query_count, 6) if query_count else 0.0,
        "top1_overrepresentation_ratio": parse_float(overrep_row.get("top1_overrepresentation_ratio")),
        "top5_overrepresentation_ratio": parse_float(overrep_row.get("top5_overrepresentation_ratio")),
        "top30_overrepresentation_ratio": parse_float(overrep_row.get("top30_overrepresentation_ratio")),
        "g04_correct_top1_count": correct,
        "g04_wrong_top1_count": wrong,
        "wrong_top1_query_type_distribution": dict(Counter(row["query_type"] for row in cases if not row["top1_correct"])),
        "interpretation": (
            "A high wrong_top1_count means RRF reduced g17 hubbing but introduced a new dominant-source risk."
        ),
    }
    return diagnostic, cases


def build_g04_wrong_top1_diagnostics(
    dominant_guideline_id: str,
    hybrid_rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    wrong_rows: list[dict[str, Any]] = []
    correct_rank_rows: list[dict[str, Any]] = []
    route_counter: Counter[tuple[str, str, str]] = Counter()
    for query_id, row in sorted(hybrid_rows.items()):
        if row.get("top1_source") != dominant_guideline_id:
            continue
        expected_sources = set(row.get("expected_guideline_ids", []))
        is_correct = dominant_guideline_id in expected_sources
        top1 = first_result(row)
        route_key = "+".join(top1.get("source_routes", [])) or "unknown"
        route_counter[(row.get("query_type", ""), str(is_correct), route_key)] += 1
        if is_correct:
            continue

        # The report keeps full expected_source_rank across candidate_k, even
        # though it stores detailed result objects only for top-k. That split is
        # intentional: this file can still tell whether the correct source was
        # present in the fused candidate pool without bloating every report.
        expected_rank = row.get("expected_source_rank")
        candidate_status = (
            "candidate_absent"
            if expected_rank in (None, "")
            else "candidate_present_below_top1"
        )
        wrong_payload = {
            "query_id": query_id,
            "query": row.get("query", ""),
            "query_type": row.get("query_type", ""),
            "primary_expected_guideline_id": row.get("primary_expected_guideline_id", ""),
            "expected_guideline_ids": "|".join(row.get("expected_guideline_ids", [])),
            "top1_source": dominant_guideline_id,
            "correct_source_candidate_status": candidate_status,
            "correct_source_final_rank": expected_rank or "",
            "top1_chunk_id": top1.get("chunk_id", ""),
            "top1_source_routes": route_key,
            "top1_vector_rank": top1.get("vector_rank", ""),
            "top1_lexical_rank": top1.get("lexical_rank", ""),
            "top1_table_lexical_rank": top1.get("table_lexical_rank", ""),
            "top1_vector_score": top1.get("vector_score", ""),
            "top1_lexical_score": top1.get("lexical_score", ""),
            "top1_rrf_score": top1.get("rrf_score", ""),
            "top5_sources": "|".join(row.get("top5_sources", [])),
            "retrieved_chunk_ids": "|".join(row.get("retrieved_chunk_ids", [])),
        }
        wrong_rows.append(wrong_payload)
        correct_rank_rows.append(
            {
                "query_id": query_id,
                "query_type": row.get("query_type", ""),
                "expected_guideline_ids": "|".join(row.get("expected_guideline_ids", [])),
                "top1_source": dominant_guideline_id,
                "correct_source_final_rank": expected_rank or "",
                "correct_source_candidate_status": candidate_status,
            }
        )
    route_rows = [
        {
            "query_type": query_type,
            "top1_correct": top1_correct,
            "source_routes": source_routes,
            "count": count,
        }
        for (query_type, top1_correct, source_routes), count in sorted(route_counter.items())
    ]
    return wrong_rows, route_rows, correct_rank_rows


def first_result(row: dict[str, Any]) -> dict[str, Any]:
    results = row.get("results") or []
    if results:
        return dict(results[0])
    return {}


def build_table_sensitive_slice(
    queries: dict[str, dict[str, Any]],
    hybrid_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query_id, row in sorted(hybrid_rows.items()):
        if not row.get("table_sensitive"):
            continue
        rows.append(
            {
                "query_id": query_id,
                "query": row.get("query", ""),
                "query_type": row.get("query_type", ""),
                "primary_expected_guideline_id": row.get("primary_expected_guideline_id", ""),
                "expected_guideline_ids": "|".join(row.get("expected_guideline_ids", [])),
                "top1_source": row.get("top1_source", ""),
                "top5_sources": "|".join(row.get("top5_sources", [])),
                "expected_source_rank": row.get("expected_source_rank"),
                "expected_source_in_top5": row.get("expected_source_in_top5"),
                "table_exposure_hit": row.get("table_exposure_hit"),
                "table_exposure_by_k": json.dumps(row.get("table_exposure_by_k", {}), ensure_ascii=False, sort_keys=True),
                "retrieved_chunk_ids": "|".join(row.get("retrieved_chunk_ids", [])),
                "failure_type": table_failure_type(row),
            }
        )
    return rows


def table_failure_type(row: dict[str, Any]) -> str:
    expected_miss = not row.get("expected_source_in_top5")
    table_miss = not row.get("table_exposure_hit")
    if expected_miss and table_miss:
        return "expected_source_and_table_exposure_miss"
    if expected_miss:
        return "expected_source_miss"
    if table_miss:
        return "table_exposure_miss"
    return ""


def first_row(rows: list[dict[str, str]], key: str, value: str) -> dict[str, str]:
    for row in rows:
        if row.get(key) == value:
            return row
    return {}


def first_matching_row(rows: list[dict[str, str]], match: dict[str, str]) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in match.items()):
            return row
    return {}


def rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4)


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
