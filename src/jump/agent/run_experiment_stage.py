#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run predeclared LACP experiment stages through Harness.

The agent node owns stage orchestration: run-id creation, repeated scenario
dispatch, and lightweight dblog row-count checks. Harness remains the per-turn
executor and evidence writer.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scenario_loader import load_scenario
from scenario_sender import send_scenario


DEFAULT_SCENARIO = "/home/lacp/agent/scenario/civil_complaint_query_pool_v2.json"
RUN_B_SCENARIO = "/home/lacp/agent/scenario/lacp_run_b_scenario_v1.json"
CF_SCENARIO = "/home/lacp/agent/scenario/lacp_cf_scenario_v1.json"
CF_F_DEFAULT_FORCED_TURNS = [3, 6, 9, 12, 15, 18, 21, 24, 27, 29]
DEFAULT_HARNESS_URL = "http://harness:9000"
DEFAULT_DB_HOST = "dblog"
DEFAULT_DB_USER = "morophi"
DEFAULT_DB_PASSWORD = os.environ.get("LACP_DB_PASSWORD", "")
DEFAULT_DB_NAME = "lacp_db_final"
DEFAULT_HARNESS_HOST = "harness"
DEFAULT_THETA_PATH = "/home/lacp/harness/config/theta_config.json"
DEFAULT_NODE_CONFIG_PATH = "/home/lacp/harness/config/node_config.yaml"
DEFAULT_ENTROPY_PERCENTILE = 0.70
DEFAULT_TRIGGER_PERCENTILE = 0.95
DEFAULT_THERMAL_OUTPUT_DIR = "/home/lacp/agent/validation_queries/formal_thermal"
DEFAULT_THERMAL_NODES = "inference1=inference-a,inference2=inference-b,inference3=inference-c"
DEFAULT_FAILED_ARCHIVE_DIR = "/home/lacp/agent/validation_queries/failed_runs"
DEFAULT_INFERENCE_HOSTS = "inference-a,inference-b,inference-c"
DEFAULT_MODEL_NAME = "qwen3-nothink"
ROLEMAP_PREFIX = "rev9_10_A-ragsc_B-ragonly_C-baseline_np512_hist3"


@dataclass(frozen=True)
class StageSpec:
    condition: str
    run_mode: str
    repetitions: int
    max_turns: Optional[int]
    run_id_prefix: str
    expected_nodes: int = 3
    causal_evidence: bool = True


STAGES = {
    "tr": StageSpec(
        condition="tr",
        run_mode="formal",
        repetitions=1,
        max_turns=None,
        run_id_prefix=f"tr_{ROLEMAP_PREFIX}",
        causal_evidence=False,
    ),
    "cr": StageSpec(
        condition="cr",
        run_mode="formal",
        repetitions=10,
        max_turns=None,
        run_id_prefix=f"cr_{ROLEMAP_PREFIX}",
    ),
    "cr2": StageSpec(
        condition="cr2",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cr2_{ROLEMAP_PREFIX}",
    ),
    "run_b": StageSpec(
        condition="run_b",
        run_mode="formal",
        repetitions=30,
        max_turns=None,
        run_id_prefix="run_b_repetition_#x",
    ),
    "cf_a": StageSpec(
        condition="cf_a",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cf_a_{ROLEMAP_PREFIX}",
    ),
    "cf_b": StageSpec(
        condition="cf_b",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cf_b_{ROLEMAP_PREFIX}",
    ),
    "cf_c": StageSpec(
        condition="cf_c",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cf_c_{ROLEMAP_PREFIX}",
    ),
    "cf_d": StageSpec(
        condition="cf_d",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cf_d_{ROLEMAP_PREFIX}",
    ),
    "cf_e": StageSpec(
        condition="cf_e",
        run_mode="formal",
        repetitions=5,
        max_turns=None,
        run_id_prefix=f"cf_e_{ROLEMAP_PREFIX}",
    ),
    "cf_f": StageSpec(
        condition="cf_f",
        run_mode="formal",
        repetitions=10,
        max_turns=None,
        run_id_prefix=f"cf_f_{ROLEMAP_PREFIX}",
    ),
}


STAGE_DEFAULT_SCENARIOS = {
    "run_b": RUN_B_SCENARIO,
    "cf_a": CF_SCENARIO,
    "cf_b": CF_SCENARIO,
    "cf_c": CF_SCENARIO,
    "cf_d": CF_SCENARIO,
    "cf_e": CF_SCENARIO,
    "cf_f": CF_SCENARIO,
}


