#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Ollama node client used only by Harness."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Tuple

import aiohttp


class NodeClient:
    def __init__(
        self,
        nodes: Dict[str, Dict[str, Any]],
        model_config: Dict[str, Any],
        run_modes: Dict[str, Dict[str, Any]] | None = None,
    ):
        self.nodes = nodes
        self.run_modes = run_modes or {}
        self.model_name = model_config.get("name", "qwen3-nothink")
        self.temperature = float(model_config.get("temperature", 0.0))
        self.seed = int(model_config.get("seed", 42))
        self.thinking = bool(model_config.get("thinking", False))
        self.num_predict = int(model_config.get("num_predict", 512))
        self.request_timeout_sec = float(model_config.get("request_timeout_sec", 240.0))
        self.endpoint_by_run_mode = model_config.get("endpoint_by_run_mode", {})
        self.request_logprobs = bool(model_config.get("request_logprobs", False))
        self.top_logprobs = int(model_config.get("top_logprobs", 5))
        self.strip_empty_think_tags = bool(model_config.get("strip_empty_think_tags", True))

    async def chat(self, node: str, messages: list[dict], run_mode: str = "formal") -> Dict[str, Any]:
        normalized_node = node.upper()
        if normalized_node not in self.nodes:
            raise ValueError(f"Unknown inference node: {node}")

        endpoint_mode = self.endpoint_by_run_mode.get(run_mode, self.endpoint_by_run_mode.get("formal", "native_chat"))
        num_predict = self._num_predict_for_run_mode(run_mode)
        if endpoint_mode == "openai_chat_completions":
            url = self._openai_chat_url(normalized_node)
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": self.temperature,
                "seed": self.seed,
                "max_tokens": num_predict,
                "logprobs": self._request_logprobs_for_run_mode(run_mode),
                "top_logprobs": self._top_logprobs_for_run_mode(run_mode),
                "think": self.thinking,
            }
        elif endpoint_mode == "native_chat":
            url = self.nodes[normalized_node]["url"]
            payload = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "think": self.thinking,
                "options": {
                    "temperature": self.temperature,
                    "seed": self.seed,
                    "num_predict": num_predict,
                },
            }
        else:
            raise ValueError(f"Unsupported node endpoint mode: {endpoint_mode}")

        start = time.perf_counter()
        request_timeout = self._request_timeout_for_run_mode(run_mode)
        timeout = aiohttp.ClientTimeout(total=request_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    raw_text = await resp.text()
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    try:
                        raw = await resp.json()
                    except Exception:
                        raw = {"raw_text": raw_text}
                    response_text_raw = self._extract_response_text(raw)
                    clean_info = self._clean_response(response_text_raw, raw)
                    return {
                        "node": normalized_node,
                        "ok": resp.status == 200,
                        "status": resp.status,
                        "endpoint_mode": endpoint_mode,
                        "text": clean_info["clean_text"],
                        "text_raw": response_text_raw,
                        "thinking_tag_present": clean_info["thinking_tag_present"],
                        "empty_thinking_shell": clean_info["empty_thinking_shell"],
                        "thinking_content_present": clean_info["thinking_content_present"],
                        "cleaning_applied": clean_info["cleaning_applied"],
                        "cleaning_allowed": clean_info["cleaning_allowed"],
                        "failed_TR": clean_info["failed_TR"],
                        "removed_prefix_chars": clean_info["removed_prefix_chars"],
                        "raw_logprobs": clean_info["raw_logprobs"],
                        "clean_logprobs": clean_info["clean_logprobs"],
                        "excluded_token_positions": clean_info["excluded_token_positions"],
                        "raw": raw,
                        "elapsed_ms": elapsed_ms,
                    }
        except asyncio.TimeoutError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            raise TimeoutError(
                "node request timeout "
                f"node={normalized_node} run_mode={run_mode} endpoint={endpoint_mode} "
                f"timeout_sec={request_timeout} elapsed_ms={elapsed_ms:.1f}"
            ) from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"node request failed node={normalized_node} run_mode={run_mode} endpoint={endpoint_mode}: {exc}"
            ) from exc

    def _openai_chat_url(self, node: str) -> str:
        url = self.nodes[node]["url"]
        if "/api/chat" in url:
            return url.replace("/api/chat", "/v1/chat/completions")
        if url.endswith("/"):
            return url.rstrip("/") + "/v1/chat/completions"
        return url

    def _num_predict_for_run_mode(self, run_mode: str) -> int:
        mode_cfg = self.run_modes.get(run_mode, {})
        if isinstance(mode_cfg, dict) and mode_cfg.get("num_predict") is not None:
            return int(mode_cfg["num_predict"])
        return self.num_predict

    def _request_timeout_for_run_mode(self, run_mode: str) -> float:
        mode_cfg = self.run_modes.get(run_mode, {})
        if isinstance(mode_cfg, dict) and mode_cfg.get("request_timeout_sec") is not None:
            return float(mode_cfg["request_timeout_sec"])
        return self.request_timeout_sec

    def _request_logprobs_for_run_mode(self, run_mode: str) -> bool:
        mode_cfg = self.run_modes.get(run_mode, {})
        if isinstance(mode_cfg, dict) and mode_cfg.get("request_logprobs") is not None:
            return bool(mode_cfg["request_logprobs"])
        return self.request_logprobs

    def _top_logprobs_for_run_mode(self, run_mode: str) -> int:
        mode_cfg = self.run_modes.get(run_mode, {})
        if isinstance(mode_cfg, dict) and mode_cfg.get("top_logprobs") is not None:
            return int(mode_cfg["top_logprobs"])
        return self.top_logprobs

    def _extract_response_text(self, raw: Dict[str, Any]) -> str:
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                return message.get("content") or ""
        return raw.get("message", {}).get("content") or raw.get("response") or ""

    def _clean_response(self, text: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        raw_logprobs = self._extract_openai_logprobs(raw)
        think_match = re.match(r"(?is)^\s*<think>(.*?)</think>\s*", text or "")
        thinking_tag_present = bool(think_match)
        thinking_content = think_match.group(1) if think_match else ""
        thinking_content_present = bool(thinking_content.strip())
        empty_thinking_shell = thinking_tag_present and not thinking_content_present
        removed_prefix_chars = len(think_match.group(0)) if empty_thinking_shell and self.strip_empty_think_tags else 0
        cleaning_allowed = not thinking_content_present

        # Empty Qwen think shells are chat-template artifacts, not model
        # reasoning. We remove them only when the shell is empty and exclude
        # exactly the same prefix token span from LMS inputs for metric
        # alignment. Non-empty thinking content is treated as failed_TR.
        if removed_prefix_chars:
            clean_text = (text or "")[removed_prefix_chars:].strip()
        else:
            clean_text = text or ""
        excluded_positions, clean_logprobs = self._split_logprobs_by_prefix(raw_logprobs, removed_prefix_chars)

        return {
            "clean_text": clean_text,
            "thinking_tag_present": thinking_tag_present,
            "empty_thinking_shell": empty_thinking_shell,
            "thinking_content_present": thinking_content_present,
            "cleaning_applied": bool(removed_prefix_chars),
            "cleaning_allowed": cleaning_allowed,
            "failed_TR": thinking_content_present,
            "removed_prefix_chars": removed_prefix_chars,
            "raw_logprobs": raw_logprobs,
            "clean_logprobs": clean_logprobs,
            "excluded_token_positions": excluded_positions,
        }

    @staticmethod
    def _extract_openai_logprobs(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
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

    def _split_logprobs_by_prefix(
        self,
        raw_logprobs: List[Dict[str, Any]],
        removed_prefix_chars: int,
    ) -> Tuple[List[int], List[Dict[str, Any]]]:
        if removed_prefix_chars <= 0:
            return [], list(raw_logprobs)

        cursor = 0
        excluded_positions: List[int] = []
        clean_logprobs: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_logprobs):
            token_text = self._token_text(item)
            cursor += len(token_text)
            if cursor <= removed_prefix_chars:
                excluded_positions.append(index)
            else:
                clean_logprobs.append(item)
        return excluded_positions, clean_logprobs

    @staticmethod
    def _token_text(item: Dict[str, Any]) -> str:
        raw_bytes = item.get("bytes")
        if isinstance(raw_bytes, list):
            try:
                return bytes(raw_bytes).decode("utf-8", errors="replace")
            except Exception:
                pass
        return str(item.get("token") or "")
