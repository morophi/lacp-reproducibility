#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Preflight checks for the jump/agent formal TR launcher.

Run on the agent/jump node with LACP_DB_PASSWORD and LACP_DB_NAME set. This
performs read-only checks: launcher shape, live service reachability, scenario
shape, and DB schema visibility.
"""

from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any


AGENT = Path("/home/lacp/agent")
LAUNCHER = AGENT / "27_start_formal_tr.sh"
RUNNER = AGENT / "run_experiment_stage.py"
SCENARIO = AGENT / "scenario/civil_complaint_query_pool_v2.json"
NODE_CONFIG = Path("/home/lacp/harness/config/node_config.yaml")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def get_json(url: str, timeout: float = 8.0) -> tuple[int, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_status(url: str, timeout: float = 8.0) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(64)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def post_json_status(url: str, payload: dict[str, Any], timeout: float = 8.0) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
        try:
            data: Any = json.loads(text)
        except Exception:
            data = text
        return resp.status, data


def scenario_turn_count(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("turns"), list):
        return len(data["turns"])
    if isinstance(data, list):
        return len(data)
    raise RuntimeError(f"unsupported scenario shape: {path}")


def scenario_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = data.get("turns") if isinstance(data, dict) else data
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "scenario_id": data.get("scenario_id") if isinstance(data, dict) else path.stem,
        "source_file": data.get("source_file") if isinstance(data, dict) else None,
        "query_pool_id": data.get("query_pool_id") if isinstance(data, dict) else None,
        "pressure_layer": data.get("pressure_layer") if isinstance(data, dict) else None,
        "turns": len(turns),
    }


def db_query(query: str) -> str:
    env = dict(os.environ)
    code = r"""
import os
import pymysql
query = os.environ["LACP_QUERY"]
conn = pymysql.connect(
    host=os.environ.get("LACP_DB_HOST", "dblog"),
    user=os.environ.get("LACP_DB_USER", "morophi"),
    password=os.environ["LACP_DB_PASSWORD"],
    database=os.environ["LACP_DB_NAME"],
)
try:
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        for row in rows:
            print("\t".join("" if value is None else str(value) for value in row))
finally:
    conn.close()
"""
    env["LACP_QUERY"] = query
    proc = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return proc.stdout.strip()


def ssh_ok(host: str, command: str) -> bool:
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", host, command], text=True, capture_output=True)
    return proc.returncode == 0


def main() -> None:
    db_name = os.environ.get("LACP_DB_NAME")
    require(bool(os.environ.get("LACP_DB_PASSWORD")), "LACP_DB_PASSWORD is not set")
    require(db_name == "lacp_db_final", f"LACP_DB_NAME must be lacp_db_final, got {db_name!r}")

    require(LAUNCHER.exists(), f"missing launcher: {LAUNCHER}")
    require(RUNNER.exists(), f"missing runner: {RUNNER}")
    require(SCENARIO.exists(), f"missing scenario: {SCENARIO}")
    require(ssh_ok("harness", f"test -f {NODE_CONFIG}"), f"missing harness node config: {NODE_CONFIG}")

    launcher = LAUNCHER.read_text(encoding="utf-8")
    for needle in [
        "--stage tr",
        "--pre-run-readiness-probe",
        "--pre-run-post-readiness-unload",
        "--segment-every 5",
        "--segment-unload-runners",
        "--segment-cooldown-sec 60",
        "--thermal-log",
        "run_formal_post_validation_from_log.sh",
    ]:
        require(needle in launcher, f"launcher missing {needle}")

    runner = RUNNER.read_text(encoding="utf-8")
    require('DEFAULT_SCENARIO = "/home/lacp/agent/scenario/civil_complaint_query_pool_v2.json"' in runner, "runner DEFAULT_SCENARIO mismatch")
    require('"tr": StageSpec(' in runner and 'run_mode="formal"' in runner, "runner TR formal stage spec missing")

    turns = scenario_turn_count(SCENARIO)
    require(turns == 30, f"scenario turn count must be 30, got {turns}")
    scenario_meta = scenario_metadata(SCENARIO)

    service_status = {}
    status, body = post_json_status("http://harness:9000/flush?timeout=1", {})
    require(status == 200 and isinstance(body, dict) and body.get("ok"), f"harness_flush status={status} body={body}")
    service_status["harness_flush"] = {"status": status, "ok": body.get("ok")}
    rag_status = get_status("http://rag:8000/docs")
    require(rag_status == 200, f"rag_docs status={rag_status}")
    service_status["rag_docs"] = {"status": rag_status}

    node_status = {}
    for label, host in [("A", "inference-a"), ("B", "inference-b"), ("C", "inference-c")]:
        status, tags = get_json(f"http://{host}:11434/api/tags")
        require(status == 200, f"node {label} tags status={status}")
        models = [m.get("name") for m in tags.get("models", [])]
        require("qwen3-nothink:latest" in models or "qwen3-nothink" in models, f"node {label} missing qwen3-nothink model")
        ps_status, ps = get_json(f"http://{host}:11434/api/ps")
        require(ps_status == 200, f"node {label} ps status={ps_status}")
        node_status[label] = {"models": models[:5], "loaded_count": len(ps.get("models", []))}

    tables = db_query(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema=DATABASE() AND table_name IN "
        "('experiment_runs','turn_node_logs','payload_audit_logs','intervention_logs','metric_logs')"
    )
    require(tables == "5", f"DB table check expected 5, got {tables}")
    views = db_query(
        "SELECT COUNT(*) FROM information_schema.views "
        "WHERE table_schema=DATABASE() AND table_name IN "
        "('v_turn_node_logs','v_payload_audit_logs','v_intervention_logs','v_metric_logs')"
    )
    require(views == "4", f"DB view check expected 4, got {views}")

    print("formal_tr_preflight_ok")
    print(f"db_name={db_name}")
    print(f"scenario_turns={turns}")
    print("scenario=" + json.dumps(scenario_meta, ensure_ascii=False, sort_keys=True))
    print(f"launcher={LAUNCHER}")
    print(f"runner={RUNNER}")
    print("nodes=" + json.dumps(node_status, ensure_ascii=False, sort_keys=True))
    print("services=" + json.dumps(service_status, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