def default_scenario_for_stage(stage: str) -> str:
    return STAGE_DEFAULT_SCENARIOS.get(stage, DEFAULT_SCENARIO)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a LACP experiment stage through Harness.")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES), help="Experiment stage to run.")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario JSON path on the agent node. Defaults to the stage-specific frozen scenario.",
    )
    parser.add_argument("--harness-url", default=DEFAULT_HARNESS_URL, help="Harness base URL.")
    parser.add_argument("--condition", default=None, help="Override stage condition sent to Harness.")
    parser.add_argument("--run-mode", default=None, help="Override stage run_mode sent to Harness.")
    parser.add_argument("--run-id-prefix", default=None, help="Override run_id prefix.")
    parser.add_argument("--repetitions", type=int, default=None, help="Override stage repetition count.")
    parser.add_argument(
        "--repetition-start-index",
        type=int,
        default=1,
        help="First logical repetition index used in generated run_id postfixes.",
    )
    parser.add_argument("--max-turns", type=int, default=None, help="Override max turns per run.")
    parser.add_argument("--full-scenario", action="store_true", help="Ignore stage max-turn default and run all turns.")
    parser.add_argument("--skip-db-check", action="store_true", help="Skip dblog row-count validation.")
    parser.add_argument("--skip-theta-freeze", action="store_true", help="Do not freeze theta after CR2.")
    parser.add_argument(
        "--entropy-percentile",
        type=float,
        default=DEFAULT_ENTROPY_PERCENTILE,
        help="Percentile for theta_entropy over CR2 token entropy values.",
    )
    parser.add_argument(
        "--trigger-percentile",
        type=float,
        default=DEFAULT_TRIGGER_PERCENTILE,
        help="Percentile for theta_lms/theta_cds/theta_ma over CR2 absolute Node C-relative differentials.",
    )
    parser.add_argument("--harness-host", default=DEFAULT_HARNESS_HOST, help="SSH/SCP target for Harness.")
    parser.add_argument("--theta-path", default=DEFAULT_THETA_PATH, help="theta_config.json path on Harness.")
    parser.add_argument("--node-config-path", default=DEFAULT_NODE_CONFIG_PATH, help="node_config path on Harness.")
    parser.add_argument("--thermal-log", action="store_true", help="Record inference-node thermal status around formal execution.")
    parser.add_argument("--thermal-output-dir", default=DEFAULT_THERMAL_OUTPUT_DIR, help="Directory for thermal JSONL artifacts.")
    parser.add_argument(
        "--failed-archive-dir",
        default=DEFAULT_FAILED_ARCHIVE_DIR,
        help="Directory for failed-run JSONL/thermal/summary artifacts.",
    )
    parser.add_argument(
        "--no-failed-db-purge",
        action="store_true",
        help="Preserve failed-run DB rows; archive failure evidence and stop for review.",
    )
    parser.add_argument("--thermal-interval-sec", type=float, default=1.0, help="Thermal sampling interval during execution.")
    parser.add_argument("--thermal-cooldown-sec", type=float, default=10.0, help="Continue thermal sampling after stage completion.")
    parser.add_argument(
        "--node-local-thermal-log",
        action="store_true",
        help="Start a local thermal recorder on each inference node so crash/reboot evidence can be recovered later.",
    )
    parser.add_argument(
        "--node-local-thermal-dir",
        default="/home/lacp/lacp_node_thermal",
        help="Persistent directory on inference nodes for local thermal JSONL logs.",
    )
    parser.add_argument(
        "--node-local-thermal-interval-sec",
        type=float,
        default=2.0,
        help="Sampling interval for node-local thermal recorders.",
    )
    parser.add_argument("--turn-timeout-sec", type=float, default=300.0, help="Maximum seconds to wait for one Harness /turn call.")
    parser.add_argument("--turn-cooldown-every", type=int, default=0, help="Pause after every N scenario turns; 0 disables.")
    parser.add_argument("--turn-cooldown-sec", type=float, default=0.0, help="Cooldown seconds for --turn-cooldown-every.")
    parser.add_argument("--segment-every", type=int, default=0, help="Run a segment boundary hook after every N turns; 0 disables.")
    parser.add_argument("--segment-cooldown-sec", type=float, default=0.0, help="Cooldown seconds at each segment boundary.")
    parser.add_argument("--inter-run-cooldown-sec", type=float, default=0.0, help="Cooldown seconds between successful repetitions.")
    parser.add_argument("--segment-settle-sec", type=float, default=0.0, help="Settle seconds after segment runner unload.")
    parser.add_argument("--segment-unload-runners", action="store_true", help="Request Ollama keep_alive=0 unload at segment boundaries.")
    parser.add_argument("--segment-unload-timeout-sec", type=float, default=30.0, help="Timeout seconds for each segment unload request.")
    parser.add_argument("--inference-hosts", default=DEFAULT_INFERENCE_HOSTS, help="Comma-separated inference host IPs for segment runner unload.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="Model name to unload during cleanup hooks.")
    parser.add_argument("--pre-run-unload-runners", action="store_true", help="Unload inference runners before each formal run starts.")
    parser.add_argument("--pre-run-settle-sec", type=float, default=20.0, help="Settle seconds after pre-run runner unload.")
    parser.add_argument("--pre-run-readiness-probe", action="store_true", help="Run a DB-free direct inference probe on each inference node before the run.")
    parser.add_argument("--pre-run-readiness-timeout-sec", type=float, default=90.0, help="Timeout seconds for each pre-run readiness probe.")
    parser.add_argument("--pre-run-readiness-max-tokens", type=int, default=64, help="Max tokens for each pre-run readiness probe.")
    parser.add_argument(
        "--pre-run-post-readiness-unload",
        action="store_true",
        help="Unload runners and require /api/ps empty after readiness before the first formal turn.",
    )
    parser.add_argument(
        "--pre-run-post-readiness-settle-sec",
        type=float,
        default=10.0,
        help="Settle seconds after post-readiness unload before checking /api/ps.",
    )
    parser.add_argument(
        "--failure-cooldown-sec",
        type=float,
        default=120.0,
        help="Reserved cooldown seconds for manually approved retry workflows.",
    )
    parser.add_argument(
        "--max-run-attempts",
        type=int,
        default=1,
        help="Maximum attempts per logical stage repetition. Formal failures stop for user/code review by default.",
    )
    parser.add_argument(
        "--thermal-nodes",
        default=DEFAULT_THERMAL_NODES,
        help="Comma-separated SSH targets to sample; use label=host to preserve node names.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without sending turns.")
    return parser.parse_args()


class ThermalRecorder:
    def __init__(
        self,
        run_id: str,
        output_dir: Path,
        nodes: tuple[tuple[str, str], ...],
        interval_sec: float,
        cooldown_sec: float,
    ) -> None:
        self.run_id = run_id
        self.output_dir = output_dir
        self.nodes = nodes
        self.interval_sec = interval_sec
        self.cooldown_sec = cooldown_sec
        self.path = output_dir / f"{run_id}_thermal.jsonl"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write(
            {
                "event": "thermal_logger_start",
                "run_id": self.run_id,
                "nodes": [{"label": label, "ssh_host": host} for label, host in self.nodes],
                "interval_sec": self.interval_sec,
                "cooldown_sec": self.cooldown_sec,
                "timestamp": now_iso(),
            }
        )
        self.snapshot("pre_stage_idle_snapshot")
        self._thread = threading.Thread(target=self._loop, name=f"thermal-{self.run_id}", daemon=True)
        self._thread.start()

    def snapshot(self, event: str) -> None:
        for row in self._sample_all(event):
            self._write(row)

    def stop(self) -> None:
        self.snapshot("post_stage_immediate_snapshot")
        if self.cooldown_sec > 0:
            self._write(
                {
                    "event": "thermal_cooldown_start",
                    "run_id": self.run_id,
                    "cooldown_sec": self.cooldown_sec,
                    "timestamp": now_iso(),
                }
            )
            self._stop.wait(self.cooldown_sec)
            self.snapshot("post_stage_cooldown_snapshot")
            self._write(
                {
                    "event": "thermal_cooldown_end",
                    "run_id": self.run_id,
                    "cooldown_sec": self.cooldown_sec,
                    "timestamp": now_iso(),
                }
            )
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(10.0, self.interval_sec * 8))
        self._write({"event": "thermal_logger_stop", "run_id": self.run_id, "timestamp": now_iso()})

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            for row in self._sample_all("thermal_sample"):
                self._write(row)
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.interval_sec - elapsed))

    def _sample_all(self, event: str) -> list[dict[str, object]]:
        with ThreadPoolExecutor(max_workers=max(1, len(self.nodes))) as executor:
            futures = [
                executor.submit(sample_thermal_node, self.run_id, event, label, host)
                for label, host in self.nodes
            ]
            return [future.result() for future in as_completed(futures)]

    def _write(self, row: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


class NodeLocalThermalRecorder:
    def __init__(
        self,
        run_id: str,
        nodes: tuple[tuple[str, str], ...],
        remote_dir: str,
        interval_sec: float,
    ) -> None:
        self.run_id = run_id
        self.nodes = nodes
        self.remote_dir = remote_dir.rstrip("/")
        self.interval_sec = interval_sec
        self.records: list[dict[str, object]] = []

    def start(self) -> None:
        for label, host in self.nodes:
            remote_path = self.remote_log_path(label)
            pid_path = self.remote_pid_path(label)
            err_path = f"{remote_path}.stderr"
            inner_command = (
                f"mkdir -p {shlex.quote(self.remote_dir)} && "
                f"nohup python3 -u -c {shlex.quote(node_local_thermal_code())} "
                f"{shlex.quote(self.run_id)} {shlex.quote(label)} {shlex.quote(str(self.interval_sec))} "
                f"> {shlex.quote(remote_path)} 2> {shlex.quote(err_path)} < /dev/null & "
                f"echo $! > {shlex.quote(pid_path)}"
            )
            command = f"bash -lc {shlex.quote(inner_command)} >/dev/null 2>&1 &"
            proc = ssh(host, command, timeout=10)
            pid_check = ssh(
                host,
                (
                    f"for i in $(seq 1 20); do "
                    f"test -s {shlex.quote(pid_path)} && exit 0; "
                    f"sleep 0.25; "
                    f"done; "
                    f"exit 1"
                ),
                timeout=10,
            )
            self.records.append(
                {
                    "label": label,
                    "host": host,
                    "remote_path": remote_path,
                    "pid_path": pid_path,
                    "stderr_path": err_path,
                    "started": proc.returncode == 0 and pid_check.returncode == 0,
                    "start_returncode": proc.returncode,
                    "start_stderr": proc.stderr.strip(),
                    "pid_check_returncode": pid_check.returncode,
                    "pid_check_stderr": pid_check.stderr.strip(),
                }
            )

    def stop(self) -> None:
        for record in self.records:
            host = str(record["host"])
            label = str(record["label"])
            pid_path = str(record["pid_path"])
            command = (
                f"pid_file={shlex.quote(pid_path)}; "
                f"run_id={shlex.quote(self.run_id)}; "
                f"node_label={shlex.quote(label)}; "
                f"pids=$(ps -eo pid=,comm=,args= | awk -v rid=\"$run_id\" -v node=\"$node_label\" "
                f"'$2 == \"python3\" && $0 ~ rid && $0 ~ node {{print $1}}'); "
                f"if test -z \"$pids\" && test -s \"$pid_file\"; then "
                f"  pids=$(cat \"$pid_file\"); "
                f"fi; "
                f"if test -n \"$pids\"; then "
                f"  kill $pids 2>/dev/null || true; "
                f"fi; "
                f"sleep 0.5; "
                f"remaining=$(ps -eo pid=,comm=,args= | awk -v rid=\"$run_id\" -v node=\"$node_label\" "
                f"'$2 == \"python3\" && $0 ~ rid && $0 ~ node {{print $0}}'); "
                f"if test -n \"$remaining\"; then "
                f"  printf '%s\\n' \"$remaining\"; "
                f"  exit 3; "
                f"fi"
            )
            proc = ssh(host, command, timeout=10)
            record["stop_returncode"] = proc.returncode
            record["stop_stdout"] = proc.stdout.strip()
            record["stop_stderr"] = proc.stderr.strip()

    def collect(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": self.run_id,
            "remote_dir": self.remote_dir,
            "interval_sec": self.interval_sec,
            "records": self.records,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        for record in self.records:
            label = str(record["label"])
            host = str(record["host"])
            for key, suffix in (("remote_path", "jsonl"), ("stderr_path", "stderr")):
                remote_path = str(record[key])
                local_path = output_dir / f"{self.run_id}_{label}_node_local_thermal.{suffix}"
                proc = subprocess.run(["scp", f"{host}:{remote_path}", str(local_path)], check=False, text=True, capture_output=True)
                record[f"collect_{suffix}_returncode"] = proc.returncode
                record[f"collect_{suffix}_stderr"] = proc.stderr.strip()
        (output_dir / f"{self.run_id}_node_local_thermal_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def remote_log_path(self, label: str) -> str:
        return f"{self.remote_dir}/{self.run_id}_{label}_thermal.jsonl"

    def remote_pid_path(self, label: str) -> str:
        return f"{self.remote_log_path(label)}.pid"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def run_command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            args,
            124,
            stdout=stdout,
            stderr=(stderr + f"\nTimeoutExpired after {timeout}s").strip(),
        )


def ssh(host: str, remote_command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run_command(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_command], timeout=timeout)


def parse_thermal_nodes(raw: str) -> tuple[tuple[str, str], ...]:
    nodes = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if "=" in value:
            label, host = value.split("=", 1)
            nodes.append((label.strip(), host.strip()))
        else:
            nodes.append((value, value))
    return tuple((label, host) for label, host in nodes if label and host)


def parse_inference_hosts(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def sample_thermal_node(run_id: str, event: str, node: str, ssh_host: str) -> dict[str, object]:
    proc = ssh(ssh_host, remote_temperature_command(), timeout=8)
    base: dict[str, object] = {
        "event": event,
        "run_id": run_id,
        "timestamp": now_iso(),
        "node": node,
        "ssh_host": ssh_host,
        "reachable": proc.returncode == 0,
        "returncode": proc.returncode,
    }
    if proc.returncode != 0:
        return {**base, "max_temp_c": None, "temperatures": [], "stderr": proc.stderr.strip()}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {**base, "max_temp_c": None, "temperatures": [], "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    return {**base, **payload, "stderr": proc.stderr.strip()}


def remote_temperature_command() -> str:
    code = r"""
import glob,json,os
temps=[]
for path in sorted(glob.glob('/sys/class/hwmon/hwmon*/temp*_input')):
    try:
        raw=open(path, encoding='utf-8').read().strip()
        value=float(raw)
        temp_c=value/1000.0 if value > 1000 else value
        hwmon_dir=os.path.dirname(path)
        name_path=os.path.join(hwmon_dir, 'name')
        name=open(name_path, encoding='utf-8').read().strip() if os.path.exists(name_path) else os.path.basename(hwmon_dir)
        label_path=path[:-6] + '_label'
        label=open(label_path, encoding='utf-8').read().strip() if os.path.exists(label_path) else os.path.basename(path)
        temps.append({'source': path, 'device': name, 'label': label, 'temp_c': round(temp_c, 3)})
    except Exception as exc:
        temps.append({'source': path, 'error': f'{type(exc).__name__}: {exc}'})
for path in sorted(glob.glob('/sys/class/thermal/thermal_zone*/temp')):
    try:
        raw=open(path, encoding='utf-8').read().strip()
        value=float(raw)
        temp_c=value/1000.0 if value > 1000 else value
        zone=os.path.basename(os.path.dirname(path))
        type_path=os.path.join(os.path.dirname(path), 'type')
        label=open(type_path, encoding='utf-8').read().strip() if os.path.exists(type_path) else zone
        temps.append({'source': path, 'device': 'thermal_zone', 'label': label, 'temp_c': round(temp_c, 3)})
    except Exception as exc:
        temps.append({'source': path, 'error': f'{type(exc).__name__}: {exc}'})
valid=[item['temp_c'] for item in temps if isinstance(item.get('temp_c'), (int, float))]
print(json.dumps({'max_temp_c': max(valid) if valid else None, 'temperatures': temps}, ensure_ascii=False))
"""
    return "python3 -c " + shlex.quote(code)


def node_local_thermal_code() -> str:
    return r"""
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

run_id = sys.argv[1]
node = sys.argv[2]
interval_sec = float(sys.argv[3])

def read_temperatures():
    temps = []
    for path in sorted(glob.glob('/sys/class/hwmon/hwmon*/temp*_input')):
        try:
            raw = open(path, encoding='utf-8').read().strip()
            value = float(raw)
            temp_c = value / 1000.0 if value > 1000 else value
            hwmon_dir = os.path.dirname(path)
            name_path = os.path.join(hwmon_dir, 'name')
            name = open(name_path, encoding='utf-8').read().strip() if os.path.exists(name_path) else os.path.basename(hwmon_dir)
            label_path = path[:-6] + '_label'
            label = open(label_path, encoding='utf-8').read().strip() if os.path.exists(label_path) else os.path.basename(path)
            temps.append({'source': path, 'device': name, 'label': label, 'temp_c': round(temp_c, 3)})
        except Exception as exc:
            temps.append({'source': path, 'error': f'{type(exc).__name__}: {exc}'})
    for path in sorted(glob.glob('/sys/class/thermal/thermal_zone*/temp')):
        try:
            raw = open(path, encoding='utf-8').read().strip()
            value = float(raw)
            temp_c = value / 1000.0 if value > 1000 else value
            zone_dir = os.path.dirname(path)
            type_path = os.path.join(zone_dir, 'type')
            label = open(type_path, encoding='utf-8').read().strip() if os.path.exists(type_path) else os.path.basename(zone_dir)
            temps.append({'source': path, 'device': 'thermal_zone', 'label': label, 'temp_c': round(temp_c, 3)})
        except Exception as exc:
            temps.append({'source': path, 'error': f'{type(exc).__name__}: {exc}'})
    valid = [item['temp_c'] for item in temps if isinstance(item.get('temp_c'), (int, float))]
    return {'max_temp_c': max(valid) if valid else None, 'temperatures': temps}

while True:
    payload = {
        'event': 'node_local_thermal_sample',
        'run_id': run_id,
        'node': node,
        'timestamp': datetime.now(timezone.utc).astimezone().isoformat(),
    }
    payload.update(read_temperatures())
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    time.sleep(interval_sec)
"""


def direct_post_json(endpoint: str, payload: dict[str, object], timeout_sec: float) -> tuple[int, dict[str, object], str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(text)
            except Exception:
                data = {"raw_text": text}
            return response.status, data, text[:500]
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = {"raw_text": text}
        return exc.code, data, text[:500]
    except Exception as exc:
        return 599, {"error": f"{type(exc).__name__}: {exc}"}, ""


def direct_get_json(endpoint: str, timeout_sec: float) -> tuple[int, dict[str, object], str]:
    request = urllib.request.Request(endpoint, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(text)
            except Exception:
                data = {"raw_text": text}
            return response.status, data, text[:500]
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = {"raw_text": text}
        return exc.code, data, text[:500]
    except Exception as exc:
        return 599, {"error": f"{type(exc).__name__}: {exc}"}, ""


def unload_inference_runners(hosts: tuple[str, ...], model_name: str, timeout_sec: float, label: str) -> None:
    if not hosts:
        raise RuntimeError("pre-run runner unload requires at least one inference host")
    payload = {"model": model_name, "prompt": "", "stream": False, "keep_alive": 0}
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, len(hosts))) as executor:
        futures = {
            executor.submit(direct_post_json, f"http://{host}:11434/api/generate", payload, timeout_sec): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            status, data, _text = future.result()
            if status >= 400:
                failed.append(f"{host}:status={status}:response={data}")
            else:
                print(f"{label}_unload_ok host={host} status={status}")
    if failed:
        raise RuntimeError(f"{label} inference runner unload failed: {', '.join(failed)}")


def verify_inference_ps_empty(hosts: tuple[str, ...], timeout_sec: float, label: str) -> None:
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, len(hosts))) as executor:
        futures = {
            executor.submit(direct_get_json, f"http://{host}:11434/api/ps", timeout_sec): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            status, data, _text = future.result()
            models = data.get("models") if isinstance(data, dict) else None
            if status >= 400 or models != []:
                failed.append(f"{host}:status={status}:models={models}:response={data}")
            else:
                print(f"{label}_api_ps_empty host={host} status={status}")
    if failed:
        raise RuntimeError(f"{label} /api/ps empty check failed: {', '.join(failed)}")


def readiness_probe_inference_nodes(
    hosts: tuple[str, ...],
    model_name: str,
    timeout_sec: float,
    max_tokens: int,
) -> None:
    if not hosts:
        raise RuntimeError("pre-run readiness probe requires at least one inference host")
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "You are a readiness probe. Reply in Korean with exactly one short sentence.",
            },
            {"role": "user", "content": "준비 상태를 한 문장으로만 확인하세요."},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": int(max_tokens),
        "logprobs": True,
        "top_logprobs": 5,
        "think": False,
    }
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, len(hosts))) as executor:
        futures = {
            executor.submit(
                direct_post_json,
                f"http://{host}:11434/v1/chat/completions",
                payload,
                timeout_sec,
            ): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            status, data, text_prefix = future.result()
            choices = data.get("choices") if isinstance(data, dict) else None
            choice = choices[0] if isinstance(choices, list) and choices else {}
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            if status >= 400 or not choices:
                failed.append(f"{host}:status={status}:finish={finish_reason}:response={data or text_prefix}")
            else:
                print(f"pre_run_readiness_ok host={host} status={status} finish_reason={finish_reason}")
    if failed:
        raise RuntimeError(f"pre-run readiness probe failed: {', '.join(failed)}")


def pre_run_readiness_gate(args: argparse.Namespace, inference_hosts: tuple[str, ...]) -> None:
    if (
        not args.pre_run_unload_runners
        and not args.pre_run_readiness_probe
        and not args.pre_run_post_readiness_unload
    ):
        return
    print("pre_run_gate_start")
    if args.pre_run_unload_runners:
        unload_inference_runners(
            inference_hosts,
            args.model_name,
            args.segment_unload_timeout_sec,
            "pre_run",
        )
    if args.pre_run_settle_sec > 0:
        print(f"pre_run_settle_start seconds={args.pre_run_settle_sec}")
        time.sleep(args.pre_run_settle_sec)
        print("pre_run_settle_done")
    if args.pre_run_readiness_probe:
        readiness_probe_inference_nodes(
            inference_hosts,
            args.model_name,
            args.pre_run_readiness_timeout_sec,
            args.pre_run_readiness_max_tokens,
        )
    if args.pre_run_post_readiness_unload:
        unload_inference_runners(
            inference_hosts,
            args.model_name,
            args.segment_unload_timeout_sec,
            "post_readiness",
        )
        if args.pre_run_post_readiness_settle_sec > 0:
            print(f"post_readiness_settle_start seconds={args.pre_run_post_readiness_settle_sec}")
            time.sleep(args.pre_run_post_readiness_settle_sec)
            print("post_readiness_settle_done")
        verify_inference_ps_empty(inference_hosts, args.segment_unload_timeout_sec, "post_readiness")
    print("pre_run_gate_done")


def dblog_kst_stamp() -> str:
    host = os.environ.get("LACP_DB_HOST", DEFAULT_DB_HOST)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "date", "+%Y%m%dT%H%M%SKST"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "failed to read dblog KST clock")
    stamp = proc.stdout.strip()
    if not stamp.endswith("KST"):
        raise RuntimeError(f"unexpected dblog timestamp: {stamp}")
    return stamp


