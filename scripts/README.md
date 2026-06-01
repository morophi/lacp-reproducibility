# Production RAG Ingest Scripts

## 2026-05 v2 Small-Chunk Rebuild Note

This pipeline now defaults to `corpus_version=v2_table_safe` and
`collection_name=lacp_docs_v2_table_safe` because the previous large-chunk
corpus produced top-k=3 prompts around 5888 chars / 4190 Ollama prompt tokens.
That exceeded the BC-250 + Qwen3 8B + Ollama `num_ctx=4096` envelope and caused
prompt truncation plus A/B concurrent generation timeouts.

The old collection must remain untouched. Do not ingest this rebuild into
`lacp_docs`; use the versioned v2 collection.

These scripts implement the governed ingest pipeline validated in
`exam_test/`, but they are parameterized for real source documents.

## Policy

- Do not chunk a PDF directly.
- Do not embed a PDF directly.
- Every source document must pass through canonical markdown before chunking.
- The pipeline stops after semantic verification by default.
- Chunking and embedding require human approval of the semantic report.
- Tables and protected semantic blocks are preserved by the chunker.
- v2 table chunks are split only by rows; each part repeats table title,
  columns, source, section, year, unit, `table_id`, and `table_part_label`.
- Retrieval validation must log trigger-contamination fields for every query:
  query text, top-k, returned IDs, block type distribution, table IDs, context
  chars, estimated prompt chars, chunk lengths, collection, and corpus version.

## Pipeline

```text
raw PDF
-> extracted text
-> canonical markdown
-> semantic verification report and gate
-> table-aware chunks
-> embeddings
-> manifest snapshot
-> versioned ChromaDB collection
-> top-k=3 retrieval and prompt-size validation
-> dblog log/manifest sync
```

## Typical Commands

Interactive run. The runner lists PDFs in `raw/`, asks for a number, runs
steps 01-03, prints the semantic verification summary, then asks whether to
continue through steps 04-06:

```bash
cd /Users/morophi/lacp_rag
/Users/morophi/rag_venv/bin/python scripts/run_ingest.py \
  --source-label "<ascii_source_label>" \
  --run-id "<run_id>"
```

Non-interactive run through semantic verification:

```bash
cd /Users/morophi/lacp_rag
/Users/morophi/rag_venv/bin/python scripts/run_ingest.py \
  --source "raw/<source-file>.pdf" \
  --source-label "<ascii_source_label>" \
  --run-id "<run_id>"
```

After reviewing the semantic report, continue non-interactively through
chunking, embedding, and manifest:

```bash
cd /Users/morophi/lacp_rag
/Users/morophi/rag_venv/bin/python scripts/run_ingest.py \
  --source "raw/<source-file>.pdf" \
  --source-label "<ascii_source_label>" \
  --run-id "<run_id>" \
  --from-step chunks \
  --until manifest \
  --allow-approved-stages
```

Load the new v2 collection into ChromaDB without touching `lacp_docs`:

```bash
/Users/morophi/rag_venv/bin/python scripts/08_ingest_chromadb.py \
  --collection-name lacp_docs_v2_table_safe \
  --chroma-path /data/chromadb \
  --reset-new-collection
```

Run top-k=3 retrieval sanity checks:

```bash
/Users/morophi/rag_venv/bin/python scripts/09_validate_retrieval.py \
  --collection-name lacp_docs_v2_table_safe \
  --chroma-path /data/chromadb \
  --top-k 3
```

Create Harness-ready A/B prompt files and measure prompt sizes:

```bash
/Users/morophi/rag_venv/bin/python scripts/10_prompt_size_test.py \
  --collection-name lacp_docs_v2_table_safe \
  --chroma-path /data/chromadb \
  --top-k 3
```

Preview the command plan without writing artifacts:

```bash
/Users/morophi/rag_venv/bin/python scripts/run_ingest.py \
  --source "raw/<source-file>.pdf" \
  --source-label "<ascii_source_label>" \
  --run-id "<run_id>" \
  --dry-run
```

`--step-dry-run` calls each selected stage with its own `--dry-run` flag. Use it
only when the required upstream artifacts for downstream stages already exist.

## Embedding Output Location

The current production config writes embedding artifacts to the project-local
directory:

```text
/Users/morophi/lacp_rag/embeddings
```

It does not write to `~/embeddings`.

## Environment Variables

- `LACP_RAG_SOURCE`: source PDF path, set by `run_ingest.py --source`
- `LACP_RAG_SOURCE_LABEL`: ASCII artifact label, set by `--source-label`
- `LACP_RAG_RUN_ID`: shared run identifier, set by `--run-id`
- `LACP_RAG_VENV`: virtual environment path, default `/Users/morophi/rag_venv`
- `LACP_RAG_EMBEDDING_MODEL`: embedding model name
- `LACP_RAG_EMBEDDING_MODEL_VERSION`: model version label
- `LACP_RAG_CORPUS_VERSION`: default `v2_table_safe`
- `LACP_RAG_COLLECTION_NAME`: default `lacp_docs_v2_table_safe`
- `LACP_CHROMADB_PATH`: default `/data/chromadb`
- `LACP_DBLOG_HOST`: SSH host alias for central dblog storage, default `dblog`
- `LACP_DBLOG_REMOTE_ROOT`: dblog path relative to remote home, default
  `lacp_logs/imac_embedding`

## dblog Log Sync

After the manifest stage, `run_ingest.py` calls `07_sync_logs_to_dblog.py` by
default. This syncs only iMac-produced logs, manifests, source metadata, and
transfer records directly to dblog. It does not route anything through Harness.

Default dblog archive layout:

```text
~/lacp_logs/imac_embedding/<run_id>/<artifact_prefix>/
```

Use `--skip-dblog-sync` only when dblog is unavailable and you intentionally
want a local-only run.

## Files

- `ingest_config.py`: shared paths, source selection, policy constants
- `01_pdf_extract.py`: PDF to extracted text
- `02_canonicalize_md.py`: extracted text to canonical markdown
- `03_semantic_verify_report.py`: manual semantic verification report and gate
- `04_chunk_table_aware.py`: approved markdown to chunks
- `05_embed_chunks.py`: approved chunks to embeddings
- `06_manifest_snapshot.py`: reproducibility manifest and final summary
- `07_sync_logs_to_dblog.py`: direct dblog archive for iMac logs and manifests
- `08_ingest_chromadb.py`: ingest embeddings into the versioned v2 ChromaDB collection
- `09_validate_retrieval.py`: top-k=3 retrieval sanity and contamination-risk log
- `10_prompt_size_test.py`: prompt-size measurement and A/B prompt generation
- `run_ingest.py`: staged runner

The manifest stage also writes:

- `manifest/corpus_version.txt`
- `manifest/chunk_policy_v2.json`
- `manifest/source_files_sha256.txt`
- `manifest/chunks_sha256.txt`
- `manifest/embedding_model.txt`
- `manifest/embedding_model_version.txt`
- `manifest/collection_name.txt`
- `manifest/build_timestamp.txt`
- `manifest/build_summary.json`
