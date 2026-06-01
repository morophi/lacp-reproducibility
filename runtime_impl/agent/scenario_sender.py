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
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Sequence

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
    turn_timeout_sec: float | None = 300.0,
    segment_every: int | None = None,
    segment_cooldown_sec: float = 0.0,
    segment_unload_runners: bool = False,
    segment_settle_sec: float = 0.0,
    segment_unload_timeout_sec: float = 30.0,
    inference_hosts: Sequence[str] | None = None,
    model_name: str = "qwen3-nothink",
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

        status, data = await asyncio.to_thread(_post_json, endpoint, payload, turn_timeout_sec)
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
        if (
            segment_every is not None
            and segment_every > 0
            and turn_no % segment_every == 0
            and turn is not turns[-1]
        ):
            await _segment_boundary(
                after_turn=turn_no,
                flush_endpoint=flush_endpoint,
                cooldown_sec=segment_cooldown_sec,
                unload_runners=segment_unload_runners,
                settle_sec=segment_settle_sec,
                unload_timeout_sec=segment_unload_timeout_sec,
                inference_hosts=inference_hosts or (),
                model_name=model_name,
            )
        await asyncio.sleep(0)

    if flush_at_end:
        status, data = await asyncio.to_thread(_post_json, flush_endpoint, {}, 30.0)
        if status == 404:
            print("flush endpoint unavailable; continuing with legacy harness behavior")
            return
        if status >= 400 or not data.get("ok"):
            raise RuntimeError(f"Harness log flush failed: status={status} response={data}")
        print("log_flush ok")


async def _segment_boundary(
    after_turn: int,
    flush_endpoint: str,
    cooldown_sec: float,
    unload_runners: bool,
    settle_sec: float,
    unload_timeout_sec: float,
    inference_hosts: Sequence[str],
    model_name: str,
) -> None:
    print(f"segment_boundary_start after_turn={after_turn}")
    status, data = await asyncio.to_thread(_post_json, flush_endpoint, {}, 30.0)
    if status == 404:
        print(f"segment_flush_unavailable after_turn={after_turn}")
    elif status >= 400 or not data.get("ok"):
        raise RuntimeError(f"Harness segment flush failed after turn {after_turn}: status={status} response={data}")
    else:
        print(f"segment_flush_ok after_turn={after_turn}")

    if unload_runners:
        await _unload_inference_runners(inference_hosts, model_name, unload_timeout_sec, after_turn)

    if settle_sec > 0:
        print(f"segment_settle_start after_turn={after_turn} seconds={settle_sec}")
        await asyncio.sleep(settle_sec)
        print(f"segment_settle_done after_turn={after_turn}")

    if cooldown_sec > 0:
        print(f"segment_cooldown_start after_turn={after_turn} seconds={cooldown_sec}")
        await asyncio.sleep(cooldown_sec)
        print(f"segment_cooldown_done after_turn={after_turn}")
    print(f"segment_boundary_done after_turn={after_turn}")


async def _unload_inference_runners(
    inference_hosts: Sequence[str],
    model_name: str,
    timeout_sec: float,
    after_turn: int,
) -> None:
    if not inference_hosts:
        raise RuntimeError("--segment-unload-runners requires at least one inference host")
    tasks = [
        asyncio.to_thread(_post_json, f"http://{host}:11434/api/generate", _unload_payload(model_name), timeout_sec)
        for host in inference_hosts
    ]
    rows = await asyncio.gather(*tasks)
    failed = []
    for host, (status, data) in zip(inference_hosts, rows):
        if status >= 400:
            failed.append(f"{host}:status={status}:response={data}")
        else:
            print(f"segment_unload_ok after_turn={after_turn} host={host} status={status}")
    if failed:
        raise RuntimeError(f"inference runner unload failed after turn {after_turn}: {', '.join(failed)}")


def _unload_payload(model_name: str) -> Dict[str, Any]:
    return {
        "model": model_name,
        "prompt": "",
        "stream": False,
        "keep_alive": 0,
    }


def _post_json(endpoint: str, payload: Dict[str, Any], timeout_sec: float | None) -> tuple[int, Dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text)
    except socket.timeout:
        return 599, {"ok": False, "error": f"request timed out after {timeout_sec} seconds"}
    except TimeoutError:
        return 599, {"ok": False, "error": f"request timed out after {timeout_sec} seconds"}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = {"ok": False, "error": text}
        return exc.code, data
    except urllib.error.URLError as exc:
        return 599, {"ok": False, "error": str(exc.reason)}