def make_run_id(prefix: str, repetition: int, attempt: int = 1) -> str:
    stamp = dblog_kst_stamp()
    suffix = f"_attempt{attempt:02d}" if attempt > 1 else ""
    if "#x" in prefix:
        return f"{prefix.replace('#x', f'#{repetition}')}_{stamp}{suffix}"
    return f"{prefix}_{stamp}#{repetition}{suffix}"


def expected_turns(scenario: str, max_turns: Optional[int]) -> int:
    data = load_scenario(scenario)
    total = len(data["turns"])
    return total if max_turns is None else min(max_turns, total)


def validate_cf_f_default_runtime_contract(args: argparse.Namespace, condition: str) -> None:
    if args.stage != "cf_f" or condition != "cf_f":
        return
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    forced = scenario.get("forced_turn_set_default")
    if forced != CF_F_DEFAULT_FORCED_TURNS:
        raise RuntimeError(
            "CF-F scenario forced_turn_set_default mismatch: "
            f"expected={CF_F_DEFAULT_FORCED_TURNS} got={forced}"
        )
    if scenario.get("turn_30_forced") is not False:
        raise RuntimeError("CF-F default scenario must record turn_30_forced=false")
    turns = scenario.get("turns", [])
    if len(turns) < 30:
        raise RuntimeError("CF-F scenario must contain at least 30 turns")
    for human_turn in (1, 29, 30):
        actual = turns[human_turn - 1].get("turn_no")
        if actual != human_turn:
            raise RuntimeError(
                "CF-F scenario turn indexing must be 1-based: "
                f"scenario[{human_turn - 1}].turn_no={actual}, expected={human_turn}"
            )
    remote_check = (
        "python3 - <<'PY'\n"
        "import json\n"
        f"path={json.dumps(args.node_config_path)}\n"
        f"expected={json.dumps(CF_F_DEFAULT_FORCED_TURNS)}\n"
        "data=json.load(open(path, encoding='utf-8'))\n"
        "cf=data.get('counterfactual', {}).get('cf_f', {})\n"
        "turns=cf.get('injection_turns')\n"
        "if turns != expected:\n"
        "    raise SystemExit(f'CF-F remote injection_turns mismatch: expected={expected} got={turns}')\n"
        "if cf.get('turn_30_forced') is not False:\n"
        "    raise SystemExit('CF-F remote turn_30_forced must be false')\n"
        "print('cf_f_runtime_contract_ok forced_turns=' + ','.join(map(str, turns)))\n"
        "PY"
    )
    proc = subprocess.run(["ssh", args.harness_host, remote_check], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"CF-F remote runtime contract check failed: {proc.stderr.strip() or proc.stdout.strip()}")
    print(proc.stdout.strip())


