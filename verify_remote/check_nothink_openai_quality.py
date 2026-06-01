#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import re
import time
import urllib.request

HOSTS = ["10.1.1.10", "10.1.1.20", "10.1.1.30"]
MODEL = "qwen3-nothink"
PROMPT = "짧게 답하세요. 기초생활보장 신청은 어디서 하나요?"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_think_tags(text):
    return re.sub(r"(?is)<think>\s*</think>\s*", "", text or "").strip()


def korean_count(text):
    return sum("가" <= ch <= "힣" for ch in text or "")


def post_json(url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return response.status, json.loads(raw), round((time.perf_counter() - start) * 1000, 1)


def openai_payload():
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 128,
        "logprobs": True,
        "top_logprobs": 5,
        "think": False,
    }


def native_payload():
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0,
            "seed": 42,
            "num_predict": 128,
        },
    }


def parse_openai(data):
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    clean = strip_think_tags(content)
    logprob_content = (choice.get("logprobs") or {}).get("content") or []
    return {
        "content": content,
        "clean_content": clean,
        "content_hash": sha256(content),
        "clean_hash": sha256(clean),
        "content_len": len(content),
        "clean_len": len(clean),
        "reasoning_len": len(message.get("reasoning") or ""),
        "finish_reason": choice.get("finish_reason"),
        "logprobs_len": len(logprob_content),
        "first_top_logprobs_len": len(logprob_content[0].get("top_logprobs", [])) if logprob_content else None,
        "has_empty_think_tag": bool(re.search(r"(?is)<think>\s*</think>", content)),
        "starts_with_think_tag": content.lstrip().lower().startswith("<think>"),
        "korean_chars_clean": korean_count(clean),
        "contains_korean_clean": korean_count(clean) > 0,
    }


def parse_native(data):
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    content = message.get("content") or data.get("response") or ""
    clean = strip_think_tags(content)
    return {
        "content": content,
        "clean_content": clean,
        "content_hash": sha256(content),
        "clean_hash": sha256(clean),
        "content_len": len(content),
        "clean_len": len(clean),
        "thinking_len": len(str(data.get("thinking") or "")),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "korean_chars_clean": korean_count(clean),
        "contains_korean_clean": korean_count(clean) > 0,
    }


def check_host(host):
    print(f"\n================ {host} ================")
    openai_runs = []
    for i in range(2):
        try:
            status, data, elapsed = post_json(f"http://{host}:11434/v1/chat/completions", openai_payload())
            parsed = parse_openai(data)
            parsed["status"] = status
            parsed["elapsed_ms"] = elapsed
            openai_runs.append(parsed)
            print(f"[openai {i+1}] status={status} elapsed_ms={elapsed}")
            print("  content_len:", parsed["content_len"], "clean_len:", parsed["clean_len"])
            print("  finish_reason:", parsed["finish_reason"], "reasoning_len:", parsed["reasoning_len"])
            print("  logprobs_len:", parsed["logprobs_len"], "first_top_logprobs_len:", parsed["first_top_logprobs_len"])
            print("  has_empty_think_tag:", parsed["has_empty_think_tag"], "starts_with_think_tag:", parsed["starts_with_think_tag"])
            print("  clean_hash:", parsed["clean_hash"])
            print("  clean_preview:", parsed["clean_content"][:180].replace("\n", " "))
            print("  korean_chars_clean:", parsed["korean_chars_clean"])
        except Exception as exc:
            print(f"[openai {i+1}] ERROR:", repr(exc))

    if len(openai_runs) == 2:
        print("[determinism]")
        print("  same_clean_hash:", openai_runs[0]["clean_hash"] == openai_runs[1]["clean_hash"])
        print("  same_logprobs_len:", openai_runs[0]["logprobs_len"] == openai_runs[1]["logprobs_len"])
        print("  same_empty_think_tag:", openai_runs[0]["has_empty_think_tag"] == openai_runs[1]["has_empty_think_tag"])

    try:
        status, data, elapsed = post_json(f"http://{host}:11434/api/chat", native_payload())
        native = parse_native(data)
        print("[native]")
        print("  status:", status, "elapsed_ms:", elapsed)
        print("  clean_len:", native["clean_len"], "thinking_len:", native["thinking_len"])
        print("  clean_hash:", native["clean_hash"])
        print("  clean_preview:", native["clean_content"][:180].replace("\n", " "))
        print("  korean_chars_clean:", native["korean_chars_clean"])
        print("  prompt_eval_count:", native["prompt_eval_count"], "eval_count:", native["eval_count"])

        if openai_runs:
            o = openai_runs[0]
            print("[openai_vs_native_after_strip]")
            print("  both_contain_korean:", o["contains_korean_clean"] and native["contains_korean_clean"])
            print("  same_clean_hash:", o["clean_hash"] == native["clean_hash"])
            print("  openai_clean_len:", o["clean_len"], "native_clean_len:", native["clean_len"])
            print("  openai_korean_chars:", o["korean_chars_clean"], "native_korean_chars:", native["korean_chars_clean"])
    except Exception as exc:
        print("[native] ERROR:", repr(exc))


def main():
    for host in HOSTS:
        check_host(host)


if __name__ == "__main__":
    main()
