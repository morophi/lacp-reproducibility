#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from collections import Counter

import chromadb


COLLECTION = "lacp_docs_v2_table_safe_topk5"
PATH = "/home/morophi/chromadb_data"


def main() -> None:
    client = chromadb.PersistentClient(path=PATH)
    collection = client.get_collection(COLLECTION)
    print(json.dumps({"collection": COLLECTION, "count": collection.count()}, ensure_ascii=False))

    sample = collection.get(limit=20, include=["metadatas", "documents"])
    block_types = Counter()
    sections = Counter()
    source_files = Counter()
    for meta in sample.get("metadatas", []):
        if not meta:
            continue
        block_types[str(meta.get("block_type"))] += 1
        sections[str(meta.get("section"))] += 1
        source_files[str(meta.get("source_file"))] += 1
    print(json.dumps({
        "sample_block_types": block_types,
        "sample_sections": sections,
        "sample_source_files": source_files,
    }, ensure_ascii=False, default=dict))

    for idx, (doc_id, meta, doc) in enumerate(
        zip(sample.get("ids", []), sample.get("metadatas", []), sample.get("documents", [])),
        start=1,
    ):
        print(json.dumps({
            "sample_no": idx,
            "id": doc_id,
            "chunk_id": (meta or {}).get("chunk_id"),
            "page_range": (meta or {}).get("page_range"),
            "section": (meta or {}).get("section"),
            "block_type": (meta or {}).get("block_type"),
            "text_preview": (doc or "")[:360],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
