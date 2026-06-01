# LACP Retrieval Policy v1 Candidate

Status: formal-readiness candidate, pending focused manual labels for table and exception queries.

This document fixes the current retrieval substrate candidate before CR/CR2/Run B
so later causal interpretation is not confounded by silent retrieval changes.
It records the diagnostic evidence used to move away from the original
source-boundary embedding policy.

## Corpus Identity

- Run id: `20260525T_full_guideline_v1`
- Corpus version: `v1_full_guideline_table_safe`
- Base collection name: `lacp_docs_v1_full_guideline_table_safe`
- Candidate collection name: `lacp_docs_v1_full_guideline_table_safe_body_only_v1`
- Chunk count: `12240`
- Source count: `18`
- Embedding dimension: `384`
- RAG node ingest: not executed

## Embedding Text Policy

Policy: `body_only_v1`

The stored chunk document keeps the source boundary and provenance text for
display/audit use. The embedding surface strips the repeated
`[LACP_SOURCE_BOUNDARY]` wrapper and embeds only the chunk body.

Rationale:

- `original_with_source_boundary` vector-only expected-any top5 was `0.2000`.
- `body_only_v1` vector-only expected-any top5 improved to `0.8667`.
- `body_only_v1` vector-only candidate top30 hit was `0.9889`.
- Source dominance warning disappeared under `body_only_v1`.

`title_once_body_v1` is not selected because it underperformed `body_only_v1`
on expected-any top5 and did not improve table exposure.

## Candidate Generation

- Vector route: top30 from `body_only_v1` Chroma collection.
- Lexical route: top30 transparent lexical overlap over chunk document,
  guideline title, section, and table title.
- Table route: diagnostic only for table-sensitive queries.

No query expansion or paraphrasing is included in v1. This keeps the causal
retrieval substrate interpretable and avoids adding another uncontrolled
variable before CR/CR2.

## Fusion Rule

Primary candidate fusion: `hybrid_union_rrf_lexical_weighted_07_03`

- Dedup key: `chunk_id`
- RRF k: `60`
- Vector route weight: `0.3`
- Lexical route weight: `0.7`
- Final top-k for prompt context: top5 unless a run-specific prompt-size gate
  requires top3.

Rationale:

- `body_only_v1 + hybrid_union_rrf_lexical_weighted_07_03`
  - expected-any top5: `0.9222`
  - expected-any candidate top30: `0.9889`
  - primary top5: `0.7889`
  - dominant top1 ratio: `0.1000`
  - g04 wrong top1 count: `1`
  - lexical-hit union-miss count: `0`

## Table Route Diagnostic

Current table diagnostic: `hybrid_union_rrf_table_source_aware_diag`

For table-sensitive queries only:

1. Run the primary body-only lexical-weighted union.
2. Take sources already present in the primary top5.
3. Add table lexical candidates only from those sources.
4. Preserve vector-only and primary union results separately in logs.

Diagnostic result:

- expected-any top5: `0.9222`
- table-sensitive expected-any top5: `0.9333`
- table exposure hit: `0.4667`
- dominant top1 ratio: `0.1000`
- g04 wrong top1 count: `1`

Interpretation:

The source-aware table route improves exposure without reproducing source
dominance, but table exposure is still below a formal 0.80 target. It should
remain a diagnostic candidate until manually labeled table queries confirm
whether the exposed table chunks are actually the correct table evidence.

## Acceptance Criteria

Required before formal freeze:

- Expected-any top5 >= `0.90`
- Expected-any candidate top30 >= `0.95`
- Zero-hit primary sources top5: none
- Dominant top1 ratio <= `0.30`
- g04 wrong top1 no longer dominant artifact
- Table-sensitive expected-any top5 >= `0.90`
- Table exposure: diagnostic improvement documented; formal target remains
  `0.80` after manual table labels are added.

## Known Limitations

- Source-level expected labels are still coarse. Some queries need
  `expected_section`, `expected_chunk_id`, `expected_block_type`, and
  `expected_table_id`.
- Table fallback can harm source correctness if it is not source-aware.
- Lexical matching is transparent and useful for diagnosis, but it is not BM25.
- This policy does not include source frequency penalties, query expansion, or
  cross-encoder reranking.

## Required Logs

For each CR/CR2/Run B retrieval run, preserve:

- `retrieval_mode`
- `embedding_text_policy`
- `collection_name`
- `corpus_version`
- `vector_rank`
- `lexical_rank`
- `table_lexical_rank` when applicable
- `vector_score`
- `lexical_score`
- `rrf_score`
- `source_routes`
- `dedup_key`
- `table_exposure`

## Current Evidence Artifacts

Remote root:
`/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs`

Key files:

- `retrieval_variant_comparison.csv`
- `retrieval_variant_comparison.json`
- `full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_report.json`
- `full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json`
- `body_only_v1_hybrid_union_rrf_table_source_aware_diag_slice_summary.json`
- `body_only_v1_hybrid_union_rrf_table_source_aware_diag_table_sensitive_slice.csv`