def db_count_query(run_id: str) -> str:
    quoted_run_id = sql_quote(run_id)
    return (
        f"SELECT 'experiment_runs', COUNT(*) FROM experiment_runs WHERE run_id={quoted_run_id} "
        f"UNION ALL SELECT 'turn_node_logs', COUNT(*) FROM v_turn_node_logs WHERE run_id={quoted_run_id} "
        f"UNION ALL SELECT 'intervention_logs', COUNT(*) FROM v_intervention_logs WHERE run_id={quoted_run_id} "
        f"UNION ALL SELECT 'metric_logs', COUNT(*) FROM v_metric_logs WHERE run_id={quoted_run_id} "
        f"UNION ALL SELECT 'payload_audit_logs', COUNT(*) FROM v_payload_audit_logs WHERE run_id={quoted_run_id}"
    )


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def run_mysql_query(query: str) -> str:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for dblog queries")
    if shutil.which("mysql") is None:
        try:
            return run_mysql_query_via_ssh_mysql(query)
        except Exception as ssh_exc:
            try:
                return run_mysql_query_via_pymysql(query)
            except Exception as pymysql_exc:
                raise RuntimeError(
                    f"dblog query failed via ssh mysql ({ssh_exc}) and pymysql ({pymysql_exc})"
                ) from pymysql_exc
    command = [
        "mysql",
        f"-h{DEFAULT_DB_HOST}",
        f"-u{DEFAULT_DB_USER}",
        f"--password={DEFAULT_DB_PASSWORD}",
        DEFAULT_DB_NAME,
        "-N",
        "-B",
        "-e",
        query,
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"dblog query failed: {proc.stderr.strip()}")
    return proc.stdout


