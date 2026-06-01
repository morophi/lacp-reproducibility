"""Write a blocked report for the pre-CR E2E smoke attempt.

This helper is intentionally post-hoc and read-mostly: it does not call the
harness, inference nodes, RAG node, Chroma, or the metrics database.  Its only
network action is a short TCP reachability probe so the blocked state can be
recorded with enough evidence to distinguish an execution failure from a
retrieval-policy failure.

The report is kept as an experiment artifact because this run is explicitly a
pre-CR readiness smoke, not CR/CR2/Run B causal evidence.  The comments below
spell that out so future reruns do not accidentally treat a blocked transport
check as a model or retrieval result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from pathlib import Path


DEFAULT_ENDPOINTS = {
    "harness": ("10.1.1.110", 9000),
    "rag": ("10.1.1.120", 8000),
    "node_a": ("10.1.1.10", 11434),
    "node_b": ("10.1.1.20", 11434),
    "node_c": ("10.1.1.30", 11434),
    "db": ("10.1.1.130", 3306),
}


def sha256_file(path: Path) -> str:
    """Hash input artifacts so the blocked report identifies the exact setup."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_tcp(name: str, host: str, port: int, timeout_sec: float) -> dict:
    """Run a bounded TCP connect probe without sending application traffic."""
    started = time.time()
    status = "timeout"
    error = None
    sock = socket.socket()
    sock.settimeout(timeout_sec)
    try:
        sock.connect((host, port))
        status = "reachable"
    except Exception as exc:  # noqa: BLE001 - the report should preserve exact transport failures.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        sock.close()

    return {
        "name": name,
        "host": host,
        "port": port,
        "status": status,
        "elapsed_sec": round(time.time() - started, 3),
        "error": error,
    }


def build_report(args: argparse.Namespace) -> dict:
    """Assemble the blocked readiness report with policy and audit caveats."""
    scenario = Path(args.scenario).resolve()
    validator = Path(args.validator).resolve()
    checks = [
        probe_tcp(name, host, port, args.timeout_sec)
        for name, (host, port) in DEFAULT_ENDPOINTS.items()
    ]

    return {
        "run_id": args.run_id,
        "run_classification": "pre-CR E2E readiness smoke only; not causal evidence",
        "status": "blocked",
        "blocked_reason": (
            "Harness endpoint timed out before turn 1, so A/B/C inference, "
            "RAG injection, and metric logging could not be exercised."
        ),
        "scenario_path": str(scenario),
        "scenario_sha256": sha256_file(scenario),
        "validator_path": str(validator),
        "validator_sha256": sha256_file(validator),
        "requested_policy": {
            "embedding_text_policy": "body_only_v1",
            "candidate_generation": "vector_top30 + lexical_top30",
            "fusion": "lexical_weighted_RRF_0.7_0.3",
            "rrf_k": 60,
            "final_topK": 5,
            "sidecar_prompt_injection": False,
            "sidecar_logging_only": "optional",
            "table_source_aware_diag": "logging_only",
            "thinking": False,
            "temperature": 0.0,
        },
        "connectivity_checks": checks,
        "execution_attempt": {
            "command_summary": (
                "agent/run_scenario.py with precr_e2e_5query_scenario.json, "
                "condition=run_b, run_mode=smoke, max_turns=5, "
                f"harness_url={args.harness_url}"
            ),
            "result": "urllib.error.URLError timeout at /turn on first turn",
            "rows_produced": 0,
        },
        "readiness_checks_not_possible": [
            "A/B/C response_text nonempty",
            "thinking_present_rows=0",
            "Node C rag_injected=0",
            "A/B rag_injected=1",
            "LMS/MA/CDS metric completeness",
            "prompt_eval_count below context limit",
            "done_reason and done_reason=length check",
            "retrieved_chunk_ids/collection_name/corpus_version row audit",
            "sidecar_prompt_injection=false row audit",
        ],
        "rag_node_ingest_executed": False,
        "policy_conformity_caveat": (
            "The harness node was unreachable, so live runtime support for "
            "body_only_v1 + hybrid_union_rrf_lexical_weighted_07_03 could not "
            "be verified. Before a policy-conformant rerun, inspect the live "
            "harness/RAG config and confirm it does not fall back to the older "
            "vector-only collection path."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--validator", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--harness-url", default="http://10.1.1.110:9000")
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    args = parser.parse_args()

    report = build_report(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"output": str(output), "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
