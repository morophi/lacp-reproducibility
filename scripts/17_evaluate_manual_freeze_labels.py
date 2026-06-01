"""
Step 17: Evaluate manual retrieval-freeze labels.

This read-only evaluator consumes `manual_labeling_targets_v2.csv` after the
manual labels have been filled. It checks the pre-CR freeze gate documented in
`retrieval_policy_v1_draft.md`:

- critical_failure_count = 0
- table_sensitive_critical_failure_count = 0
- major_failure_count <= 3
- section_or_chunk_hit_rate >= 0.80
- wrong_table_insertion_count <= 1 and explainable
- expected_source_dropped_after_table_aug <= 1
- failures should not cluster in a single source or query type

The evaluator does not query ChromaDB, rebuild embeddings, ingest data, or
modify retrieval policy. It only joins manual labels with an existing Step 12
coverage report and writes a gate summary.
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
DEFAULT_LABELS = DEFAULT_LOG_DIR / "manual_labeling_targets_v2.csv"
DEFAULT_REPORT = (
    DEFAULT_LOG_DIR
    / "full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json"
)


PASS_VALUES = {"pass", "passed", "ok", "accept", "accepted", "hit", "correct"}
FAIL_VALUES = {"fail", "failed", "reject", "rejected", "miss", "incorrect"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate manual retrieval freeze labels.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-prefix", default="manual_labeling_freeze_gate_v2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    labels = read_csv(args.labels)
    report = read_json(args.report)
    report_by_query = {row["query_id"]: row for row in report.get("per_query", [])}
    detail_rows = [evaluate_row(row, report_by_query.get(row.get("query_id", ""), {})) for row in labels]
    summary = summarize(detail_rows)
    payload = {
        "step": "17_evaluate_manual_freeze_labels",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "labels": str(args.labels),
        "report": str(args.report),
        "summary": summary,
        "details": detail_rows,
    }
    write_json(args.output_dir / f"{args.output_prefix}.json", payload)
    write_csv(args.output_dir / f"{args.output_prefix}.csv", detail_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["freeze_gate_status"] == "pass" else 2


def evaluate_row(label: dict[str, str], report_row: dict[str, Any]) -> dict[str, Any]:
    query_id = label.get("query_id", "")
    expected_chunk_id = clean(label.get("expected_chunk_id"))
    expected_section = clean(label.get("expected_section"))
    expected_table_id = clean(label.get("expected_table_id"))
    expected_block_type = clean(label.get("expected_block_type"))
    judgment = normalize_judgment(label.get("manual_judgment", ""))
    retrieved = report_row.get("results", [])
    sidecar = report_row.get("supporting_evidence_candidates", [])
    retrieved_chunk_ids = [item.get("chunk_id", "") for item in retrieved]
    sidecar_chunk_ids = [item.get("chunk_id", "") for item in sidecar]
    retrieved_sections = [clean(item.get("section")) for item in retrieved]
    sidecar_sections = [clean(item.get("section")) for item in sidecar]
    retrieved_table_ids = [clean(item.get("table_id")) for item in retrieved]
    sidecar_table_ids = [clean(item.get("table_id")) for item in sidecar]
    retrieved_block_types = [clean(item.get("block_type")) for item in retrieved]
    sidecar_block_types = [clean(item.get("block_type")) for item in sidecar]

    chunk_hit = bool(expected_chunk_id and expected_chunk_id in retrieved_chunk_ids)
    sidecar_chunk_hit = bool(expected_chunk_id and expected_chunk_id in sidecar_chunk_ids)
    section_hit = bool(expected_section and any(expected_section in section for section in retrieved_sections))
    sidecar_section_hit = bool(expected_section and any(expected_section in section for section in sidecar_sections))
    table_hit = bool(expected_table_id and expected_table_id in retrieved_table_ids)
    sidecar_table_hit = bool(expected_table_id and expected_table_id in sidecar_table_ids)
    block_type_hit = bool(expected_block_type and expected_block_type in retrieved_block_types)
    sidecar_block_type_hit = bool(expected_block_type and expected_block_type in sidecar_block_types)
    source_hit = bool(report_row.get("expected_source_in_top5"))
    table_sensitive = label.get("query_type") == "table_sensitive" or bool(report_row.get("table_sensitive"))
    table_exposure_hit = bool(report_row.get("table_exposure_hit"))
    wrong_table_insertion = table_sensitive and table_exposure_hit and expected_table_id and not table_hit

    sidecar_evidence_hit = sidecar_chunk_hit or sidecar_section_hit
    combined_context_evidence_hit = chunk_hit or section_hit or sidecar_evidence_hit or judgment == "pass"
    evidence_hit = chunk_hit or section_hit or judgment == "pass"
    if expected_block_type == "table":
        evidence_hit = evidence_hit and (table_hit or block_type_hit or judgment == "pass")
        sidecar_evidence_hit = sidecar_evidence_hit and (sidecar_table_hit or sidecar_block_type_hit)
        combined_context_evidence_hit = (
            evidence_hit
            or sidecar_evidence_hit
            or judgment == "pass"
        )

    failure = judgment == "fail" or not source_hit or not combined_context_evidence_hit
    return {
        "query_id": query_id,
        "query_type": label.get("query_type", ""),
        "criticality": label.get("criticality", ""),
        "manual_judgment": label.get("manual_judgment", ""),
        "judgment_normalized": judgment or "missing",
        "label_complete": label_complete(label),
        "source_hit": source_hit,
        "section_hit": section_hit,
        "chunk_hit": chunk_hit,
        "block_type_hit": block_type_hit,
        "table_hit": table_hit,
        "sidecar_chunk_hit": sidecar_chunk_hit,
        "sidecar_section_hit": sidecar_section_hit,
        "sidecar_block_type_hit": sidecar_block_type_hit,
        "sidecar_table_hit": sidecar_table_hit,
        "sidecar_expected_evidence_hit": sidecar_evidence_hit,
        "combined_context_evidence_hit": combined_context_evidence_hit,
        "sidecar_candidate_count": len(sidecar),
        "sidecar_duplicate_count": len(set(retrieved_chunk_ids) & set(sidecar_chunk_ids)),
        "sidecar_wrong_evidence": bool(sidecar and not sidecar_evidence_hit),
        "table_sensitive": table_sensitive,
        "table_exposure_hit": table_exposure_hit,
        "wrong_table_insertion": wrong_table_insertion,
        "expected_source_dropped_after_table_aug": not source_hit,
        "evidence_hit": evidence_hit,
        "failure": failure,
        "expected_source_id": label.get("expected_source_id", ""),
        "expected_chunk_id": expected_chunk_id,
        "expected_section": expected_section,
        "expected_block_type": expected_block_type,
        "expected_table_id": expected_table_id,
        "notes": label.get("notes", ""),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    incomplete = [row for row in rows if not row["label_complete"]]
    failures = [row for row in rows if row["failure"]]
    critical_failures = [row for row in failures if row["criticality"] == "critical"]
    table_critical_failures = [
        row for row in critical_failures if row["table_sensitive"]
    ]
    major_failures = [row for row in failures if row["criticality"] == "major"]
    labeled_rows = [row for row in rows if row["label_complete"]]
    section_or_chunk_hit_rate = (
        round(sum(1 for row in labeled_rows if row["section_hit"] or row["chunk_hit"] or row["evidence_hit"]) / len(labeled_rows), 4)
        if labeled_rows
        else 0.0
    )
    wrong_table_rows = [row for row in rows if row["wrong_table_insertion"]]
    sidecar_wrong_rows = [row for row in rows if row.get("sidecar_wrong_evidence")]
    sidecar_duplicate_count = sum(int(row.get("sidecar_duplicate_count") or 0) for row in rows)
    source_drop_rows = [row for row in rows if row["expected_source_dropped_after_table_aug"]]
    cluster = cluster_summary(failures)
    pass_gate = (
        not incomplete
        and len(critical_failures) == 0
        and len(table_critical_failures) == 0
        and len(major_failures) <= 3
        and section_or_chunk_hit_rate >= 0.80
        and len(wrong_table_rows) <= 1
        and len(source_drop_rows) <= 1
        and not cluster["cluster_warning"]
    )
    return {
        "row_count": len(rows),
        "complete_label_count": len(labeled_rows),
        "incomplete_label_count": len(incomplete),
        "critical_failure_count": len(critical_failures),
        "table_sensitive_critical_failure_count": len(table_critical_failures),
        "major_failure_count": len(major_failures),
        "section_or_chunk_hit_rate": section_or_chunk_hit_rate,
        "wrong_table_insertion_count": len(wrong_table_rows),
        "sidecar_expected_evidence_hit_rate": hit_rate(labeled_rows, "sidecar_expected_evidence_hit"),
        "combined_context_evidence_hit_rate": hit_rate(labeled_rows, "combined_context_evidence_hit"),
        "sidecar_wrong_evidence_count": len(sidecar_wrong_rows),
        "sidecar_duplicate_count": sidecar_duplicate_count,
        "expected_source_dropped_after_table_aug": len(source_drop_rows),
        "failure_count": len(failures),
        "failure_cluster_summary": cluster,
        "freeze_gate_status": "pass" if pass_gate else "blocked",
        "blocked_reason": blocked_reason(
            incomplete,
            critical_failures,
            table_critical_failures,
            major_failures,
            section_or_chunk_hit_rate,
            wrong_table_rows,
            sidecar_wrong_rows,
            source_drop_rows,
            cluster,
        ),
    }


def blocked_reason(
    incomplete: list[dict[str, Any]],
    critical_failures: list[dict[str, Any]],
    table_critical_failures: list[dict[str, Any]],
    major_failures: list[dict[str, Any]],
    section_or_chunk_hit_rate: float,
    wrong_table_rows: list[dict[str, Any]],
    sidecar_wrong_rows: list[dict[str, Any]],
    source_drop_rows: list[dict[str, Any]],
    cluster: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if incomplete:
        reasons.append("manual labels are incomplete")
    if critical_failures:
        reasons.append("critical failures present")
    if table_critical_failures:
        reasons.append("table-sensitive critical failures present")
    if len(major_failures) > 3:
        reasons.append("major failure count exceeds 3")
    if section_or_chunk_hit_rate < 0.80:
        reasons.append("section_or_chunk_hit_rate below 0.80")
    if len(wrong_table_rows) > 1:
        reasons.append("wrong_table_insertion_count exceeds explainable threshold")
    if len(sidecar_wrong_rows) > 3:
        reasons.append("sidecar_wrong_evidence_count exceeds diagnostic tolerance")
    if len(source_drop_rows) > 1:
        reasons.append("expected_source_dropped_after_table_aug exceeds 1")
    if cluster["cluster_warning"]:
        reasons.append("failures cluster by source or query type")
    return reasons


def hit_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4)


def cluster_summary(failures: list[dict[str, Any]]) -> dict[str, Any]:
    if not failures:
        return {"cluster_warning": False, "by_query_type": {}, "by_source": {}}
    by_type = Counter(row["query_type"] for row in failures)
    by_source = Counter(row["expected_source_id"] for row in failures)
    dominant_type_count = max(by_type.values(), default=0)
    dominant_source_count = max(by_source.values(), default=0)
    return {
        "cluster_warning": dominant_type_count >= 3 or dominant_source_count >= 3,
        "by_query_type": dict(sorted(by_type.items())),
        "by_source": dict(sorted(by_source.items())),
    }


def label_complete(row: dict[str, str]) -> bool:
    required = ["manual_judgment", "label_confidence", "expected_block_type"]
    if any(not clean(row.get(field)) for field in required):
        return False
    if clean(row.get("expected_block_type")) == "table" and not clean(row.get("expected_table_id")):
        return False
    return bool(clean(row.get("expected_section")) or clean(row.get("expected_chunk_id")))


def normalize_judgment(value: str) -> str:
    cleaned = clean(value).lower()
    if cleaned in PASS_VALUES:
        return "pass"
    if cleaned in FAIL_VALUES:
        return "fail"
    return ""


def clean(value: Any) -> str:
    return str(value or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
