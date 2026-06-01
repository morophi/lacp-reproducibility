# LACP Retrieval Policy v1 Draft

Status: pre-CR formal candidate, not final freeze.

This draft documents the current formal retrieval candidate for CR/CR2/Run B
readiness. It is meant to prevent silent retrieval changes while the final
manual section/chunk/table labels are reviewed. Formal freeze is not declared
until the manual label set passes.

## Selected Candidate

- `embedding_text_policy`: `body_only_v1`
- `candidate_generation`: `vector_top30 + lexical_top30`
- `fusion`: `lexical_weighted_RRF_0.7_0.3`
- `RRF k`: `60`
- `dedup_key`: `chunk_id`
- `final_topK`: `5`
- `table_route`: `source-aware diagnostic`

## Corpus Identity

- Run id: `20260525T_full_guideline_v1`
- Corpus version: `v1_full_guideline_table_safe`
- Candidate collection: `lacp_docs_v1_full_guideline_table_safe_body_only_v1`
- Chunk count: `12240`
- Source count: `18`
- Embedding dimension: `384`
- RAG node ingest: not executed

## Embedding Text Policy

`body_only_v1` strips the repeated source boundary/header/provenance wrapper
from the embedding surface while preserving the stored chunk document and
metadata for audit and prompt display.

Diagnostic evidence:

- `original_with_source_boundary` vector-only expected-any top5: `0.2000`
- `body_only_v1` vector-only expected-any top5: `0.8667`
- `body_only_v1` vector-only candidate top30: `0.9889`
- `body_only_v1` removed the g04/g17-style dominant source warning from the
  vector route.

## Fusion Candidate

`hybrid_union_rrf_lexical_weighted_07_03` unions vector and lexical candidates
by `chunk_id`, then applies reciprocal-rank fusion.

Weights:

- lexical route: `0.7`
- vector route: `0.3`
- RRF k: `60`

Diagnostic evidence for `body_only_v1 + hybrid_union_rrf_lexical_weighted_07_03`:

- expected-any top5: `0.9222`
- expected-any candidate top30: `0.9889`
- primary top5: `0.7889`
- dominant top1 ratio: `0.1000`
- g04 wrong top1 count: `1`
- lexical-hit union-miss count: `0`
- zero-hit primary sources: none

## Table Route Candidate

`table_route = source-aware diagnostic`

The table route is not final freeze. It operates only for table-sensitive
queries and only after base retrieval has established source/guideline anchors.

Rules:

- Applies only when `table_sensitive = true`.
- Base route remains `body_only_v1 + hybrid_union_rrf_lexical_weighted_07_03`.
- Table candidates are drawn only from sources/guidelines already present in
  the base retrieval top5.
- No forced table insertion from unrelated sources.
- Vector-only and base union results must remain logged separately.
- Table route final freeze requires manual labels.

Diagnostic evidence for source-aware table route:

- expected-any top5: `0.9222`
- table-sensitive expected-any top5: `0.9333`
- table exposure hit: `0.4667`
- dominant top1 ratio: `0.1000`
- g04 wrong top1 count: `1`

Interpretation:

The source-aware route improves table exposure from `0.3333` to `0.4667`
without damaging expected source retrieval or creating source dominance. It is
better than naive table fallback, but below the formal table exposure target.

## Evidence Sidecar Status

Evidence sidecar is separated from the base retrieval policy.

Current status:

- `sidecar_logging_enabled = true`
- `sidecar_prompt_injection_enabled = false`
- `sidecar_status = diagnostic_only`
- CR/CR2 default retrieval policy must not include sidecar prompt injection.

Reason:

`evidence_sidecar_v1` preserved base source retrieval quality but did not pass
the assisted section/chunk/table-level gate.

Observed v1 diagnostics:

- expected-any top5 preserved: `0.9222`
- candidate top30 preserved: `0.9889`
- dominant top1 ratio preserved: `0.1000`
- section_or_chunk_hit_rate: `0.625`
- combined_context_evidence_hit_rate: `0.6500`
- sidecar_expected_evidence_hit_rate: `0.3500`
- critical_failure_count: `24`
- table_sensitive_critical_failure_count: `7`
- sidecar_wrong_evidence_count: `21`
- sidecar attached queries: `70/90`
- average added chars when present: about `2297`

Interpretation:

The sidecar architecture is safer than final top5 replacement because it does
not damage base retrieval. However, v1 is too broad and too heavy for prompt
injection. It remains logging-only evidence for diagnostics.

Future `evidence_sidecar_v2` diagnostic should be narrower:

- `sidecar_max_items = 1`
- `sidecar_max_chars_per_query = 800-1000`
- apply only when base top5 has evidence-miss risk
- apply only for `table_sensitive`, `exception`, `eligibility`, `procedure`
- require source/guideline anchor match
- require query-type marker match
- require high confidence evidence score
- record prompt injection eligibility separately

## Freeze Gate

Final formal freeze requires manual labels for the 40-query stratified v2 set.

Manual labels should fill:

- `expected_section`
- `expected_chunk_id`
- `expected_block_type`
- `expected_table_id`

Freeze can be declared only if the manually labeled slice confirms that the
candidate route retrieves the correct section/chunk/table evidence, not merely
the correct source.

The v2 manual set is stratified as the CR/CR2 pre-freeze gate:

- `table_sensitive`: 10
- `eligibility`: 8
- `exception`: 8
- `procedure`: 6
- `concept`: up to 4, with any corpus-query deficit filled by borderline cases
- `title_direct`: 2
- previous failure/borderline: at least 2

Freeze thresholds:

- `critical_failure_count = 0`
- `table_sensitive_critical_failure_count = 0`
- `major_failure_count <= 3`
- `section_or_chunk_hit_rate >= 0.80`
- `wrong_table_insertion_count = 0`, or at most 1 explainable case
- `expected_source_dropped_after_table_aug <= 1`
- failures must not cluster in a single source or query type

Unless this v2 set reveals a critical failure cluster, do not expand the manual
freeze gate to 60 or 90 queries before CR/CR2.

## Required Run Logging

Every CR/CR2/Run B retrieval record must preserve:

- `retrieval_mode`
- `embedding_text_policy`
- `collection_name`
- `corpus_version`
- `candidate_generation`
- `final_topK`
- `dedup_key`
- `vector_rank`
- `lexical_rank`
- `table_lexical_rank`
- `vector_score`
- `lexical_score`
- `rrf_score`
- `source_routes`
- `table_exposure`
- `sidecar_logging_enabled`
- `sidecar_prompt_injection_enabled`
- `supporting_evidence_candidates` when diagnostic logging is enabled

## Evidence Artifacts

Remote log root:
`/Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs`

Required artifacts:

- `retrieval_variant_comparison.csv`
- `retrieval_variant_comparison.json`
- `source_aware_table_diagnostic.csv`
- `manual_labeling_targets_v1.csv`
- `manual_labeling_targets_v2.csv`
- `full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_report.json`
- `full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json`
- `body_only_v1_hybrid_union_rrf_table_source_aware_diag_table_sensitive_slice.csv`
- `full_guideline_retrieval_coverage_body_only_v1_evidence_sidecar_v1_report.json`
- `manual_labeling_freeze_gate_v2_evidence_sidecar.json`