def run_mysql_query_via_ssh_mysql(query: str) -> str:
    query_b64 = base64.b64encode(query.encode("utf-8")).decode("ascii")
    remote = (
        "set -euo pipefail; "
        f"query=$(printf %s {shlex.quote(query_b64)} | /usr/bin/base64 -d); "
        f"MYSQL_PWD={shlex.quote(DEFAULT_DB_PASSWORD)} "
        f"mysql -u{shlex.quote(DEFAULT_DB_USER)} {shlex.quote(DEFAULT_DB_NAME)} -N -B -e \"$query\""
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", DEFAULT_DB_HOST, remote],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def run_mysql_query_via_pymysql(query: str) -> str:
    query_b64 = base64.b64encode(query.encode("utf-8")).decode("ascii")
    code = r"""
import base64
import os
import pymysql
from pymysql.constants import CLIENT

query = base64.b64decode(os.environ["LACP_QUERY_B64"]).decode("utf-8")
conn = pymysql.connect(
    host=os.environ.get("LACP_DB_HOST", "dblog"),
    user=os.environ.get("LACP_DB_USER", "morophi"),
    password=os.environ["LACP_DB_PASSWORD"],
    database=os.environ.get("LACP_DB_NAME", "lacp_db_final"),
    client_flag=CLIENT.MULTI_STATEMENTS,
)
try:
    with conn.cursor() as cur:
        cur.execute(query)
        while True:
            if cur.description:
                for row in cur.fetchall():
                    print("\t".join("" if value is None else str(value) for value in row))
            if not cur.nextset():
                break
    conn.commit()
finally:
    conn.close()
"""
    env = dict(os.environ)
    env["LACP_DB_PASSWORD"] = DEFAULT_DB_PASSWORD
    env.setdefault("LACP_DB_NAME", DEFAULT_DB_NAME)
    env["LACP_QUERY_B64"] = query_b64
    proc = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"dblog query via pymysql failed: {proc.stderr.strip()}")
    return proc.stdout


def check_db_rows(run_id: str, turns: int, expected_nodes: int) -> None:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for dblog row-count checks")
    expected_node_rows = turns * expected_nodes
    counts = {}
    for line in run_mysql_query(db_count_query(run_id)).splitlines():
        if not line.strip():
            continue
        table, value = line.split("\t", 1)
        counts[table] = int(value)
    expected = {
        "experiment_runs": 1,
        "turn_node_logs": expected_node_rows,
        "intervention_logs": expected_node_rows,
        "metric_logs": expected_node_rows,
        "payload_audit_logs": expected_node_rows,
    }
    mismatches = {key: (counts.get(key), value) for key, value in expected.items() if counts.get(key) != value}
    if mismatches:
        raise RuntimeError(f"dblog row-count mismatch for {run_id}: {mismatches}")
    print(f"db_check ok run_id={run_id} turns={turns} node_rows={expected_node_rows}")


