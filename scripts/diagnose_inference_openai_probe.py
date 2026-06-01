#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Direct OpenAI-compatible probe for the three inference nodes.

This diagnostic script does not touch Harness configuration or logs. It sends
the same payload shape Harness uses in openai_chat_completions mode and prints
compact JSONL results for A/B/C.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


NODES = {
    "A": "10.1.1.10",
    "B": "10.1.1.20",
    "C": "10.1.1.30",
}


def build_payload(args: argparse.Namespace) -> dict:
    if args.long_prompt_chars > 0:
        prompt = (
            "Direct inference probe input. "
            "The key settings are max_tokens, logprobs, top_logprobs, and think=false.\n"
            + ("LACP smoke probe context. " * 400)
        )[: args.long_prompt_chars]
    else:
        prompt = "Say ready in Korean."

    return {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": args.max_tokens,
        "logprobs": True,
        "top_logprobs": 5,
        "think": False,
    }


def probe_node(node: str, host: str, payload: dict, timeout_s: float) -> dict:
    url = f"http://{host}:11434/v1/chat/completions"
    started = time.perf_counter()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            raw = json.loads(body.decode("utf-8"))
            choices = raw.get("choices") or [{}]
            logprobs = (choices[0].get("logprobs") or {}).get("content") or []
            text = ((choices[0].get("message") or {}).get("content") or "")[:120]
            return {
                "node": node,
                "host": host,
                "status": resp.status,
                "elapsed_ms": round(elapsed_ms, 1),
                "bytes": len(body),
                "logprobs_len": len(logprobs),
                "first_top_count": len((logprobs[0].get("top_logprobs") if logprobs else []) or []),
                "text_prefix": text,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "node": node,
            "host": host,
            "status": exc.code,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": "HTTPError",
            "body_prefix": body.decode("utf-8", errors="replace")[:300],
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "node": node,
            "host": host,
            "elapsed_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3-nothink")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--long-prompt-chars", type=int, default=0)
    args = parser.parse_args()

    payload = build_payload(args)
    print(json.dumps({
        "event": "probe_start",
        "max_tokens": args.max_tokens,
        "timeout_s": args.timeout_s,
        "long_prompt_chars": args.long_prompt_chars,
        "message_chars": sum(len(m["content"]) for m in payload["messages"]),
    }, ensure_ascii=False))
    for node, host in NODES.items():
        print(json.dumps(probe_node(node, host, payload, args.timeout_s), ensure_ascii=False))


if __name__ == "__main__":
    main()
