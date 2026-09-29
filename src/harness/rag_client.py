#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Raw RAG retrieval client for Harness.

The RAG node remains a retrieval service only. This client returns raw chunks and
does not summarize, rewrite, interpret, or apply SC-Protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import chromadb
from sentence_transformers import SentenceTransformer


class RAGClient:
    def __init__(self, host: str, port: int, collection: str, embedding_model: str):
        self.host = host
        self.port = port
        self.collection_name = collection
        self.embedding_model_name = embedding_model
        self._client = chromadb.HttpClient(host=host, port=port)
        self._collection = self._client.get_collection(collection)
        self._embedder = SentenceTransformer(embedding_model, local_files_only=True)

    async def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._retrieve_sync, query, top_k)

    def _retrieve_sync(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        embedding = self._embedder.encode([query], normalize_embeddings=True)[0].tolist()
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks = []
        for idx, chunk_id in enumerate(ids):
            metadata = metas[idx] if idx < len(metas) and isinstance(metas[idx], dict) else {}
            chunks.append(
                {
                    "chunk_id": metadata.get("chunk_id") or chunk_id,
                    "id": chunk_id,
                    "collection_name": self.collection_name,
                    "retrieval_method": "chromadb_vector",
                    "source": metadata.get("source_file") or metadata.get("source"),
                    "score": None if idx >= len(distances) else distances[idx],
                    "text": docs[idx] if idx < len(docs) else "",
                    "metadata": metadata,
                }
            )
        return chunks
