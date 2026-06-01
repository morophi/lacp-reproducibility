"""
Step 15: Compare retrieval diagnostic variants for formal-readiness review.

This script is intentionally read-only. It scans Step 12 coverage report JSON
files, extracts the readiness metrics that matter for CR/CR2/Run B policy
freeze, and writes one compact CSV/JSON comparison table. It does not query
ChromaDB, ingest data, rebuild embeddings, or modify any retrieval policy.

The comparison is useful after running both route variants
(`hybrid_union_rrf_*`) and embedding-text-policy variants
(`body_only_v1`, `title_once_body_v1`). Keeping these metrics in one artifact
prevents ad hoc cherry-picking when deciding which retrieval substrate is stable
enough for formal runs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate Step 12 retrieval coverage reports into a formal-readiness comparison."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument(
        "--pattern",
        default="full_guideline_retrieval_coverage_*_report.json",
        help="Glob pattern for Step 12 report JSON files.",
    )
    parser.add_argument(
        "--output-prefix",
        default="retrieval_variant_comparison",
        help="Prefix for CSV/JSON comparison outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = sorted(args.input_dir.glob(args.pattern))
    rows = [summary_row(path) for path in reports]
    rows = [row for row in rows if row]
    rows.sort(key=lambda row: (row["collection_name"], row["retrieval_mode"], row["report_name"]))

    payload = {
        "step": "15_compare_retrieval_variants",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(args.input_dir),
        "pattern": args.pattern,
        "report_count": len(rows),
        "rows": rows,
    }
    write_json(args.output_dir / f"{args.output_prefix}.json", payload)
    write_csv(args.output_dir / f"{args.output_prefix}.csv", rows)
    print(json.dumps({"report_count": len(rows), "outputs": str(args.output_dir)}, ensure_ascii=False, indent=2))
    return 0


def summary_row(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    summary = payload.get("summary") or {}
    collection_metadata = payload.get("collection_metadata") or {}
    if not summary:
        return {}
    return {
        "report_name": path.name,
        "collection_name": summary.get("collection_name", ""),
        "corpus_version": summary.get("corpus_version", ""),
        "retrieval_mode": summary.get("retrieval_mode", ""),
        "embedding_text_policy": collection_metadata.get("embedding_text_policy", ""),
        "query_count": summary.get("query_count", 0),
        "primary_top5_hit_rate": summary.get("primary_top5_hit_rate", 0.0),
        "expected_any_top5_hit_rate": summary.get("expected_any_top5_hit_rate", 0.0),
        "expected_any_candidate_hit_rate": summary.get("expected_any_candidate_hit_rate", 0.0),
        "table_exposure_hit_rate": summary.get("table_exposure_hit_rate", 0.0),
        "dominant_top1_source": summary.get("dominant_top1_source", ""),
        "dominant_top1_ratio": summary.get("dominant_top1_ratio", 0.0),
        "dominant_top1_warning": summary.get("dominant_top1_warning", False),
        "top1_source_entropy": summary.get("top1_source_entropy", 0.0),
        "topk_source_entropy": summary.get("topk_source_entropy", 0.0),
        "zero_hit_primary_sources_top5": "|".join(summary.get("zero_hit_primary_sources_top5", [])),
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
