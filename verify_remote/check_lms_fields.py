#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import urllib.request

HOSTS = ["10.1.1.10", "10.1.1.20", "10.1.1.30"]
WANTED = {"logprobs", "top_logprobs", "logits", "token_candidates", "tokens"}


def walk(obj, path=""):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            current = f"{path}.{key}" if path else key
            if key in WANTED:
                found.append((current, type(value).__name__))
            found.extend(walk(value, current))
    elif isinstance(obj, list):
        for index, value in enumerate(obj[:5]):
            found.extend(walk(value, f"{path}[{index}]"))
    return found


def post_json(url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return response.status, json.loads(raw)


def check_api(host, api):
    if api == "chat":
        url = f"http://{host}:11434/api/chat"
        payload = {
            "model": "qwen3:8b",
            "messages": [
                {"role": "user", "content": "짧게 답하세요. 기초생활보장 신청은 어디서 하나요?"}
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "seed": 42,
                "num_predict": 64,
                "logprobs": 5,
                "top_logprobs": 5,
            },
        }
    else:
        url = f"http://{host}:11434/api/generate"
        payload = {
            "model": "qwen3:8b",
            "prompt": "짧게 답하세요. 기초생활보장 신청은 어디서 하나요?",
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "seed": 42,
                "num_predict": 64,
                "logprobs": 5,
                "top_logprobs": 5,
            },
        }

    print(f"===== {host} /api/{api} =====")
    try:
        status, data = post_json(url, payload)
    except Exception as exc:
        print("request_error:", repr(exc))
        return

    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    text = message.get("content") or data.get("response") or ""
    print("http_status:", status)
    print("top_level_keys:", sorted(data.keys()))
    print("message_keys:", sorted(message.keys()) if message else None)
    print("response_text_len:", len(text))
    print("thinking_present:", "thinking" in data, "thinking_len:", len(str(data.get("thinking") or "")))
    print("prompt_eval_count:", data.get("prompt_eval_count"), "eval_count:", data.get("eval_count"))
    print("lms_fields:", walk(data))


def main():
    for host in HOSTS:
        check_api(host, "chat")
    for host in HOSTS:
        check_api(host, "generate")


if __name__ == "__main__":
    main()
