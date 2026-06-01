#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import argparse
import time
import urllib.error
import urllib.request
from pathlib import Path

from config_utils import load_config
from prompt_builder import build_messages


OUTPUT_DIR = Path("/home/morophi/harness/validation_queries")
UTTERANCE = "나 생계급여 받을 수 있는지 알아보려고 하는데요. 기초수급자 기준이 도대체 어떻게 됩니까?"
SCENARIO_ID = "lacp_30turn_civil_complaint_v1"
SCENARIO_HASH = "8303dd12a5e488ea546114e074742ed272af928cdc836fa10057aabcf0b79369"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--node", default="A")
    parser.add_argument("--host", default="10.1.1.10")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config("/home/morophi/harness/config/node_config.yaml")
    model_cfg = config["model"]
    built = build_messages(args.node, UTTERANCE, [], [], None, None)
    max_tokens = args.max_tokens or int(model_cfg.get("num_predict", 512))
    payload = {
        "model": model_cfg.get("name", "qwen3-nothink"),
        "messages": built["messages"],
        "temperature": float(model_cfg.get("temperature", 0.0)),
        "seed": int(model_cfg.get("seed", 42)),
        "max_tokens": max_tokens,
        "logprobs": bool(model_cfg.get("request_logprobs", False)),
        "top_logprobs": int(model_cfg.get("top_logprobs", 5)),
        "think": bool(model_cfg.get("thinking", False)),
    }
    url = f"http://{args.host}:11434/v1/chat/completions"
    result = {
        "probe": "inference1_tr_formal_first_turn_direct",
        "db_writes": False,
        "harness_turn_called": False,
        "node": args.node,
        "url": url,
        "scenario_id": SCENARIO_ID,
        "scenario_hash": SCENARIO_HASH,
        "turn_no": 1,
        "prompt_metadata": built["prompt_metadata"],
        "request": {
            "max_tokens": payload["max_tokens"],
            "logprobs": payload["logprobs"],
            "top_logprobs": payload["top_logprobs"],
            "think": payload["think"],
        },
    }
    started = time.perf_counter()
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=420) as response:
            raw = json.loads(response.read().decode("utf-8"))
            elapsed_ms = (time.perf_counter() - started) * 1000
            choice = (raw.get("choices") or [{}])[0]
            logprobs = (choice.get("logprobs") or {}).get("content") or []
            text = ((choice.get("message") or {}).get("content") or "")
            finish_reason = choice.get("finish_reason")
            result.update(
                {
                    "ok": response.status == 200 and bool(text.strip()) and len(logprobs) > 0,
                    "status": response.status,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "finish_reason": finish_reason,
                    "truncation_risk": finish_reason == "length",
                    "response_chars": len(text),
                    "logprobs_len": len(logprobs),
                    "first_top_logprobs_len": len((logprobs[0].get("top_logprobs") if logprobs else []) or []),
                    "text_prefix": text[:240],
                }
            )
    except urllib.error.HTTPError as exc:
        result.update(
            {
                "ok": False,
                "status": exc.code,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": "HTTPError",
                "body_prefix": exc.read().decode("utf-8", errors="replace")[:500],
            }
        )
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": type(exc).__name__,
                "detail": str(exc),
            }
        )

    output = OUTPUT_DIR / f"{args.node}_tr_direct_probe_{max_tokens}.json"
    result["artifact"] = str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
