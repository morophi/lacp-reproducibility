"""
Step 12: Validate full-guideline retrieval coverage without mutating ChromaDB.

This script is a diagnostic harness, not a retrieval policy change. It reads a
local validation Chroma collection, evaluates source coverage against a curated
query set, and writes JSON/CSV reports that can be reviewed before any causal
run. It deliberately does not ingest chunks, rebuild embeddings, or write to the
RAG node active collection.

Design notes:
    - Expected sources are allowed to be plural because welfare guideline topics
      often overlap across documents. Metrics therefore distinguish primary
      source hits from "any acceptable expected source" hits.
    - Source dominance is normalized against corpus chunk share. A source with
      many chunks can appear often naturally, so the report includes
      overrepresentation_ratio = retrieval_share / corpus_chunk_share.
    - Table-sensitive queries are evaluated separately for table exposure. This
      prevents table coverage failures from being hidden inside aggregate source
      hit rates.
    - Vector top-N candidates are retained for diagnosis. If the expected source
      appears in top 30 but not top 5, reranking may help; if it is absent from
      top 30, the issue is more likely embedding text, chunking, or query design.
    - `hybrid_union_rrf_v1` and its weighted/source-cap/table-fallback variants
      are diagnostic routes. They help isolate whether failures come from
      vector recall, lexical dominance, source dominance, or missing table
      exposure. None of these modes becomes formal policy unless separately
      frozen in retrieval_policy_v1.md.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")
DEFAULT_QUERY_FILE = (
    Path(__file__).resolve().parents[1]
    / "validation_queries"
    / "full_guideline_coverage_queries_v1.jsonl"
)


@dataclass(frozen=True)
class CoverageQuery:
    query_id: str
    query: str
    primary_expected_guideline_id: str
    expected_guideline_ids: tuple[str, ...]
    expected_section_keywords: tuple[str, ...]
    must_include: tuple[str, ...]
    query_type: str
    table_sensitive: bool


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
        description="Evaluate source-level retrieval coverage for the full guideline corpus."
    )
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--chroma-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--report-prefix", default="full_guideline_retrieval_coverage")
    parser.add_argument(
        "--top-k-values",
        default="1,3,5",
        help="Comma-separated top-k checkpoints used for hit-rate metrics.",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=30,
        help="Vector candidates retained to diagnose reranking-vs-embedding failures.",
    )
    parser.add_argument("--head-chars", type=int, default=180)
    parser.add_argument("--must-include-threshold", type=float, default=0.7)
    parser.add_argument("--dominant-source-warning-ratio", type=float, default=0.30)
    parser.add_argument(
        "--retrieval-mode",
        choices=(
            "vector_only",
            "lexical_only",
            "hybrid_rerank_v1",
            "hybrid_union_rrf_v1",
            "hybrid_union_rrf_lexical_weighted_07_03",
            "hybrid_union_rrf_lexical_weighted_08_02",
            "hybrid_union_rrf_source_cap_diag",
            "hybrid_union_rrf_table_fallback_diag",
            "hybrid_union_rrf_table_source_aware_diag",
            "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_localization_v1",
            "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_sidecar_v1",
        ),
        default="vector_only",
        help="Diagnostic retrieval condition. These modes are validation-only unless separately versioned as policy.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    collection_name = args.collection_name or config.COLLECTION_NAME
    chroma_path = args.chroma_path or config.CHROMADB_PATH
    output_dir = args.output_dir or config.DIRS.logs
    top_k_values = parse_top_k_values(args.top_k_values)
    max_top_k = max(top_k_values)
    candidate_k = max(args.candidate_k, max_top_k)

    queries = load_queries(args.queries)
    collection_count, collection_metadata, per_query, source_distribution = evaluate_collection(
        config=config,
        chroma_path=chroma_path,
        collection_name=collection_name,
        queries=queries,
        top_k_values=top_k_values,
        candidate_k=candidate_k,
        head_chars=args.head_chars,
        must_include_threshold=args.must_include_threshold,
        retrieval_mode=args.retrieval_mode,
    )
    effective_corpus_version = str(collection_metadata.get("corpus_version") or config.CORPUS_VERSION)
    summary = summarize(
        collection_name=collection_name,
        corpus_version=effective_corpus_version,
        collection_count=collection_count,
        queries=queries,
        per_query=per_query,
        source_distribution=source_distribution,
        top_k_values=top_k_values,
        dominant_source_warning_ratio=args.dominant_source_warning_ratio,
        retrieval_mode=args.retrieval_mode,
    )
    failures = build_failures(per_query)
    payload = {
        "step": "12_validate_retrieval_coverage",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "query_file": str(args.queries),
        "collection_metadata": collection_metadata,
        "summary": summary,
        "per_query": per_query,
        "source_distribution": source_distribution,
    }
    write_outputs(output_dir, args.report_prefix, payload, per_query, failures, source_distribution)
    print(json.dumps({"summary": summary, "failure_count": len(failures)}, ensure_ascii=False, indent=2))
    return 0


def parse_top_k_values(value: str) -> tuple[int, ...]:
    parsed = tuple(sorted({int(part.strip()) for part in value.split(",") if part.strip()}))
    if not parsed or min(parsed) <= 0:
        raise ValueError("--top-k-values must contain positive integers.")
    return parsed


def load_queries(path: Path) -> list[CoverageQuery]:
    if not path.exists():
        raise FileNotFoundError(path)
    queries: list[CoverageQuery] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            expected = tuple(row.get("expected_guideline_ids") or [])
            primary = str(row["primary_expected_guideline_id"])
            if primary not in expected:
                expected = (primary, *expected)
            queries.append(
                CoverageQuery(
                    query_id=str(row["query_id"]),
                    query=str(row["query"]),
                    primary_expected_guideline_id=primary,
                    expected_guideline_ids=tuple(dict.fromkeys(expected)),
                    expected_section_keywords=tuple(row.get("expected_section_keywords") or []),
                    must_include=tuple(row.get("must_include") or []),
                    query_type=str(row.get("query_type") or "unspecified"),
                    table_sensitive=bool(row.get("table_sensitive")),
                )
            )
    if not queries:
        raise ValueError(f"No validation queries loaded from {path}")
    return queries


def evaluate_collection(
    config: Any,
    chroma_path: Path,
    collection_name: str,
    queries: list[CoverageQuery],
    top_k_values: tuple[int, ...],
    candidate_k: int,
    head_chars: int,
    must_include_threshold: float,
    retrieval_mode: str,
) -> tuple[int, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("chromadb and sentence-transformers are required.") from exc

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_collection(collection_name)
    collection_count = collection.count()
    collection_metadata = collection.metadata or {}
    needs_lexical_corpus = retrieval_mode != "vector_only" and retrieval_mode != "hybrid_rerank_v1"
    source_chunk_counts, lexical_corpus = load_collection_inventory(
        collection,
        collection_count,
        include_documents=needs_lexical_corpus,
        head_chars=head_chars,
    )

    model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    vectors = model.encode(
        [query.query for query in queries],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    details: list[dict[str, Any]] = []
    top1_counter: Counter[str] = Counter()
    topk_counter: Counter[str] = Counter()
    query_type_counter: Counter[str] = Counter()
    max_top_k = max(top_k_values)

    for query, vector in zip(queries, vectors):
        response = None
        vector_items: list[dict[str, Any]] = []
        if retrieval_mode != "lexical_only":
            response = collection.query(
                query_embeddings=[vector.astype("float32").tolist()],
                n_results=candidate_k,
                include=["documents", "metadatas", "distances"],
            )
            vector_items = response_items(response, head_chars)

        if retrieval_mode == "lexical_only":
            items = lexical_search(query, lexical_corpus, candidate_k)
        elif retrieval_mode == "hybrid_rerank_v1":
            items = hybrid_rerank(query, vector_items)
        elif retrieval_mode.startswith("hybrid_union_rrf") or retrieval_mode in {
            "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_localization_v1",
            "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_sidecar_v1",
        }:
            lexical_items = lexical_search(query, lexical_corpus, candidate_k)
            table_items: list[dict[str, Any]] = []
            if retrieval_mode == "hybrid_union_rrf_table_fallback_diag" and query.table_sensitive:
                table_items = table_lexical_search(query, lexical_corpus, 20)
            elif retrieval_mode == "hybrid_union_rrf_table_source_aware_diag" and query.table_sensitive:
                preliminary = hybrid_union_rrf(
                    query=query,
                    vector_items=vector_items,
                    lexical_items=lexical_items,
                    candidate_k=candidate_k,
                    retrieval_mode="hybrid_union_rrf_lexical_weighted_07_03",
                )
                allowed_sources = {item["guideline_id"] for item in preliminary[:5]}
                table_items = table_lexical_search(
                    query,
                    lexical_corpus,
                    20,
                    allowed_sources=allowed_sources,
                )
            base_mode = (
                "hybrid_union_rrf_lexical_weighted_07_03"
                if retrieval_mode in {
                    "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_localization_v1",
                    "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_sidecar_v1",
                }
                else retrieval_mode
            )
            items = hybrid_union_rrf(
                query=query,
                vector_items=vector_items,
                lexical_items=lexical_items,
                candidate_k=candidate_k,
                retrieval_mode=base_mode,
                table_items=table_items,
            )
            if retrieval_mode == "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_localization_v1":
                localized = evidence_localization_candidates(
                    query=query,
                    base_items=items,
                    lexical_corpus=lexical_corpus,
                    candidate_k=candidate_k,
                )
                items = apply_evidence_localization(
                    base_items=items,
                    localized_items=localized,
                    candidate_k=candidate_k,
                )
            sidecar_items: list[dict[str, Any]] = []
            if retrieval_mode == "body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_evidence_sidecar_v1":
                sidecar_items = evidence_sidecar_candidates(
                    query=query,
                    base_items=items,
                    lexical_corpus=lexical_corpus,
                    max_items=2,
                )
        else:
            items = vector_items
            sidecar_items = []
        top_sources = [item["guideline_id"] for item in items[:max_top_k]]
        if top_sources:
            top1_counter[top_sources[0]] += 1
        topk_counter.update(top_sources)
        query_type_counter[query.query_type] += 1

        primary_rank = first_rank(items, {query.primary_expected_guideline_id})
        any_expected_rank = first_rank(items, set(query.expected_guideline_ids))
        section_hit_rate = term_hit_rate(query.expected_section_keywords, joined_documents(items[:max_top_k]))
        must_include_hit_rate = term_hit_rate(query.must_include, joined_documents(items[:max_top_k]))
        table_exposure_by_k = {
            f"top{k}": any(item["block_type"] == "table" or bool(item["table_id"]) for item in items[:k])
            for k in top_k_values
        }
        topk_source_counts = dict(sorted(Counter(top_sources).items()))
        detail = {
            "query_id": query.query_id,
            "query": query.query,
            "query_type": query.query_type,
            "retrieval_mode": retrieval_mode,
            "primary_expected_guideline_id": query.primary_expected_guideline_id,
            "expected_guideline_ids": list(query.expected_guideline_ids),
            "primary_source_rank": primary_rank,
            "expected_source_rank": any_expected_rank,
            "primary_source_in_top1": rank_within(primary_rank, 1),
            "expected_source_in_top1": rank_within(any_expected_rank, 1),
            "primary_source_in_top3": rank_within(primary_rank, 3),
            "expected_source_in_top3": rank_within(any_expected_rank, 3),
            "primary_source_in_top5": rank_within(primary_rank, 5),
            "expected_source_in_top5": rank_within(any_expected_rank, 5),
            "expected_source_in_candidate_k": rank_within(any_expected_rank, candidate_k),
            "must_include_terms": list(query.must_include),
            "must_include_hit_rate": must_include_hit_rate,
            "must_include_pass": must_include_hit_rate >= must_include_threshold,
            "expected_section_keywords": list(query.expected_section_keywords),
            "expected_section_hit_rate": section_hit_rate,
            "table_sensitive": query.table_sensitive,
            "table_exposure_by_k": table_exposure_by_k,
            "table_exposure_hit": (not query.table_sensitive) or table_exposure_by_k.get("top5", False),
            "top1_source": top_sources[0] if top_sources else "",
            "top5_sources": top_sources[:5],
            "topk_source_distribution": topk_source_counts,
            "topk_source_entropy": entropy(topk_source_counts.values()),
            "retrieved_chunk_ids": [item["chunk_id"] for item in items[:max_top_k]],
            "candidate_chunk_ids": [item["chunk_id"] for item in items],
            "results": items[:max_top_k],
            "supporting_evidence_candidates": sidecar_items,
            "sidecar_added_to_prompt": False,
            "sidecar_reason": (
                "diagnostic_only_base_top5_preserved"
                if sidecar_items
                else "no_sidecar_candidate"
            ),
            "prompt_context_policy_version": "base_top5_plus_optional_sidecar_v1",
        }
        details.append(detail)

    source_distribution = build_source_distribution(
        source_chunk_counts=source_chunk_counts,
        top1_counter=top1_counter,
        topk_counter=topk_counter,
        query_count=len(queries),
        topk_total=len(queries) * max_top_k,
    )
    return collection_count, collection_metadata, details, source_distribution


def load_collection_inventory(
    collection: Any,
    collection_count: int,
    include_documents: bool,
    head_chars: int,
) -> tuple[Counter[str], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    lexical_corpus: list[dict[str, Any]] = []
    batch_size = 1000
    include = ["metadatas", "documents"] if include_documents else ["metadatas"]
    for offset in range(0, collection_count, batch_size):
        response = collection.get(
            include=include,
            limit=batch_size,
            offset=offset,
        )
        metadatas = response.get("metadatas", []) or []
        documents = response.get("documents", []) or []
        for idx, metadata in enumerate(metadatas):
            guideline_id = str(metadata.get("guideline_id") or "unknown")
            counts[guideline_id] += 1
            if include_documents:
                doc = documents[idx] if idx < len(documents) else ""
                lexical_corpus.append(item_from_document_metadata(doc, metadata, head_chars, rank=0))
    return counts, lexical_corpus


def response_items(response: dict[str, Any], head_chars: int) -> list[dict[str, Any]]:
    docs = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]
    items: list[dict[str, Any]] = []
    for idx, (doc, metadata) in enumerate(zip(docs, metadatas)):
        item = item_from_document_metadata(doc, metadata, head_chars, rank=idx + 1)
        item["distance"] = distances[idx] if idx < len(distances) else None
        items.append(item)
    return items


def item_from_document_metadata(
    document: str,
    metadata: dict[str, Any],
    head_chars: int,
    rank: int,
) -> dict[str, Any]:
    guideline_id = str(metadata.get("guideline_id") or parse_guideline_id(str(metadata.get("chunk_id", ""))))
    return {
        "rank": rank,
        "chunk_id": str(metadata.get("chunk_id", "")),
        "guideline_id": guideline_id,
        "guideline_title": str(metadata.get("guideline_title", "")),
        "block_type": str(metadata.get("block_type", "")),
        "table_id": str(metadata.get("table_id", "")),
        "table_title": str(metadata.get("table_title", "")),
        "section": str(metadata.get("section", "")),
        "chunk_chars": int(metadata.get("chunk_chars", len(document))),
        "distance": None,
        "text_head": document[:head_chars],
        "document": document,
    }


def lexical_search(
    query: CoverageQuery,
    lexical_corpus: list[dict[str, Any]],
    candidate_k: int,
) -> list[dict[str, Any]]:
    # This is intentionally simple and transparent: it is a diagnostic baseline
    # for term coverage, not a proposed production BM25 replacement. Scores come
    # from query-term overlap across body text plus lightweight metadata fields.
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in lexical_corpus:
        score = lexical_score(query, item)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
    results: list[dict[str, Any]] = []
    for rank, (score, item) in enumerate(scored[:candidate_k], start=1):
        copied = dict(item)
        copied["rank"] = rank
        copied["lexical_score"] = round(score, 4)
        results.append(copied)
    return results


def table_lexical_search(
    query: CoverageQuery,
    lexical_corpus: list[dict[str, Any]],
    candidate_k: int,
    allowed_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    # Table fallback is kept as a diagnostic-only route. It deliberately looks
    # only at chunks already marked as table material, then records that route
    # separately so formal policy review can decide whether table-sensitive
    # questions deserve a dedicated candidate generator.
    table_corpus = [
        item
        for item in lexical_corpus
        if item.get("block_type") == "table" or bool(item.get("table_id"))
    ]
    if allowed_sources is not None:
        # Source-aware table fallback is deliberately conservative. It can only
        # add table candidates from sources that already surfaced in the normal
        # vector+lexical top-5 pool, so it tests table exposure without allowing
        # unrelated table-heavy documents to hijack the retrieval result.
        table_corpus = [item for item in table_corpus if item.get("guideline_id") in allowed_sources]
    results = lexical_search(query, table_corpus, candidate_k)
    for item in results:
        item["table_lexical_rank"] = int(item["rank"])
    return results


def evidence_localization_candidates(
    query: CoverageQuery,
    base_items: list[dict[str, Any]],
    lexical_corpus: list[dict[str, Any]],
    candidate_k: int,
    max_anchor_sources: int = 3,
) -> list[dict[str, Any]]:
    # Evidence localization is intentionally within-source. It is designed for
    # cases where top-k already found plausible guideline sources but missed the
    # exact section/table/chunk. It must not introduce a new global retrieval
    # policy or pull evidence from unrelated sources.
    anchor_sources = []
    for item in base_items[:10]:
        guideline_id = item.get("guideline_id")
        if guideline_id and guideline_id not in anchor_sources:
            anchor_sources.append(guideline_id)
        if len(anchor_sources) >= max_anchor_sources:
            break
    anchor_set = set(anchor_sources)
    scoped = [item for item in lexical_corpus if item.get("guideline_id") in anchor_set]
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in scoped:
        score = evidence_score(query, item)
        if score <= 0:
            continue
        copied = dict(item)
        copied["evidence_localization_score"] = round(score, 4)
        copied["source_routes"] = sorted(set(copied.get("source_routes", [])) | {"evidence_localization"})
        scored.append((score, copied))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
    results: list[dict[str, Any]] = []
    for rank, (_, item) in enumerate(scored[:candidate_k], start=1):
        item["evidence_localization_rank"] = rank
        results.append(item)
    return results


def evidence_sidecar_candidates(
    query: CoverageQuery,
    base_items: list[dict[str, Any]],
    lexical_corpus: list[dict[str, Any]],
    max_items: int,
    within_source_top_n: int = 5,
) -> list[dict[str, Any]]:
    # Sidecar evidence is not a replacement for base retrieval. It is a
    # diagnostic support layer for high-risk query types where source-level
    # retrieval is acceptable but section/chunk/table evidence may be missing.
    # The base final top5 remains unchanged; sidecar candidates are separately
    # logged so prompt inclusion can be gated later.
    if query.query_type not in {"table_sensitive", "exception", "eligibility", "procedure"}:
        return []
    base_ids = {item.get("chunk_id") for item in base_items[:5]}
    localized = evidence_localization_candidates(
        query=query,
        base_items=base_items,
        lexical_corpus=lexical_corpus,
        candidate_k=within_source_top_n,
    )
    sidecar: list[dict[str, Any]] = []
    for item in localized:
        if len(sidecar) >= max_items:
            break
        if item.get("chunk_id") in base_ids:
            continue
        score = float(item.get("evidence_localization_score") or 0.0)
        threshold = sidecar_threshold(query.query_type)
        if score < threshold:
            continue
        copied = dict(item)
        copied["sidecar_rank"] = len(sidecar) + 1
        copied["sidecar_score_threshold"] = threshold
        copied["sidecar_reason"] = f"{query.query_type}_within_anchor_source_evidence"
        copied["sidecar_added_to_prompt"] = False
        sidecar.append(copied)
    return sidecar


def sidecar_threshold(query_type: str) -> float:
    if query_type == "table_sensitive":
        return 5.0
    if query_type in {"eligibility", "exception", "procedure"}:
        return 4.0
    return 10**9


def evidence_score(query: CoverageQuery, item: dict[str, Any]) -> float:
    text = compact(
        "\n".join(
            [
                item.get("document", ""),
                item.get("section", ""),
                item.get("table_title", ""),
                item.get("guideline_title", ""),
            ]
        )
    )
    score = lexical_score(query, item)
    qtype = query.query_type
    if qtype == "table_sensitive":
        if item.get("block_type") == "table" or item.get("table_id"):
            score += 4.0
        score += keyword_bonus(text, ["표", "기준", "금액", "단위", "구분", "지원", "대상"])
    elif qtype == "exception":
        score += keyword_bonus(text, ["예외", "제외", "불가", "중지", "환수", "감액", "단서", "제한"])
    elif qtype == "eligibility":
        score += keyword_bonus(text, ["지원대상", "선정기준", "소득", "재산", "연령", "가구", "장애", "수급권자"])
    elif qtype == "procedure":
        score += keyword_bonus(text, ["신청", "접수", "조사", "결정", "통보", "지급", "처리", "절차", "서류"])
    return score


def keyword_bonus(text: str, keywords: list[str]) -> float:
    return sum(0.8 for keyword in keywords if compact(keyword) in text)


def apply_evidence_localization(
    base_items: list[dict[str, Any]],
    localized_items: list[dict[str, Any]],
    candidate_k: int,
    preserve_top_n: int = 3,
    final_top_k: int = 5,
    min_evidence_score: float = 3.0,
) -> list[dict[str, Any]]:
    # Keep base top3 untouched. Localized evidence can only fill or replace
    # ranks 4-5 when it passes a transparent score threshold. This conservative
    # placement tests evidence localization without letting it hijack source
    # ranking.
    selected: list[dict[str, Any]] = [dict(item) for item in base_items[:preserve_top_n]]
    selected_ids = {item.get("chunk_id") for item in selected}
    tail_base = [dict(item) for item in base_items[preserve_top_n:final_top_k]]
    localized_pool = [
        dict(item)
        for item in localized_items
        if item.get("chunk_id") not in selected_ids
        and float(item.get("evidence_localization_score") or 0.0) >= min_evidence_score
    ]
    localized_pool = localized_pool[: max(final_top_k - preserve_top_n, 0)]
    for item in localized_pool:
        selected.append(item)
        selected_ids.add(item.get("chunk_id"))
    for item in tail_base:
        if len(selected) >= final_top_k:
            break
        if item.get("chunk_id") not in selected_ids:
            selected.append(item)
            selected_ids.add(item.get("chunk_id"))
    for item in base_items[final_top_k:]:
        if len(selected) >= candidate_k:
            break
        if item.get("chunk_id") not in selected_ids:
            selected.append(dict(item))
            selected_ids.add(item.get("chunk_id"))
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
        item["evidence_localization_applied"] = "evidence_localization" in set(item.get("source_routes", []))
    return selected[:candidate_k]


def hybrid_rerank(query: CoverageQuery, vector_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Hybrid rerank is validation-only. It tests whether broad vector candidates
    # already contain useful evidence that can be promoted by transparent lexical
    # anchors before considering heavier cross-encoder rerankers.
    scored: list[tuple[float, dict[str, Any]]] = []
    max_lexical = max((lexical_score(query, item) for item in vector_items), default=0.0) or 1.0
    for item in vector_items:
        vector_rank_score = 1.0 / max(int(item["rank"]), 1)
        lexical_component = lexical_score(query, item) / max_lexical
        table_bonus = 0.05 if query.table_sensitive and (item["block_type"] == "table" or item["table_id"]) else 0.0
        final_score = 0.70 * vector_rank_score + 0.25 * lexical_component + table_bonus
        copied = dict(item)
        copied["hybrid_score"] = round(final_score, 6)
        copied["lexical_score"] = round(lexical_score(query, item), 4)
        scored.append((final_score, copied))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["rank"], pair[1]["chunk_id"]))
    results: list[dict[str, Any]] = []
    for rank, (_, item) in enumerate(scored, start=1):
        item["rank"] = rank
        results.append(item)
    return results


def hybrid_union_rrf(
    query: CoverageQuery,
    vector_items: list[dict[str, Any]],
    lexical_items: list[dict[str, Any]],
    candidate_k: int,
    retrieval_mode: str,
    table_items: list[dict[str, Any]] | None = None,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    # This diagnostic route tests whether lexical candidates can repair vector
    # candidate recall failures without creating a new embedding index. It keeps
    # route provenance explicit so downstream reports can tell whether a chunk
    # came from vector, lexical, or both routes.
    by_chunk_id: dict[str, dict[str, Any]] = {}
    for item in vector_items[:candidate_k]:
        chunk_id = item["chunk_id"]
        merged = by_chunk_id.setdefault(chunk_id, dict(item))
        merged["vector_rank"] = int(item["rank"])
        merged["vector_score"] = vector_score_from_distance(item.get("distance"))
        merged["source_routes"] = sorted(set(merged.get("source_routes", [])) | {"vector"})

    for item in lexical_items[:candidate_k]:
        chunk_id = item["chunk_id"]
        merged = by_chunk_id.setdefault(chunk_id, dict(item))
        merged["lexical_rank"] = int(item["rank"])
        merged["lexical_score"] = float(item.get("lexical_score") or lexical_score(query, item))
        merged["source_routes"] = sorted(set(merged.get("source_routes", [])) | {"lexical"})

    for item in table_items or []:
        chunk_id = item["chunk_id"]
        merged = by_chunk_id.setdefault(chunk_id, dict(item))
        merged["table_lexical_rank"] = int(item.get("table_lexical_rank") or item["rank"])
        merged["table_lexical_score"] = float(item.get("lexical_score") or lexical_score(query, item))
        merged["source_routes"] = sorted(set(merged.get("source_routes", [])) | {"table_lexical"})

    fused: list[dict[str, Any]] = []
    for chunk_id, item in by_chunk_id.items():
        vector_rank = item.get("vector_rank")
        lexical_rank = item.get("lexical_rank")
        table_lexical_rank = item.get("table_lexical_rank")
        rrf_score = 0.0
        vector_weight, lexical_weight, table_weight = rrf_route_weights(retrieval_mode)
        if vector_rank:
            rrf_score += vector_weight / (rrf_k + int(vector_rank))
        if lexical_rank:
            rrf_score += lexical_weight / (rrf_k + int(lexical_rank))
        if table_lexical_rank:
            rrf_score += table_weight / (rrf_k + int(table_lexical_rank))
        item["dedup_key"] = chunk_id
        item["rrf_k"] = rrf_k
        item["rrf_vector_weight"] = vector_weight
        item["rrf_lexical_weight"] = lexical_weight
        item["rrf_table_weight"] = table_weight
        item["rrf_score"] = round(rrf_score, 8)
        item.setdefault("vector_rank", None)
        item.setdefault("lexical_rank", None)
        item.setdefault("table_lexical_rank", None)
        item.setdefault("vector_score", None)
        item.setdefault("lexical_score", None)
        item.setdefault("table_lexical_score", None)
        item.setdefault("source_routes", [])
        fused.append(item)

    fused.sort(
        key=lambda item: (
            -float(item["rrf_score"]),
            min_rank(item.get("vector_rank"), item.get("lexical_rank")),
            item["chunk_id"],
        )
    )
    for rank, item in enumerate(fused, start=1):
        item["rank"] = rank
    if retrieval_mode == "hybrid_union_rrf_source_cap_diag":
        fused = apply_source_cap(fused, protected_top_k=5, max_per_source=2)
    return fused[:candidate_k]


def rrf_route_weights(retrieval_mode: str) -> tuple[float, float, float]:
    if retrieval_mode == "hybrid_union_rrf_lexical_weighted_07_03":
        return 0.3, 0.7, 0.0
    if retrieval_mode == "hybrid_union_rrf_lexical_weighted_08_02":
        return 0.2, 0.8, 0.0
    if retrieval_mode == "hybrid_union_rrf_table_fallback_diag":
        return 0.2, 0.7, 0.8
    if retrieval_mode == "hybrid_union_rrf_table_source_aware_diag":
        return 0.3, 0.7, 0.45
    return 1.0, 1.0, 0.0


def apply_source_cap(
    fused: list[dict[str, Any]],
    protected_top_k: int,
    max_per_source: int,
) -> list[dict[str, Any]]:
    # This is a diagnostic source-diversity cap, not a formal penalty. It tests
    # whether a dominant source can be controlled after fusion without changing
    # candidate generation. Items displaced from the protected top-k are kept in
    # the tail so failure analysis can still inspect them.
    protected: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for item in fused:
        guideline_id = str(item.get("guideline_id") or "")
        if len(protected) < protected_top_k and counts[guideline_id] < max_per_source:
            protected.append(item)
            counts[guideline_id] += 1
        else:
            overflow.append(item)
    reranked = protected + overflow
    for rank, item in enumerate(reranked, start=1):
        item["rank"] = rank
        item["source_cap_diag_max_per_source_top5"] = max_per_source
    return reranked


def vector_score_from_distance(distance: Any) -> float | None:
    if distance is None:
        return None
    try:
        return round(1.0 / (1.0 + float(distance)), 8)
    except (TypeError, ValueError):
        return None


def min_rank(*ranks: Any) -> int:
    numeric = [int(rank) for rank in ranks if rank is not None]
    return min(numeric) if numeric else 10**9


def lexical_score(query: CoverageQuery, item: dict[str, Any]) -> float:
    text = compact(
        "\n".join(
            [
                item.get("document", ""),
                item.get("guideline_title", ""),
                item.get("section", ""),
                item.get("table_title", ""),
            ]
        )
    )
    terms = query_terms(query.query)
    must_terms = [compact(term) for term in query.must_include]
    section_terms = [compact(term) for term in query.expected_section_keywords]
    score = 0.0
    score += sum(1.0 for term in terms if term and term in text)
    score += sum(1.5 for term in must_terms if term and term in text)
    score += sum(0.5 for term in section_terms if term and term in text)
    if query.table_sensitive and (item.get("block_type") == "table" or item.get("table_id")):
        score += 1.0
    return score


def query_terms(query_text: str) -> list[str]:
    return [
        compact(part)
        for part in query_text.replace("별", " ").replace("·", " ").split()
        if len(compact(part)) >= 2
    ]


def parse_guideline_id(chunk_id: str) -> str:
    marker = "__"
    parts = chunk_id.split(marker)
    return parts[1] if len(parts) >= 3 else "unknown"


def first_rank(items: list[dict[str, Any]], expected_sources: set[str]) -> int | None:
    for item in items:
        if item["guideline_id"] in expected_sources:
            return int(item["rank"])
    return None


def rank_within(rank: int | None, top_k: int) -> bool:
    return rank is not None and rank <= top_k


def joined_documents(items: Iterable[dict[str, Any]]) -> str:
    return "\n".join(str(item.get("document", "")) for item in items)


def term_hit_rate(terms: tuple[str, ...], text: str) -> float:
    if not terms:
        return 1.0
    haystack = compact(text)
    hits = sum(1 for term in terms if compact(term) in haystack)
    return round(hits / len(terms), 4)


def compact(value: str) -> str:
    return "".join((value or "").lower().split())


def entropy(counts: Iterable[int]) -> float:
    values = [count for count in counts if count > 0]
    total = sum(values)
    if total <= 0:
        return 0.0
    return round(-sum((count / total) * math.log(count / total, 2) for count in values), 4)


def build_source_distribution(
    source_chunk_counts: Counter[str],
    top1_counter: Counter[str],
    topk_counter: Counter[str],
    query_count: int,
    topk_total: int,
) -> list[dict[str, Any]]:
    total_chunks = sum(source_chunk_counts.values())
    rows: list[dict[str, Any]] = []
    all_sources = sorted(set(source_chunk_counts) | set(top1_counter) | set(topk_counter))
    for source in all_sources:
        chunk_count = source_chunk_counts.get(source, 0)
        chunk_share = ratio(chunk_count, total_chunks)
        top1_count = top1_counter.get(source, 0)
        top1_share = ratio(top1_count, query_count)
        topk_count = topk_counter.get(source, 0)
        topk_share = ratio(topk_count, topk_total)
        rows.append(
            {
                "guideline_id": source,
                "source_chunk_count": chunk_count,
                "corpus_chunk_share": chunk_share,
                "top1_count": top1_count,
                "top1_share": top1_share,
                "top1_overrepresentation_ratio": overrepresentation(top1_share, chunk_share),
                "topk_count": topk_count,
                "topk_share": topk_share,
                "topk_overrepresentation_ratio": overrepresentation(topk_share, chunk_share),
            }
        )
    return rows


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def overrepresentation(retrieval_share: float, chunk_share: float) -> float | None:
    if chunk_share <= 0:
        return None
    return round(retrieval_share / chunk_share, 4)


def summarize(
    collection_name: str,
    corpus_version: str,
    collection_count: int,
    queries: list[CoverageQuery],
    per_query: list[dict[str, Any]],
    source_distribution: list[dict[str, Any]],
    top_k_values: tuple[int, ...],
    dominant_source_warning_ratio: float,
    retrieval_mode: str,
) -> dict[str, Any]:
    query_count = len(per_query)
    table_queries = [row for row in per_query if row["table_sensitive"]]
    dominant = max(source_distribution, key=lambda row: row["top1_share"], default={})
    zero_hit_sources = sorted(
        {
            query.primary_expected_guideline_id
            for query in queries
            if not any(
                row["primary_expected_guideline_id"] == query.primary_expected_guideline_id
                and row["primary_source_in_top5"]
                for row in per_query
            )
        }
    )
    summary = {
        "collection_name": collection_name,
        "corpus_version": corpus_version,
        "retrieval_mode": retrieval_mode,
        "collection_count": collection_count,
        "query_count": query_count,
        "source_count": len({query.primary_expected_guideline_id for query in queries}),
        "top_k_values": list(top_k_values),
        "primary_top1_hit_rate": hit_rate(per_query, "primary_source_in_top1"),
        "primary_top3_hit_rate": hit_rate(per_query, "primary_source_in_top3"),
        "primary_top5_hit_rate": hit_rate(per_query, "primary_source_in_top5"),
        "expected_any_top1_hit_rate": hit_rate(per_query, "expected_source_in_top1"),
        "expected_any_top3_hit_rate": hit_rate(per_query, "expected_source_in_top3"),
        "expected_any_top5_hit_rate": hit_rate(per_query, "expected_source_in_top5"),
        "expected_any_candidate_hit_rate": hit_rate(per_query, "expected_source_in_candidate_k"),
        "must_include_pass_rate": hit_rate(per_query, "must_include_pass"),
        "average_must_include_hit_rate": average(row["must_include_hit_rate"] for row in per_query),
        "average_expected_section_hit_rate": average(row["expected_section_hit_rate"] for row in per_query),
        "table_sensitive_query_count": len(table_queries),
        "table_exposure_hit_rate": hit_rate(table_queries, "table_exposure_hit") if table_queries else 1.0,
        "zero_hit_primary_sources_top5": zero_hit_sources,
        "dominant_top1_source": dominant.get("guideline_id", ""),
        "dominant_top1_ratio": dominant.get("top1_share", 0.0),
        "dominant_top1_warning": dominant.get("top1_share", 0.0) > dominant_source_warning_ratio,
        "top1_source_entropy": entropy(row["top1_count"] for row in source_distribution),
        "topk_source_entropy": entropy(row["topk_count"] for row in source_distribution),
    }
    summary["query_type_breakdown"] = summarize_by_query_type(per_query)
    return summary


def hit_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4)


def average(values: Iterable[float]) -> float:
    values = list(values)
    return round(sum(values) / len(values), 4) if values else 0.0


def summarize_by_query_type(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in per_query:
        groups.setdefault(row["query_type"], []).append(row)
    return {
        query_type: {
            "query_count": len(rows),
            "primary_top5_hit_rate": hit_rate(rows, "primary_source_in_top5"),
            "expected_any_top5_hit_rate": hit_rate(rows, "expected_source_in_top5"),
            "must_include_pass_rate": hit_rate(rows, "must_include_pass"),
        }
        for query_type, rows in sorted(groups.items())
    }


def build_failures(per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in per_query:
        failure_types: list[str] = []
        if not row["expected_source_in_top5"]:
            failure_types.append("expected_source_not_in_top5")
        if not row["expected_source_in_candidate_k"]:
            failure_types.append("expected_source_not_in_candidate_k")
        if not row["primary_source_in_top5"]:
            failure_types.append("primary_source_not_in_top5")
        if not row["must_include_pass"]:
            failure_types.append("must_include_below_threshold")
        if row["table_sensitive"] and not row["table_exposure_hit"]:
            failure_types.append("table_sensitive_without_table_exposure")
        for failure_type in failure_types:
            failures.append(
                {
                    "query_id": row["query_id"],
                    "query": row["query"],
                    "query_type": row["query_type"],
                    "expected_sources": row["expected_guideline_ids"],
                    "primary_expected_source": row["primary_expected_guideline_id"],
                    "top5_sources": row["top5_sources"],
                    "failure_type": failure_type,
                    "retrieval_mode": row["retrieval_mode"],
                    "hypothesis": failure_hypothesis(failure_type),
                }
            )
    return failures


def failure_hypothesis(failure_type: str) -> str:
    hypotheses = {
        "expected_source_not_in_top5": "Expected source is not ranked high enough; inspect vector similarity, source boundary text, and possible reranking.",
        "expected_source_not_in_candidate_k": "Expected source is absent even in broad vector candidates; inspect embedding representation, chunk text, and query wording.",
        "primary_source_not_in_top5": "A secondary acceptable source may have been retrieved, but the primary guideline did not surface in top 5.",
        "must_include_below_threshold": "Retrieved text does not contain enough required lexical anchors; query may be semantically close but weakly grounded.",
        "table_sensitive_without_table_exposure": "Table-sensitive query did not retrieve a table chunk; lexical table fallback or reranking may be needed.",
    }
    return hypotheses.get(failure_type, "Inspect query design and retrieved chunks.")


def write_outputs(
    output_dir: Path,
    prefix: str,
    payload: dict[str, Any],
    per_query: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    source_distribution: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / f"{prefix}_report.json"
    failures_json = output_dir / f"{prefix}_failures.json"
    report_csv = output_dir / f"{prefix}_report.csv"
    failures_csv = output_dir / f"{prefix}_failures.csv"
    distribution_csv = output_dir / f"{prefix}_source_distribution.csv"

    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures_json.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(report_csv, flatten_query_rows(per_query))
    write_csv(failures_csv, failures)
    write_csv(distribution_csv, source_distribution)


def flatten_query_rows(per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in per_query:
        rows.append(
            {
                "query_id": row["query_id"],
                "query": row["query"],
                "query_type": row["query_type"],
                "retrieval_mode": row["retrieval_mode"],
                "primary_expected_guideline_id": row["primary_expected_guideline_id"],
                "expected_guideline_ids": "|".join(row["expected_guideline_ids"]),
                "top1_source": row["top1_source"],
                "top5_sources": "|".join(row["top5_sources"]),
                "primary_source_rank": row["primary_source_rank"] or "",
                "expected_source_rank": row["expected_source_rank"] or "",
                "primary_source_in_top1": row["primary_source_in_top1"],
                "primary_source_in_top3": row["primary_source_in_top3"],
                "primary_source_in_top5": row["primary_source_in_top5"],
                "expected_source_in_top1": row["expected_source_in_top1"],
                "expected_source_in_top3": row["expected_source_in_top3"],
                "expected_source_in_top5": row["expected_source_in_top5"],
                "expected_source_in_candidate_k": row["expected_source_in_candidate_k"],
                "must_include_hit_rate": row["must_include_hit_rate"],
                "must_include_pass": row["must_include_pass"],
                "expected_section_hit_rate": row["expected_section_hit_rate"],
                "table_sensitive": row["table_sensitive"],
                "table_exposure_hit": row["table_exposure_hit"],
                "topk_source_entropy": row["topk_source_entropy"],
                "retrieved_chunk_ids": "|".join(row["retrieved_chunk_ids"]),
                "route_summary": route_summary(row["results"]),
            }
        )
    return rows


def route_summary(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        routes = "+".join(item.get("source_routes", [])) if item.get("source_routes") else ""
        if routes:
            parts.append(f"{item.get('chunk_id')}:{routes}:v{item.get('vector_rank')}:l{item.get('lexical_rank')}:rrf{item.get('rrf_score')}")
    return "|".join(parts)


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
