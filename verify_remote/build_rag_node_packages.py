from __future__ import annotations

"""
Build top-k separated RAG-node deployment bundles.

Change reason:
    LACP now validates top-k=3 and top-k=5 as distinct treatment conditions.
    The corpus content stays unchanged; this script packages the same approved
    chunks and embeddings with separate collection names, validation logs, and
    prompt artifacts so the RAG node can load each condition independently.
"""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/morophi/lacp_rag")
RUN_ID = "20260523T_v2_table_safe_caption_sep2"
PREFIX = f"rag_basic_living_2026_{RUN_ID}"
PACKAGE_ROOT = ROOT / "deploy" / RUN_ID
TOPK_CONFIGS = {
    3: {
        "collection_name": "lacp_docs_v2_table_safe_topk3",
        "retrieval_log": ROOT / "logs" / f"{PREFIX}_hybrid_retrieval_topk3.json",
        "prompt_size_log": ROOT / "logs" / f"{PREFIX}_hybrid_prompt_size_topk3.json",
        "prompt_dir": ROOT / "logs" / f"{PREFIX}_hybrid_ab_prompts_topk3",
    },
    5: {
        "collection_name": "lacp_docs_v2_table_safe_topk5",
        "retrieval_log": ROOT / "logs" / f"{PREFIX}_hybrid_retrieval_topk5.json",
        "prompt_size_log": ROOT / "logs" / f"{PREFIX}_hybrid_prompt_size_topk5.json",
        "prompt_dir": ROOT / "logs" / f"{PREFIX}_hybrid_ab_prompts_topk5",
    },
}

COMMON_FILES = {
    "chunks": ROOT / "chunks" / f"{PREFIX}_chunks.jsonl",
    "embeddings": ROOT / "embeddings" / f"{PREFIX}_embeddings.npy",
    "embedding_metadata": ROOT / "embeddings" / f"{PREFIX}_embedding_metadata.jsonl",
    "manifest": ROOT / "manifest" / f"{PREFIX}_manifest.json",
    "chunking_log": ROOT / "logs" / f"{PREFIX}_chunking.json",
    "embedding_log": ROOT / "logs" / f"{PREFIX}_embedding.json",
}

SCRIPT_FILES = [
    ROOT / "scripts" / "08_ingest_chromadb.py",
    ROOT / "scripts" / "09_validate_retrieval.py",
    ROOT / "scripts" / "10_prompt_size_test.py",
    ROOT / "scripts" / "ingest_config.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package_topk(top_k: int, config: dict) -> Path:
    run_dir = PACKAGE_ROOT / f"topk{top_k}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for name, src in COMMON_FILES.items():
        if name in {"chunks"}:
            copy_file(src, run_dir / "chunks" / src.name)
        elif name in {"embeddings", "embedding_metadata"}:
            copy_file(src, run_dir / "embeddings" / src.name)
        elif name == "manifest":
            copy_file(src, run_dir / "manifest" / src.name)
        else:
            copy_file(src, run_dir / "logs" / src.name)

    copy_file(config["retrieval_log"], run_dir / "logs" / config["retrieval_log"].name)
    copy_file(config["prompt_size_log"], run_dir / "logs" / config["prompt_size_log"].name)
    copy_tree(config["prompt_dir"], run_dir / "logs" / config["prompt_dir"].name)
    for script in SCRIPT_FILES:
        copy_file(script, run_dir / "scripts" / script.name)

    deploy_policy = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "top_k": top_k,
        "collection_name": config["collection_name"],
        "corpus_version": "v2_table_safe",
        "source_collection": "lacp_docs_v2_table_safe",
        "retrieval_mode": "hybrid_table_fallback_validation",
        "chunk_contents_modified": False,
        "source_values_modified": False,
        "chroma_path_on_rag": "/home/morophi/chromadb_data",
        "ingest_command": (
            f"/home/morophi/RAG/bin/python scripts/08_ingest_chromadb.py "
            f"--chunks chunks/{COMMON_FILES['chunks'].name} "
            f"--embeddings embeddings/{COMMON_FILES['embeddings'].name} "
            f"--metadata embeddings/{COMMON_FILES['embedding_metadata'].name} "
            f"--collection-name {config['collection_name']} "
            f"--chroma-path /home/morophi/chromadb_data"
        ),
    }
    write_json(run_dir / "deploy_policy.json", deploy_policy)

    checksums = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        checksums[str(path.relative_to(run_dir))] = sha256(path)
    write_json(run_dir / "checksums_sha256.json", checksums)

    tar_path = PACKAGE_ROOT / f"{PREFIX}_topk{top_k}_rag_node_package.tar.gz"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(run_dir, arcname=run_dir.name)
    return tar_path


def main() -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    tarballs = [package_topk(top_k, cfg) for top_k, cfg in TOPK_CONFIGS.items()]
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "package_root": str(PACKAGE_ROOT),
        "tarballs": [str(path) for path in tarballs],
        "collections": {
            f"topk{top_k}": cfg["collection_name"] for top_k, cfg in TOPK_CONFIGS.items()
        },
    }
    write_json(PACKAGE_ROOT / "rag_node_package_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