def format_failure_reason(run_id: str, args: argparse.Namespace, attempt: int, exc: Exception) -> str:
    payload = {
        "run_id": run_id,
        "stage": args.stage,
        "scenario": args.scenario,
        "attempt": attempt,
        "max_run_attempts": args.max_run_attempts,
        "db_rows_preserved": bool(args.no_failed_db_purge),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    text = json.dumps(payload, ensure_ascii=False)
    return text[:60000]


def update_experiment_run_status(run_id: str, status: str, failure_reason: Optional[str] = None) -> None:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for experiment run status updates")
    if failure_reason is None:
        failure_expr = "failure_reason=NULL"
    else:
        failure_expr = f"failure_reason={sql_quote(failure_reason)}"
    query = f"""
UPDATE experiment_runs
SET acceptance_status={sql_quote(status)},
    {failure_expr},
    completed_at=CURRENT_TIMESTAMP()
WHERE run_id={sql_quote(run_id)};
SELECT ROW_COUNT();
"""
    output = [line.strip() for line in run_mysql_query(query).splitlines() if line.strip()]
    affected = int(output[-1]) if output else 0
    if affected != 1:
        raise RuntimeError(f"experiment_runs status update affected {affected} rows for {run_id}")
    print(f"db_status_update ok run_id={run_id} acceptance_status={status}")


def purge_db_run(run_id: str) -> dict[str, int]:
    if not DEFAULT_DB_PASSWORD:
        raise RuntimeError("LACP_DB_PASSWORD must be set for failed-run DB purge")
    query = f"""
SET @run_pk = NULL;
START TRANSACTION;
SELECT id INTO @run_pk FROM experiment_runs WHERE run_id = {sql_quote(run_id)} LIMIT 1;
SELECT COUNT(*) INTO @experiment_runs_before FROM experiment_runs WHERE id = @run_pk;
SELECT COUNT(*) INTO @turn_node_logs_before FROM turn_node_logs WHERE experiment_run_id = @run_pk;
SELECT COUNT(*) INTO @payload_audit_logs_before
FROM payload_audit_logs p JOIN turn_node_logs t ON t.id = p.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
SELECT COUNT(*) INTO @intervention_logs_before
FROM intervention_logs i JOIN turn_node_logs t ON t.id = i.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
SELECT COUNT(*) INTO @metric_logs_before
FROM metric_logs m JOIN turn_node_logs t ON t.id = m.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
DELETE p FROM payload_audit_logs p JOIN turn_node_logs t ON t.id = p.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
DELETE i FROM intervention_logs i JOIN turn_node_logs t ON t.id = i.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
DELETE m FROM metric_logs m JOIN turn_node_logs t ON t.id = m.turn_node_log_id
WHERE t.experiment_run_id = @run_pk;
DELETE FROM turn_node_logs WHERE experiment_run_id = @run_pk;
DELETE FROM experiment_runs WHERE id = @run_pk;
COMMIT;
SET @next_experiment_runs = (SELECT COALESCE(MAX(id), 0) + 1 FROM experiment_runs);
SET @sql = CONCAT('ALTER TABLE experiment_runs AUTO_INCREMENT = ', @next_experiment_runs);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @next_turn_node_logs = (SELECT COALESCE(MAX(id), 0) + 1 FROM turn_node_logs);
SET @sql = CONCAT('ALTER TABLE turn_node_logs AUTO_INCREMENT = ', @next_turn_node_logs);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @next_payload_audit_logs = (SELECT COALESCE(MAX(id), 0) + 1 FROM payload_audit_logs);
SET @sql = CONCAT('ALTER TABLE payload_audit_logs AUTO_INCREMENT = ', @next_payload_audit_logs);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @next_intervention_logs = (SELECT COALESCE(MAX(id), 0) + 1 FROM intervention_logs);
SET @sql = CONCAT('ALTER TABLE intervention_logs AUTO_INCREMENT = ', @next_intervention_logs);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @next_metric_logs = (SELECT COALESCE(MAX(id), 0) + 1 FROM metric_logs);
SET @sql = CONCAT('ALTER TABLE metric_logs AUTO_INCREMENT = ', @next_metric_logs);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SELECT 'experiment_runs', @experiment_runs_before
UNION ALL SELECT 'turn_node_logs', @turn_node_logs_before
UNION ALL SELECT 'payload_audit_logs', @payload_audit_logs_before
UNION ALL SELECT 'intervention_logs', @intervention_logs_before
UNION ALL SELECT 'metric_logs', @metric_logs_before;
"""
    counts: dict[str, int] = {}
    for line in run_mysql_query(query).splitlines():
        if not line.strip():
            continue
        table, value = line.split("\t", 1)
        counts[table] = int(value)
    print(f"db_purge_done run_id={run_id} removed={json.dumps(counts, sort_keys=True)}")
    return counts


def archive_failed_run_artifacts(
    run_id: str,
    args: argparse.Namespace,
    error: Exception,
    thermal_path: Optional[Path],
    node_local_recorder: Optional[NodeLocalThermalRecorder] = None,
) -> Path:
    archive_root = Path(args.failed_archive_dir)
    archive_dir = archive_root / run_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": run_id,
        "stage": args.stage,
        "condition": args.condition or STAGES[args.stage].condition,
        "run_mode": args.run_mode or STAGES[args.stage].run_mode,
        "archived_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": str(error),
        "db_policy": (
            "failed formal run DB rows are preserved"
            if args.no_failed_db_purge
            else "failed formal run rows are purged; failure evidence is preserved only as files"
        ),
    }
    (archive_dir / "failure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (archive_dir / "failure_summary.md").write_text(
        "\n".join(
            [
                "# Failed Run Artifact",
                "",
                f"- run_id: `{run_id}`",
                f"- stage: `{summary['stage']}`",
                f"- condition: `{summary['condition']}`",
                f"- run_mode: `{summary['run_mode']}`",
                f"- archived_at_utc: `{summary['archived_at_utc']}`",
                f"- db_policy: {summary['db_policy']}",
                "",
                "## Error",
                "",
                "```text",
                str(error),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    local_jsonl = Path(f"/home/lacp/harness/logs/runs/{run_id}.jsonl")
    if local_jsonl.exists():
        shutil.copy2(local_jsonl, archive_dir / f"{run_id}.jsonl")
    else:
        remote_jsonl = f"{args.harness_host}:/home/lacp/harness/logs/runs/{run_id}.jsonl"
        subprocess.run(["scp", remote_jsonl, str(archive_dir / f"{run_id}.jsonl")], check=False)
    if thermal_path is not None and thermal_path.exists():
        shutil.copy2(thermal_path, archive_dir / thermal_path.name)
    if node_local_recorder is not None:
        node_local_recorder.collect(archive_dir / "node_local_thermal")
    print(f"failed_run_artifact_archive path={archive_dir}")
    return archive_dir


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile from an empty value set")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def fetch_cr2_metric_values(run_ids: list[str]) -> dict[str, object]:
    run_id_list = ", ".join(sql_quote(run_id) for run_id in run_ids)
    query = f"""
SELECT run_id, turn_no, node, lms_value, cds, ma_assert, metric_status, metrics_json
FROM v_metric_logs
WHERE run_id IN ({run_id_list})
  AND analysis_eligible = 1
  AND COALESCE(exclude_from_causal_trigger, 0) = 0
ORDER BY run_id, turn_no, node
"""
    rows_by_turn: dict[tuple[str, int], dict[str, dict[str, object]]] = {}
    entropy_values: list[float] = []
    for line in run_mysql_query(query).splitlines():
        if not line.strip():
            continue
        run_id, turn_no, node, lms_value, cds, ma_assert, metric_status, metrics_json = line.split("\t", 7)
        status = {} if metric_status in {"", "NULL"} else json.loads(metric_status)
        metrics = {} if metrics_json in {"", "NULL"} else json.loads(metrics_json)
        for item in status.get("lms_token_entropies", []):
            if isinstance(item, (int, float)):
                entropy_values.append(float(item))
        row = {
            "lms_value": _float_or_none(lms_value),
            "cds": _float_or_none(cds),
            "ma_assert": _float_or_none(ma_assert),
            "metric_status": status,
            "metrics": metrics,
        }
        rows_by_turn.setdefault((run_id, int(turn_no)), {})[node] = row

    values = {
        "d_lms_abs": [],
        "d_cds_abs": [],
        "d_ma_abs": [],
        "d_lms_signed": [],
        "d_cds_signed": [],
        "d_ma_signed": [],
    }
    non_trigger_eligible_turns = []
    for (run_id, turn_no), nodes in sorted(rows_by_turn.items()):
        c = nodes.get("C")
        if not c:
            continue
        turn_is_trigger_eligible = False
        for node in ("A", "B"):
            x = nodes.get(node)
            if not x:
                continue
            d_lms = _diff(x.get("lms_value"), c.get("lms_value"), "x_minus_c")
            d_cds = _diff(x.get("cds"), c.get("cds"), "c_minus_x")
            d_ma = _diff(x.get("ma_assert"), c.get("ma_assert"), "x_minus_c")
            if d_lms is not None:
                values["d_lms_abs"].append(abs(d_lms))
                values["d_lms_signed"].append(d_lms)
            if d_cds is not None:
                values["d_cds_abs"].append(abs(d_cds))
                values["d_cds_signed"].append(d_cds)
            if d_ma is not None:
                values["d_ma_abs"].append(abs(d_ma))
                values["d_ma_signed"].append(d_ma)
            if any(value is not None and value > 0.0 for value in (d_lms, d_cds, d_ma)):
                turn_is_trigger_eligible = True
        if not turn_is_trigger_eligible:
            non_trigger_eligible_turns.append(turn_no)

    return {
        "theta_values": values,
        "entropy_values": entropy_values,
        "non_trigger_eligible_turns": sorted(set(non_trigger_eligible_turns)),
    }


def _float_or_none(raw: str) -> Optional[float]:
    if raw in {"", "NULL"}:
        return None
    return float(raw)


def _diff(left: object, right: object, direction: str) -> Optional[float]:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    if direction == "x_minus_c":
        return float(left) - float(right)
    if direction == "c_minus_x":
        return float(right) - float(left)
    raise ValueError(f"unsupported differential direction: {direction}")


def fetch_cr2_run_metadata(run_ids: list[str]) -> dict[str, object]:
    run_id_list = ", ".join(sql_quote(run_id) for run_id in run_ids)
    query = f"""
SELECT run_id, scenario_hash, node_config_hash, policy_hash
FROM experiment_runs
WHERE run_id IN ({run_id_list})
ORDER BY run_id
"""
    rows = []
    for line in run_mysql_query(query).splitlines():
        if not line.strip():
            continue
        run_id, scenario_hash, node_config_hash, policy_hash = line.split("\t")
        rows.append(
            {
                "run_id": run_id,
                "scenario_hash": None if scenario_hash in {"", "NULL"} else scenario_hash,
                "node_config_hash": None if node_config_hash in {"", "NULL"} else node_config_hash,
                "sc_policy_hash": None if policy_hash in {"", "NULL"} else policy_hash,
            }
        )
    return {
        "runs": rows,
        "scenario_hashes": sorted({row["scenario_hash"] for row in rows if row["scenario_hash"]}),
        "node_config_hashes": sorted({row["node_config_hash"] for row in rows if row["node_config_hash"]}),
        "sc_policy_hashes": sorted({row["sc_policy_hash"] for row in rows if row["sc_policy_hash"]}),
    }


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_theta_config(
    run_ids: list[str],
    calibration: dict[str, object],
    expected_rows: int,
    entropy_percentile: float,
    trigger_percentile: float,
    metadata: dict[str, object],
) -> dict[str, object]:
    if not 0.0 < entropy_percentile < 1.0:
        raise ValueError("--entropy-percentile must be > 0 and < 1")
    if not 0.0 < trigger_percentile < 1.0:
        raise ValueError("--trigger-percentile must be > 0 and < 1")
    values = calibration["theta_values"]
    entropy_values = calibration["entropy_values"]
    if not isinstance(values, dict) or not isinstance(entropy_values, list):
        raise TypeError("invalid CR2 calibration payload")
    counts = {key: len(items) for key, items in values.items()}
    missing = {key: (count, expected_rows) for key, count in counts.items() if count < expected_rows}
    if missing:
        raise RuntimeError(f"CR2 theta freeze blocked; insufficient eligible metric rows: {missing}")
    if not entropy_values:
        raise RuntimeError(
            "CR2 theta freeze blocked; no lms_token_entropies found. "
            "Re-run CR2 with the updated Harness metrics logger."
        )
    d_ma_values = values.get("d_ma_abs", [])
    theta_ma_status = "frozen"
    theta_ma_evidence_enabled = True
    if _is_degenerate_metric(d_ma_values):
        theta_ma_status = "descriptive_fallback"
        theta_ma_evidence_enabled = False

    return {
        "theta_entropy": percentile(entropy_values, entropy_percentile),
        "theta_lms": percentile(values["d_lms_abs"], trigger_percentile),
        "theta_cds": percentile(values["d_cds_abs"], trigger_percentile),
        "theta_ma": percentile(values["d_ma_abs"], trigger_percentile),
        "theta_ma_status": theta_ma_status,
        "theta_ma_threshold_evidence_enabled": theta_ma_evidence_enabled,
        "source": "CR2",
        "locked": True,
        "cr2_run_id": run_ids,
        "percentile_rule": {
            "theta_entropy": entropy_percentile,
            "theta_lms": trigger_percentile,
            "theta_cds": trigger_percentile,
            "theta_ma": trigger_percentile,
        },
        "direction_convention": {
            "d_lms": "LMS_X - LMS_C for X in {A,B}; trigger threshold exceedance when abs(d_lms) > theta_lms",
            "d_cds": "CDS_C - CDS_X for X in {A,B}; trigger threshold exceedance when abs(d_cds) > theta_cds",
            "d_ma": "MA_assert_X - MA_assert_C for X in {A,B}; trigger governance monitors abs(d_ma) > theta_ma; supporting-evidence interpretation is sign-aware and treats reduced unsafe assertiveness as the RBC/SC-supportive direction",
            "trigger_threshold_basis": "empirical percentile of absolute CR2 Node C-relative differentials",
            "supporting_evidence_rule": "Run B/CF supporting counts must be evaluated only in the pre-registered intervention-oriented direction; opposite-direction absolute exceedance is a deviation, not supportive evidence.",
        },
        "calibration": {
            "algorithm": "cr2_oriented_differential_percentile_v2_pooled_shared_floor",
            "pooled_shared_floor": True,
            "condition_specific_threshold_tuning": False,
            "theta_ma_status": theta_ma_status,
            "theta_ma_threshold_evidence_enabled": theta_ma_evidence_enabled,
            "rules": {
                "theta_entropy": "70th percentile of CR2 natural RAG-off token entropy distribution",
                "theta_lms": "95th percentile of |LMS_X - LMS_C| for X in {A,B}",
                "theta_cds": "95th percentile of |CDS_C - CDS_X| for X in {A,B}",
                "theta_ma": "95th percentile of |MA_assert_X - MA_assert_C| for X in {A,B}; if degenerate, MA is descriptive/non-thresholded for supporting-evidence reporting while the numeric value remains present for trigger-config compatibility.",
            },
            "run_ids": run_ids,
            "expected_rows_per_metric": expected_rows,
            "metric_counts": counts,
            "entropy_token_count": len(entropy_values),
            "non_trigger_eligible_turns": calibration.get("non_trigger_eligible_turns", []),
            "run_metadata": metadata,
            "script_sha256": file_sha256(Path(__file__)),
            "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "node_config_hash": metadata.get("node_config_hashes", []),
        "sc_policy_hash": metadata.get("sc_policy_hashes", []),
        "corpus_hash": metadata.get("scenario_hashes", []),
        "code_git_sha": git_sha(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notes": "Auto-frozen after CR2 by run_experiment_stage.py. Required for final Run B and CF execution.",
    }


def _is_degenerate_metric(values: object) -> bool:
    if not isinstance(values, list) or not values:
        return True
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return True
    return max(numeric) - min(numeric) <= 1e-12


def git_sha() -> Optional[str]:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def write_local_theta(theta: dict[str, object], prefix: str) -> Path:
    path = Path(f"/tmp/{prefix}_theta_config_{int(time.time())}.json")
    path.write_text(json.dumps(theta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def install_theta_config(theta_path: Path, harness_host: str, remote_theta_path: str) -> None:
    remote_tmp = f"{remote_theta_path}.tmp.{int(time.time())}.{os.getpid()}"
    subprocess.run(["scp", str(theta_path), f"{harness_host}:{remote_tmp}"], check=True)
    stamp = dblog_kst_stamp()
    remote_cmd = (
        f"set -e; "
        f"cp {remote_theta_path} {remote_theta_path}.bak.{stamp}; "
        f"mv {remote_tmp} {remote_theta_path}; "
        f"systemctl --user restart lacp-harness.service; "
        f"systemctl --user is-active lacp-harness.service"
    )
    subprocess.run(["ssh", harness_host, remote_cmd], check=True)


def install_cf_f_non_trigger_turns(
    harness_host: str,
    remote_node_config_path: str,
    non_trigger_eligible_turns: list[int],
) -> None:
    if not non_trigger_eligible_turns:
        raise RuntimeError("CF-F config update blocked; CR2 produced no non-trigger-eligible turns")
    code = r"""
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
turns = json.loads(sys.argv[2])
data = json.loads(path.read_text(encoding="utf-8"))
cf_f = data.setdefault("counterfactual", {}).setdefault("cf_f", {})
cf_f["non_trigger_eligible_turns"] = turns
if not cf_f.get("injection_turns"):
    cf_f["injection_turns"] = []
stamp = time.strftime("%Y%m%dT%H%M%SKST", time.localtime())
backup = path.with_name(path.name + f".bak.cf_f.{stamp}")
backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"cf_f_non_trigger_turns_updated path={path} count={len(turns)} backup={backup}")
"""
    remote_cmd = " ".join(
        [
            "set -e;",
            "python3",
            "-c",
            shlex.quote(code),
            shlex.quote(remote_node_config_path),
            shlex.quote(json.dumps(non_trigger_eligible_turns)),
            ";",
            "systemctl --user restart lacp-harness.service",
            ";",
            "systemctl --user is-active lacp-harness.service",
        ]
    )
    subprocess.run(["ssh", harness_host, remote_cmd], check=True)


def freeze_theta_after_cr2(args: argparse.Namespace, run_ids: list[str], turns: int, repetitions: int) -> None:
    expected_rows = turns * repetitions * 2
    calibration = fetch_cr2_metric_values(run_ids)
    metadata = fetch_cr2_run_metadata(run_ids)
    theta = build_theta_config(
        run_ids,
        calibration,
        expected_rows,
        args.entropy_percentile,
        args.trigger_percentile,
        metadata,
    )
    theta_path = write_local_theta(theta, args.run_id_prefix or "cr2")
    install_theta_config(theta_path, args.harness_host, args.theta_path)
    install_cf_f_non_trigger_turns(
        args.harness_host,
        args.node_config_path,
        theta["calibration"]["non_trigger_eligible_turns"],
    )
    print(
        "theta_freeze_done "
        f"path={args.theta_path} theta_entropy={theta['theta_entropy']:.10g} "
        f"theta_lms={theta['theta_lms']:.10g} "
        f"theta_cds={theta['theta_cds']:.10g} theta_ma={theta['theta_ma']:.10g}"
    )


async def run_stage(args: argparse.Namespace) -> None:
    spec = STAGES[args.stage]
    if args.scenario is None:
        args.scenario = default_scenario_for_stage(args.stage)
    repetitions = args.repetitions if args.repetitions is not None else spec.repetitions
    if repetitions < 1:
        raise ValueError("--repetitions must be >= 1")
    if args.repetition_start_index < 1:
        raise ValueError("--repetition-start-index must be >= 1")
    max_turns = None if args.full_scenario else (args.max_turns if args.max_turns is not None else spec.max_turns)
    condition = args.condition or spec.condition
    run_mode = args.run_mode or spec.run_mode
    prefix = args.run_id_prefix or spec.run_id_prefix
    turns = expected_turns(args.scenario, max_turns)
    validate_cf_f_default_runtime_contract(args, condition)
    thermal_nodes = parse_thermal_nodes(args.thermal_nodes)
    inference_hosts = parse_inference_hosts(args.inference_hosts)
    thermal_recorder = None
    if args.thermal_log:
        if not thermal_nodes:
            raise ValueError("--thermal-nodes must include at least one SSH target when --thermal-log is enabled")
        thermal_run_id = f"{prefix}_{args.stage}_{dblog_kst_stamp()}"
        thermal_recorder = ThermalRecorder(
            thermal_run_id,
            Path(args.thermal_output_dir),
            thermal_nodes,
            args.thermal_interval_sec,
            args.thermal_cooldown_sec,
        )

    print(
        "stage_plan "
        f"stage={args.stage} condition={condition} run_mode={run_mode} "
        f"repetitions={repetitions} repetition_start_index={args.repetition_start_index} "
        f"turns_per_run={turns} causal_evidence={spec.causal_evidence}"
    )
    if thermal_recorder is not None:
        print(
            f"thermal_log_start path={thermal_recorder.path} "
            f"nodes={','.join(label for label, _host in thermal_nodes)}"
        )
        thermal_recorder.start()

    try:
        run_ids = []
        for offset in range(repetitions):
            index = args.repetition_start_index + offset
            attempt = 1
            while True:
                run_id = make_run_id(prefix, index, attempt)
                node_local_recorder = None
                print(f"stage_run_start run_id={run_id} attempt={attempt}/{args.max_run_attempts}")
                if thermal_recorder is not None:
                    thermal_recorder.snapshot(f"pre_run_snapshot:{run_id}")
                try:
                    if args.node_local_thermal_log and not args.dry_run:
                        node_local_recorder = NodeLocalThermalRecorder(
                            run_id,
                            thermal_nodes,
                            args.node_local_thermal_dir,
                            args.node_local_thermal_interval_sec,
                        )
                        node_local_recorder.start()
                        print(
                            "node_local_thermal_start "
                            f"run_id={run_id} dir={args.node_local_thermal_dir} "
                            f"interval_sec={args.node_local_thermal_interval_sec}"
                        )
                    if not args.dry_run:
                        pre_run_readiness_gate(args, inference_hosts)
                        if thermal_recorder is not None:
                            thermal_recorder.snapshot(f"post_pre_run_gate_snapshot:{run_id}")
                        await send_scenario(
                            args.scenario,
                            args.harness_url,
                            run_id,
                            condition,
                            run_mode,
                            max_turns=max_turns,
                            turn_cooldown_every=args.turn_cooldown_every or None,
                            turn_cooldown_sec=args.turn_cooldown_sec,
                            turn_timeout_sec=args.turn_timeout_sec,
                            segment_every=args.segment_every or None,
                            segment_cooldown_sec=args.segment_cooldown_sec,
                            segment_unload_runners=args.segment_unload_runners,
                            segment_settle_sec=args.segment_settle_sec,
                            segment_unload_timeout_sec=args.segment_unload_timeout_sec,
                            inference_hosts=inference_hosts,
                            model_name=args.model_name,
                        )
                        if thermal_recorder is not None:
                            thermal_recorder.snapshot(f"post_run_immediate_snapshot:{run_id}")
                        if node_local_recorder is not None:
                            node_local_recorder.stop()
                            node_local_output = Path(args.thermal_output_dir) / f"{run_id}_node_local"
                            node_local_recorder.collect(node_local_output)
                            print(f"node_local_thermal_collect path={node_local_output}")
                        if not args.skip_db_check:
                            check_db_rows(run_id, turns, spec.expected_nodes)
                        update_experiment_run_status(run_id, "accepted")
                    else:
                        if thermal_recorder is not None:
                            thermal_recorder.snapshot(f"dry_run_post_plan_snapshot:{run_id}")
                    run_ids.append(run_id)
                    print(f"stage_run_done run_id={run_id}")
                    break
                except Exception as exc:
                    print(f"stage_run_failed run_id={run_id} attempt={attempt} error={exc}")
                    if thermal_recorder is not None:
                        thermal_recorder.snapshot(f"failed_run_snapshot:{run_id}")
                    archive_failed_run_artifacts(
                        run_id,
                        args,
                        exc,
                        thermal_recorder.path if thermal_recorder is not None else None,
                        node_local_recorder,
                    )
                    if not args.dry_run:
                        try:
                            update_experiment_run_status(
                                run_id,
                                "failed",
                                format_failure_reason(run_id, args, attempt, exc),
                            )
                        except Exception as status_exc:
                            print(f"failed_run_status_update_warning run_id={run_id} error={status_exc}")
                    if node_local_recorder is not None:
                        node_local_recorder.stop()
                    if not args.dry_run and inference_hosts:
                        try:
                            unload_inference_runners(
                                inference_hosts,
                                args.model_name,
                                args.segment_unload_timeout_sec,
                                "failed_run",
                            )
                        except Exception as unload_exc:
                            print(f"failed_run_unload_warning run_id={run_id} error={unload_exc}")
                    if not args.dry_run and not args.no_failed_db_purge:
                        purge_db_run(run_id)
                    if args.failure_cooldown_sec > 0:
                        print(f"failed_run_cooldown_start run_id={run_id} seconds={args.failure_cooldown_sec}")
                        await asyncio.sleep(args.failure_cooldown_sec)
                        print(f"failed_run_cooldown_done run_id={run_id}")
                    raise RuntimeError(
                        (
                            "stage run failed; file artifacts were archived and failed DB rows were preserved. "
                            if args.no_failed_db_purge
                            else "stage run failed; file artifacts were archived and failed DB rows were purged. "
                        )
                        +
                        "User confirmation is required before any new run attempt."
                    ) from exc
            if offset < repetitions - 1 and args.inter_run_cooldown_sec > 0:
                print(f"inter_run_cooldown_start after_run_id={run_id} seconds={args.inter_run_cooldown_sec}")
                await asyncio.sleep(args.inter_run_cooldown_sec)
                print(f"inter_run_cooldown_done after_run_id={run_id}")

        if args.stage == "cr2" and not args.dry_run and not args.skip_theta_freeze:
            freeze_theta_after_cr2(args, run_ids, turns, repetitions)
    finally:
        if thermal_recorder is not None:
            thermal_recorder.stop()
            print(f"thermal_log_done path={thermal_recorder.path}")


def main() -> None:
    args = parse_args()
    asyncio.run(run_stage(args))


if __name__ == "__main__":
    main()
