"""
Step 20: Summarize the evidence-sidecar policy decision.

This read-only script records why evidence_sidecar_v1 remains diagnostic-only:
it preserves base retrieval, but assisted section/chunk/table-level evidence
quality and prompt payload cost are not yet acceptable for CR/CR2 prompt
injection.
"""

from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_ROOT = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1")
LOG_DIR = RUN_ROOT / "logs"
SIDECAR_REPORT = LOG_DIR / "full_guideline_retrieval_coverage_body_only_v1_evidence_sidecar_v1_report.json"
SIDECAR_GATE = LOG_DIR / "manual_labeling_freeze_gate_v2_evidence_sidecar.json"
OUTPUT = LOG_DIR / "evidence_sidecar_policy_decision_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=SIDECAR_REPORT)
    parser.add_argument("--gate", type=Path, default=SIDECAR_GATE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = read_json(args.report)
    gate = read_json(args.gate)
    per_query = report.get("per_query", [])
    sidecar_char_stats = compute_sidecar_chars(per_query)
    payload = {
        "step": "20_summarize_sidecar_policy_decision",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "base_retrieval_policy_status": "pre_cr_formal_candidate",
            "evidence_sidecar_status": "diagnostic_only",
            "sidecar_logging_enabled": True,
            "sidecar_prompt_injection_enabled": False,
            "cr_cr2_default_includes_sidecar_prompt_injection": False,
        },
        "base_policy": {
            "embedding_text_policy": "body_only_v1",
            "candidate_generation": "vector_top30 + lexical_top30",
            "fusion": "lexical_weighted_RRF_0.7_0.3",
            "rrf_k": 60,
            "final_topK": 5,
        },
        "sidecar_v1_summary": {
            "retrieval_summary": report.get("summary", {}),
            "manual_gate_summary": gate.get("summary", {}),
            "prompt_payload_chars": sidecar_char_stats,
        },
        "rationale": [
            "Sidecar preserves base expected-any top5, candidate top30, and source dominance metrics.",
            "Sidecar v1 does not pass assisted section/chunk/table-level freeze gate.",
            "Sidecar v1 attaches too broadly and adds too much prompt payload for default CR/CR2 use.",
            "Sidecar should remain logging-only until a narrower v2 diagnostic passes.",
        ],
        "evidence_sidecar_v2_constraints": {
            "sidecar_max_items": 1,
            "sidecar_max_chars_per_query": "800-1000",
            "eligible_query_types": ["table_sensitive", "exception", "eligibility", "procedure"],
            "requires_base_top5_evidence_miss_risk": True,
            "requires_source_or_guideline_anchor_match": True,
            "requires_query_type_marker_match": True,
            "requires_high_confidence_score": True,
            "prompt_injection_separately_gated": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sidecar_prompt_injection_enabled": False}, ensure_ascii=False, indent=2))
    return 0


def compute_sidecar_chars(rows: list[dict[str, Any]]) -> dict[str, Any]:
    adds = []
    counts = []
    for row in rows:
        sidecar = row.get("supporting_evidence_candidates") or []
        counts.append(len(sidecar))
        adds.append(sum(len(item.get("document", "")) for item in sidecar))
    present = [value for value in adds if value]
    return {
        "query_count": len(rows),
        "sidecar_query_count": sum(1 for count in counts if count),
        "total_sidecar_items": sum(counts),
        "max_sidecar_items_per_query": max(counts, default=0),
        "avg_added_chars_all_queries": round(sum(adds) / len(adds), 2) if adds else 0.0,
        "avg_added_chars_when_present": round(sum(present) / len(present), 2) if present else 0.0,
        "max_added_chars": max(adds, default=0),
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
