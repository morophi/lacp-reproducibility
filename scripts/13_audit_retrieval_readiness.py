"""
Step 13: Audit retrieval-readiness diagnostics for the full-guideline index.

This script performs Phase 0/1 analysis only. It reads the already-built corpus
manifest, local validation Chroma collection, chunking logs, and Step 12
coverage reports, then writes identity/decomposition artifacts. It does not
create embeddings, rebuild chunks, ingest into any RAG node, or change retrieval
policy. The intent is to isolate whether the current vector failure is an index
identity problem, a query-type problem, source overrepresentation, or a route
problem before testing new embedding-text policies.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BUILD_ROOT = Path("/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1")
DEFAULT_MANIFEST = (
    DEFAULT_BUILD_ROOT
    / "manifest"
    / "rag_full_guidelines_2026_20260525T_full_guideline_v1_manifest.json"
)
DEFAULT_CHROMA_PATH = DEFAULT_BUILD_ROOT / "chroma_validation"
DEFAULT_LOG_DIR = DEFAULT_BUILD_ROOT / "logs"
DEFAULT_COLLECTION_NAME = "lacp_docs_v1_full_guideline_table_safe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create Phase 0/1 retrieval-readiness audit artifacts."
    )
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--chroma-path", type=Path, default=DEFAULT_CHROMA_PATH)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument(
        "--vector-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_vector_only_report.json",
    )
    parser.add_argument(
        "--lexical-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_lexical_only_report.json",
    )
    parser.add_argument(
        "--hybrid-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_hybrid_rerank_v1_report.json",
    )
    parser.add_argument(
        "--hybrid-union-report",
        type=Path,
        default=DEFAULT_LOG_DIR / "full_guideline_retrieval_coverage_hybrid_union_rrf_v1_report.json",
    )
    parser.add_argument("--g17-guideline-id", default="g17_src_2deb381f")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_json(args.manifest)
    collection_audit = audit_collection(args.chroma_path, args.collection_name)
    chunk_policy = load_chunk_policy(args.build_root)
    manifest_compare = compare_manifest_to_collection(manifest, collection_audit, args.collection_name)

    reports = {
        "vector_only": read_json(args.vector_report),
        "lexical_only": read_json(args.lexical_report),
        "hybrid_rerank_v1": read_json(args.hybrid_report),
    }
    if args.hybrid_union_report.exists():
        reports["hybrid_union_rrf_v1"] = read_json(args.hybrid_union_report)
    query_type_metrics = build_query_type_metrics(reports)
    source_overrepresentation = build_source_overrepresentation(
        collection_audit["source_chunk_distribution"],
        reports,
    )
    g17_diagnostic = build_g17_diagnostic(
        g17_guideline_id=args.g17_guideline_id,
        collection_audit=collection_audit,
        reports=reports,
        source_overrepresentation=source_overrepresentation,
    )
    lexical_by_query_type = [
        row for row in query_type_metrics if row["retrieval_mode"] == "lexical_only"
    ]
    table_exposure = build_table_exposure_by_query_type(reports)

    index_identity = {
        "step": "13_audit_retrieval_readiness",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "phase_0_index_identity_audit",
        "collection_name": args.collection_name,
        "chroma_path": str(args.chroma_path),
        "manifest_path": str(args.manifest),
        "manifest": {
            "run_id": manifest.get("run_id"),
            "corpus_version": manifest.get("corpus_version"),
            "collection_name": manifest.get("collection_name"),
            "source_count": manifest.get("source_count"),
            "chunk_count": manifest.get("chunk_count"),
            "embedding_metadata_count": manifest.get("embedding_metadata_count"),
            "embedding_model": manifest.get("embedding_model")
            or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "embeddings_sha256": (manifest.get("artifacts") or {}).get("embeddings_sha256"),
            "chunks_sha256": (manifest.get("artifacts") or {}).get("chunks_sha256"),
            "rag_node_ingest_executed": manifest.get("rag_node_ingest_executed"),
        },
        "collection": {
            "collection_count": collection_audit["collection_count"],
            "collection_metadata": collection_audit["collection_metadata"],
            "embedding_dimension": collection_audit["embedding_dimension"],
            "metadata_corpus_versions": collection_audit["metadata_corpus_versions"],
            "embedding_text_policy": collection_audit["embedding_text_policy"],
            "source_count": len(collection_audit["source_chunk_distribution"]),
            "table_chunk_count": collection_audit["table_chunk_count"],
            "g17_chunk_count": collection_audit["source_counts"].get(args.g17_guideline_id, 0),
            "g17_chunk_share": share(
                collection_audit["source_counts"].get(args.g17_guideline_id, 0),
                collection_audit["collection_count"],
            ),
        },
        "chunking_policy": chunk_policy,
        "identity_checks": manifest_compare,
    }

    write_json(args.output_dir / "index_identity_report.json", index_identity)
    write_csv(args.output_dir / "source_chunk_distribution.csv", collection_audit["source_chunk_distribution"])
    write_csv(args.output_dir / "collection_manifest_compare.csv", manifest_compare)
    write_csv(args.output_dir / "query_type_metrics.csv", query_type_metrics)
    write_csv(args.output_dir / "source_overrepresentation.csv", source_overrepresentation)
    write_json(args.output_dir / "g17_diagnostic.json", g17_diagnostic)
    write_csv(args.output_dir / "lexical_by_query_type.csv", lexical_by_query_type)
    write_csv(args.output_dir / "table_exposure_by_query_type.csv", table_exposure)

    print(
        json.dumps(
            {
                "index_identity": {
                    "collection_count": collection_audit["collection_count"],
                    "manifest_chunk_count": manifest.get("chunk_count"),
                    "embedding_dimension": collection_audit["embedding_dimension"],
                    "table_chunk_count": collection_audit["table_chunk_count"],
                    "g17_chunk_share": index_identity["collection"]["g17_chunk_share"],
                    "metadata_corpus_versions": collection_audit["metadata_corpus_versions"],
                },
                "g17": g17_diagnostic["summary"],
                "outputs": [
                    "index_identity_report.json",
                    "source_chunk_distribution.csv",
                    "collection_manifest_compare.csv",
                    "query_type_metrics.csv",
                    "source_overrepresentation.csv",
                    "g17_diagnostic.json",
                    "lexical_by_query_type.csv",
                    "table_exposure_by_query_type.csv",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def audit_collection(chroma_path: Path, collection_name: str) -> dict[str, Any]:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("chromadb is required for collection audit.") from exc

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_collection(collection_name)
    collection_count = collection.count()
    source_counts: Counter[str] = Counter()
    block_type_counts: Counter[str] = Counter()
    corpus_versions: Counter[str] = Counter()
    table_chunk_count = 0
    first_document = ""
    first_embedding_dimension: int | None = None

    batch_size = 1000
    for offset in range(0, collection_count, batch_size):
        response = collection.get(
            include=["documents", "metadatas", "embeddings"],
            limit=batch_size,
            offset=offset,
        )
        docs = response.get("documents", []) or []
        metadatas = response.get("metadatas", []) or []
        embeddings = response.get("embeddings", [])
        if first_document == "" and docs:
            first_document = docs[0]
        if first_embedding_dimension is None and embeddings is not None and len(embeddings):
            first_embedding_dimension = len(embeddings[0])
        for metadata in metadatas:
            guideline_id = str(metadata.get("guideline_id") or "unknown")
            block_type = str(metadata.get("block_type") or "unknown")
            source_counts[guideline_id] += 1
            block_type_counts[block_type] += 1
            corpus_versions[str(metadata.get("corpus_version") or "unknown")] += 1
            if block_type == "table" or metadata.get("table_id"):
                table_chunk_count += 1

    source_distribution = [
        {
            "guideline_id": guideline_id,
            "source_chunk_count": count,
            "corpus_chunk_share": share(count, collection_count),
        }
        for guideline_id, count in sorted(source_counts.items())
    ]
    return {
        "collection_count": collection_count,
        "collection_metadata": collection.metadata or {},
        "embedding_dimension": first_embedding_dimension,
        "source_counts": dict(source_counts),
        "source_chunk_distribution": source_distribution,
        "block_type_counts": dict(sorted(block_type_counts.items())),
        "table_chunk_count": table_chunk_count,
        "metadata_corpus_versions": dict(sorted(corpus_versions.items())),
        "embedding_text_policy": infer_embedding_text_policy(first_document),
    }


def infer_embedding_text_policy(first_document: str) -> str:
    # This intentionally infers only what is observable from stored Chroma
    # documents. If source boundary markers are present in the retrieved document
    # text, the current index is "original_with_source_boundary"; later body-only
    # variants should make this check flip to a body/title policy string.
    if first_document.startswith("[LACP_SOURCE_BOUNDARY]"):
        return "original_with_source_boundary"
    if "[LACP_SOURCE_BOUNDARY]" in first_document[:500]:
        return "original_boundary_near_head"
    return "unknown_or_body_only"


def load_chunk_policy(build_root: Path) -> dict[str, Any]:
    logs_dir = build_root / "logs"
    for path in sorted(logs_dir.glob("*_chunking.json")):
        payload = read_json(path)
        policy = payload.get("policy")
        if policy:
            return {
                "policy_source_log": str(path),
                **policy,
            }
    return {"policy_source_log": "", "status": "not_found"}


def compare_manifest_to_collection(
    manifest: dict[str, Any],
    collection_audit: dict[str, Any],
    collection_name: str,
) -> list[dict[str, Any]]:
    manifest_collection = manifest.get("collection_name")
    manifest_chunk_count = manifest.get("chunk_count")
    collection_count = collection_audit["collection_count"]
    metadata_versions = collection_audit["metadata_corpus_versions"]
    manifest_version = manifest.get("corpus_version")
    collection_metadata_version = (collection_audit.get("collection_metadata") or {}).get("corpus_version")
    return [
        compare_row("collection_name", manifest_collection, collection_name),
        compare_row("chunk_count", manifest_chunk_count, collection_count),
        compare_row("collection_metadata_corpus_version", manifest_version, collection_metadata_version),
        compare_row("corpus_version_present_in_metadata", True, manifest_version in metadata_versions),
        compare_row("single_metadata_corpus_version", True, len(metadata_versions) == 1),
        compare_row("rag_node_ingest_executed", False, manifest.get("rag_node_ingest_executed")),
        compare_row("source_count", manifest.get("source_count"), len(collection_audit["source_chunk_distribution"])),
    ]


def compare_row(field: str, expected: Any, observed: Any) -> dict[str, Any]:
    return {
        "field": field,
        "expected": json.dumps(expected, ensure_ascii=False, sort_keys=True),
        "observed": json.dumps(observed, ensure_ascii=False, sort_keys=True),
        "match": expected == observed,
    }


def build_query_type_metrics(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode, report in reports.items():
        per_query = report.get("per_query", [])
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in per_query:
            grouped[str(row.get("query_type", "unknown"))].append(row)
        for query_type, group in sorted(grouped.items()):
            rows.append(
                {
                    "retrieval_mode": mode,
                    "query_type": query_type,
                    "query_count": len(group),
                    "primary_top1_hit_rate": hit_rate(group, "primary_source_in_top1"),
                    "primary_top3_hit_rate": hit_rate(group, "primary_source_in_top3"),
                    "primary_top5_hit_rate": hit_rate(group, "primary_source_in_top5"),
                    "expected_any_top1_hit_rate": hit_rate(group, "expected_source_in_top1"),
                    "expected_any_top3_hit_rate": hit_rate(group, "expected_source_in_top3"),
                    "expected_any_top5_hit_rate": hit_rate(group, "expected_source_in_top5"),
                    "expected_any_candidate_hit_rate": hit_rate(group, "expected_source_in_candidate_k"),
                    "must_include_pass_rate": hit_rate(group, "must_include_pass"),
                    "avg_must_include_hit_rate": average(row.get("must_include_hit_rate", 0.0) for row in group),
                    "table_sensitive_count": sum(1 for row in group if row.get("table_sensitive")),
                    "table_exposure_hit_rate": table_hit_rate(group),
                }
            )
    return rows


def build_source_overrepresentation(
    source_distribution: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    chunk_share = {
        row["guideline_id"]: float(row["corpus_chunk_share"])
        for row in source_distribution
    }
    rows: list[dict[str, Any]] = []
    for mode, report in reports.items():
        per_query = report.get("per_query", [])
        query_count = len(per_query)
        top1_counter: Counter[str] = Counter()
        top5_counter: Counter[str] = Counter()
        top30_counter: Counter[str] = Counter()
        for row in per_query:
            if row.get("top1_source"):
                top1_counter[str(row["top1_source"])] += 1
            top5_counter.update(str(source) for source in row.get("top5_sources", []))
            top30_counter.update(parse_guideline_id(chunk_id) for chunk_id in row.get("candidate_chunk_ids", []))
        all_sources = sorted(set(chunk_share) | set(top1_counter) | set(top5_counter) | set(top30_counter))
        for source in all_sources:
            rows.append(
                {
                    "retrieval_mode": mode,
                    "guideline_id": source,
                    "corpus_chunk_share": chunk_share.get(source, 0.0),
                    "top1_count": top1_counter.get(source, 0),
                    "top1_share": share(top1_counter.get(source, 0), query_count),
                    "top1_overrepresentation_ratio": overrepresentation(
                        share(top1_counter.get(source, 0), query_count),
                        chunk_share.get(source, 0.0),
                    ),
                    "top5_count": top5_counter.get(source, 0),
                    "top5_share": share(top5_counter.get(source, 0), query_count * 5),
                    "top5_overrepresentation_ratio": overrepresentation(
                        share(top5_counter.get(source, 0), query_count * 5),
                        chunk_share.get(source, 0.0),
                    ),
                    "top30_count": top30_counter.get(source, 0),
                    "top30_share": share(top30_counter.get(source, 0), query_count * 30),
                    "top30_overrepresentation_ratio": overrepresentation(
                        share(top30_counter.get(source, 0), query_count * 30),
                        chunk_share.get(source, 0.0),
                    ),
                }
            )
    return rows


def build_g17_diagnostic(
    g17_guideline_id: str,
    collection_audit: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    source_overrepresentation: list[dict[str, Any]],
) -> dict[str, Any]:
    by_mode = {}
    for mode, report in reports.items():
        per_query = report.get("per_query", [])
        by_query_type: dict[str, dict[str, Any]] = {}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in per_query:
            grouped[str(row.get("query_type", "unknown"))].append(row)
        for query_type, group in sorted(grouped.items()):
            by_query_type[query_type] = {
                "query_count": len(group),
                "g17_top1_count": sum(1 for row in group if row.get("top1_source") == g17_guideline_id),
                "g17_top1_share": share(
                    sum(1 for row in group if row.get("top1_source") == g17_guideline_id),
                    len(group),
                ),
                "g17_top5_count": sum(
                    1 for row in group if g17_guideline_id in set(row.get("top5_sources", []))
                ),
                "g17_top5_query_share": share(
                    sum(1 for row in group if g17_guideline_id in set(row.get("top5_sources", []))),
                    len(group),
                ),
                "g17_top30_count": sum(
                    1
                    for row in group
                    if g17_guideline_id in {parse_guideline_id(cid) for cid in row.get("candidate_chunk_ids", [])}
                ),
                "g17_top30_query_share": share(
                    sum(
                        1
                        for row in group
                        if g17_guideline_id
                        in {parse_guideline_id(cid) for cid in row.get("candidate_chunk_ids", [])}
                    ),
                    len(group),
                ),
            }
        overrep_row = next(
            (
                row
                for row in source_overrepresentation
                if row["retrieval_mode"] == mode and row["guideline_id"] == g17_guideline_id
            ),
            {},
        )
        by_mode[mode] = {
            "overrepresentation": overrep_row,
            "by_query_type": by_query_type,
        }
    source_count = collection_audit["source_counts"].get(g17_guideline_id, 0)
    collection_count = collection_audit["collection_count"]
    return {
        "guideline_id": g17_guideline_id,
        "summary": {
            "g17_chunk_count": source_count,
            "g17_chunk_share": share(source_count, collection_count),
            "interpretation": (
                "High vector-only overrepresentation supports a semantic-hub hypothesis "
                "only if retrieval share greatly exceeds corpus chunk share across query types."
            ),
        },
        "by_mode": by_mode,
    }


def build_table_exposure_by_query_type(reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode, report in reports.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in report.get("per_query", []):
            grouped[str(row.get("query_type", "unknown"))].append(row)
        for query_type, group in sorted(grouped.items()):
            table_group = [row for row in group if row.get("table_sensitive")]
            rows.append(
                {
                    "retrieval_mode": mode,
                    "query_type": query_type,
                    "query_count": len(group),
                    "table_sensitive_query_count": len(table_group),
                    "table_exposure_hit_rate": table_hit_rate(table_group) if table_group else "",
                    "table_exposure_hit_count": sum(1 for row in table_group if row.get("table_exposure_hit")),
                }
            )
    return rows


def parse_guideline_id(chunk_id: str) -> str:
    parts = str(chunk_id).split("__")
    return parts[1] if len(parts) >= 3 else "unknown"


def hit_rate(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4) if rows else 0.0


def table_hit_rate(rows: list[dict[str, Any]]) -> float:
    table_rows = [row for row in rows if row.get("table_sensitive")]
    return hit_rate(table_rows, "table_exposure_hit") if table_rows else 1.0


def average(values: Iterable[float]) -> float:
    values = list(values)
    return round(sum(float(value) for value in values) / len(values), 4) if values else 0.0


def share(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def overrepresentation(retrieval_share: float, chunk_share: float) -> float | None:
    if chunk_share <= 0:
        return None
    return round(retrieval_share / chunk_share, 4)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
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
