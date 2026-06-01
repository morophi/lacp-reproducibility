#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LACP Scenario Agent sender.

Reason for this module:
  The agent/jump node supplies immutable citizen utterances to Harness and waits
  for acknowledgment. It intentionally has no RAG, SC-Protocol, metric, prompt,
  or inference-node responsibilities.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from scenario_loader import load_scenario


def _turn_payload(
    scenario: Dict[str, Any],
    turn: Dict[str, Any],
    run_id: str,
    condition: Optional[str],
    run_mode: Optional[str],
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "scenario_id": scenario["scenario_id"],
        "scenario_hash": scenario["scenario_hash"],
        "condition": condition or scenario.get("condition"),
        "run_mode": run_mode,
        "turn_no": turn["turn_no"],
        "utterance": turn["utterance"],
        "source_file": scenario["source_file"],
        "sender_node": "agent",
        "metadata": {
            "speaker": turn.get("speaker"),
        },
    }


async def send_scenario(
    scenario_path: str,
    harness_url: str,
    run_id: str,
    condition: str | None = None,
    run_mode: str | None = None,
    max_turns: int | None = None,
    flush_at_end: bool = True,
    turn_cooldown_every: int | None = None,
    turn_cooldown_sec: float = 0.0,
) -> None:
    scenario = load_scenario(scenario_path)
    endpoint = harness_url.rstrip("/") + "/turn"
    flush_endpoint = harness_url.rstrip("/") + "/flush?timeout=30"
    turns = scenario["turns"][:max_turns] if max_turns is not None else scenario["turns"]

    print(
        f"scenario_id={scenario['scenario_id']} turns={len(turns)}/{len(scenario['turns'])} "
        f"scenario_hash={scenario['scenario_hash']}"
    )

    for turn in turns:
        payload = _turn_payload(scenario, turn, run_id, condition, run_mode)
        turn_no = payload["turn_no"]
        print(f"send turn={turn_no} endpoint={endpoint}")

        status, data = await asyncio.to_thread(_post_json, endpoint, payload)
        if status >= 400 or not data.get("ok"):
            raise RuntimeError(f"Harness rejected turn {turn_no}: status={status} response={data}")

        completed = ",".join(data.get("nodes_completed", []))
        print(f"ack turn={turn_no} nodes_completed={completed}")
        if (
            turn_cooldown_every is not None
            and turn_cooldown_every > 0
            and turn_cooldown_sec > 0
            and turn_no % turn_cooldown_every == 0
            and turn is not turns[-1]
        ):
            print(f"turn_cooldown_start after_turn={turn_no} seconds={turn_cooldown_sec}")
            await asyncio.sleep(turn_cooldown_sec)
            print(f"turn_cooldown_done after_turn={turn_no}")
        await asyncio.sleep(0)

    if flush_at_end:
        status, data = await asyncio.to_thread(_post_json, flush_endpoint, {})
        if status == 404:
            print("flush endpoint unavailable; continuing with legacy harness behavior")
            return
        if status >= 400 or not data.get("ok"):
            raise RuntimeError(f"Harness log flush failed: status={status} response={data}")
        print("log_flush ok")


def _post_json(endpoint: str, payload: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=None) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = {"ok": False, "error": text}
        return exc.code, data
