#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""DB-free formal logprobs probe for A/B/C inference nodes.

This script bypasses Harness, MariaDB, intervention logging, and metric logging.
It sends one minimal OpenAI-compatible chat-completions request to each node and
writes only a local JSON summary. Use it before TR to verify that formal
logprobs are actually available without polluting experiment DB tables.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_NODES = {
    "A": "http://10.1.1.10:11434/api/chat",
    "B": "http://10.1.1.20:11434/api/chat",
    "C": "http://10.1.1.30:11434/api/chat",
}


def openai_url(url: str) -> str:
    if "/api/chat" in url:
        return url.replace("/api/chat", "/v1/chat/completions")
    if url.endswith("/"):
        return url.rstrip("/") + "/v1/chat/completions"
    return url


def post_json(url: str, payload: dict[str, Any], timeout_sec: int) -> tuple[int, dict[str, Any], float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
        elapsed_ms = (time.perf_counter() - start) * 1000
        raw = response.read().decode("utf-8", errors="replace")
        return response.status, json.loads(raw), elapsed_ms


def extract_text(raw: dict[str, Any]) -> str:
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                return message.get("content") or ""
    return raw.get("response") or raw.get("message", {}).get("content") or ""


def extract_logprobs(raw: dict[str, Any]) -> list[dict[str, Any]]:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    choice = choices[0]
    if not isinstance(choice, dict):
        return []
    logprobs = choice.get("logprobs")
    if not isinstance(logprobs, dict):
        return []
    content = logprobs.get("content")
    return content if isinstance(content, list) else []


def top_candidate_count(item: dict[str, Any]) -> int:
    top = item.get("top_logprobs")
    return len(top) if isinstance(top, list) else 0


def summarize_node(node: str, base_url: str, args: argparse.Namespace) -> dict[str, Any]:
    url = openai_url(base_url)
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": args.max_tokens,
        "logprobs": True,
        "top_logprobs": args.top_logprobs,
        "think": False,
    }
    result: dict[str, Any] = {
        "node": node,
        "url": url,
        "request": {
            "model": args.model,
            "max_tokens": args.max_tokens,
            "logprobs": True,
            "top_logprobs": args.top_logprobs,
            "think": False,
            "temperature": 0.0,
            "seed": 42,
        },
    }
    try:
        status, raw, elapsed_ms = post_json(url, payload, args.timeout_sec)
        text = extract_text(raw)
        logprob_items = extract_logprobs(raw)
        top_counts = [top_candidate_count(item) for item in logprob_items[:10]]
        result.update(
            {
                "ok": status == 200,
                "http_status": status,
                "elapsed_ms": round(elapsed_ms, 3),
                "response_text_len": len(text),
                "response_text_preview": text[:300],
                "top_level_keys": sorted(raw.keys()),
                "choices_present": isinstance(raw.get("choices"), list),
                "raw_logprobs_len": len(logprob_items),
                "first_token_keys": sorted(logprob_items[0].keys()) if logprob_items else [],
                "first_10_top_logprobs_counts": top_counts,
                "logprobs_available": len(logprob_items) > 0,
                "lms_preflight_candidate": len(logprob_items) > 0 and any(count >= 2 for count in top_counts),
            }
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        result.update({"ok": False, "http_status": exc.code, "error": body[:1000]})
    except Exception as exc:
        result.update({"ok": False, "error": repr(exc)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3-nothink")
    parser.add_argument("--prompt", default="기초생활보장 수급자격 확인 절차를 한 문장으로 설명하세요.")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--top-logprobs", type=int, default=5)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument(
        "--out-dir",
        default="validation_queries/logprobs_preflight",
        help="Local output directory. No DB writes are performed.",
    )
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"formal_logprobs_no_db_{stamp}.json"

    results = [summarize_node(node, url, args) for node, url in DEFAULT_NODES.items()]
    summary = {
        "created_at_utc": stamp,
        "db_writes": False,
        "harness_logging": False,
        "purpose": "formal logprobs availability probe before TR",
        "all_nodes_ok": all(item.get("ok") for item in results),
        "all_nodes_logprobs_available": all(item.get("logprobs_available") for item in results),
        "all_nodes_lms_preflight_candidate": all(item.get("lms_preflight_candidate") for item in results),
        "results": results,
    }
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote: {out_path}")
    return 0 if summary["all_nodes_lms_preflight_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
