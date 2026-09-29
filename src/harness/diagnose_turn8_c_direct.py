#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/lacp/harness")

from config_utils import load_config  # noqa: E402
from prompt_builder import build_messages  # noqa: E402


def load_turns(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = data if isinstance(data, list) else data["turns"]
    normalized = []
    for item in turns:
        turn_no = item.get("turn_no", item.get("turn"))
        normalized.append({"turn_no": int(turn_no), "utterance": item["utterance"]})
    return normalized


def reconstruct_history(jsonl_path: Path, turns: list[dict], node: str, before_turn: int) -> list[dict]:
    utterances = {item["turn_no"]: item["utterance"] for item in turns}
    rows = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("node") != node or int(row.get("turn_no", 0)) >= before_turn:
                continue
            rows.append(row)
    rows.sort(key=lambda row: int(row["turn_no"]))
    history = []
    for row in rows:
        quality = row.get("quality_gate") or {}
        if not quality.get("history_eligible", row.get("history_eligible", True)):
            continue
        turn_no = int(row["turn_no"])
        history.append({"role": "user", "content": utterances[turn_no]})
        history.append({"role": "assistant", "content": row.get("response_text") or ""})
    return history


def post_json(url: str, payload: dict, timeout_sec: float) -> tuple[int | None, dict | None, str, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8", errors="replace")
            elapsed_ms = (time.perf_counter() - started) * 1000
            try:
                return response.status, json.loads(text), text[:1000], elapsed_ms
            except Exception:
                return response.status, None, text[:1000], elapsed_ms
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            raw = json.loads(text)
        except Exception:
            raw = None
        return exc.code, raw, text[:1000], elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return None, None, f"{type(exc).__name__}: {exc}", elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", default="/home/lacp/harness/logs/runs/tr_20260601T083620Z_rep01.jsonl")
    parser.add_argument("--scenario", default="/home/lacp/harness/validation_queries/lacp_30turn_civil_complaint_v1.json")
    parser.add_argument("--config", default="/home/lacp/harness/config/node_config.yaml")
    parser.add_argument("--node", default="C")
    parser.add_argument("--host", default="inference-c")
    parser.add_argument("--turn", type=int, default=8)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--top-logprobs", type=int, default=None)
    parser.add_argument("--no-logprobs", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--history-last-turns", type=int, default=None)
    parser.add_argument("--native-chat", action="store_true")
    parser.add_argument("--out", default="/home/lacp/harness/validation_queries/turn8_c_direct_diagnosis.json")
    args = parser.parse_args()

    turns = load_turns(Path(args.scenario))
    utterances = {item["turn_no"]: item["utterance"] for item in turns}
    history = [] if args.no_history else reconstruct_history(Path(args.jsonl), turns, args.node, args.turn)
    if args.history_last_turns is not None:
        history = history[-args.history_last_turns * 2 :]
    built = build_messages(args.node, utterances[args.turn], history, None, None, None)
    cfg = load_config(args.config)
    model_cfg = cfg["model"]
    mode_cfg = cfg.get("run_modes", {}).get("formal", {})
    max_tokens = args.max_tokens or int(mode_cfg.get("num_predict", model_cfg.get("num_predict", 512)))
    if args.native_chat:
        payload = {
            "model": model_cfg.get("name", "qwen3-nothink"),
            "messages": built["messages"],
            "stream": False,
            "think": bool(model_cfg.get("thinking", False)),
            "options": {
                "temperature": float(model_cfg.get("temperature", 0.0)),
                "seed": int(model_cfg.get("seed", 42)),
                "num_predict": max_tokens,
            },
        }
        url = f"http://{args.host}:11434/api/chat"
    else:
        payload = {
            "model": model_cfg.get("name", "qwen3-nothink"),
            "messages": built["messages"],
            "temperature": float(model_cfg.get("temperature", 0.0)),
            "seed": int(model_cfg.get("seed", 42)),
            "max_tokens": max_tokens,
            "logprobs": False if args.no_logprobs else bool(model_cfg.get("request_logprobs", False)),
            "top_logprobs": args.top_logprobs if args.top_logprobs is not None else int(model_cfg.get("top_logprobs", 5)),
            "think": bool(model_cfg.get("thinking", False)),
        }
        url = f"http://{args.host}:11434/v1/chat/completions"
    status, raw, body_prefix, elapsed_ms = post_json(url, payload, args.timeout_sec)
    choice = ((raw or {}).get("choices") or [{}])[0]
    if args.native_chat:
        text = ((raw or {}).get("message") or {}).get("content") or ""
        finish_reason = (raw or {}).get("done_reason")
        logprobs = []
    else:
        text = ((choice.get("message") or {}).get("content") or "") if isinstance(choice, dict) else ""
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        logprobs = ((choice.get("logprobs") or {}).get("content") or []) if isinstance(choice, dict) else []
    result = {
        "diagnosis": "turn8_node_c_direct_replay",
        "db_writes": False,
        "harness_turn_called": False,
        "url": url,
        "node": args.node,
        "turn_no": args.turn,
        "timeout_sec": args.timeout_sec,
        "status": status,
        "elapsed_ms": round(elapsed_ms, 1),
        "timed_out": status is None and ("Timeout" in body_prefix or "timed out" in body_prefix),
        "error_or_body_prefix": body_prefix,
        "finish_reason": finish_reason,
        "response_chars": len(text),
        "logprobs_len": len(logprobs),
        "prompt_metadata": built["prompt_metadata"],
        "history_messages": len(history),
        "request": {
            "max_tokens": max_tokens,
            "logprobs": payload.get("logprobs", False),
            "top_logprobs": payload.get("top_logprobs"),
            "think": payload["think"],
            "seed": payload.get("seed", payload.get("options", {}).get("seed")),
            "temperature": payload.get("temperature", payload.get("options", {}).get("temperature")),
            "native_chat": args.native_chat,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == 200 else 2


if __name__ == "__main__":
    raise SystemExit(main())
