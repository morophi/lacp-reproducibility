#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run or preflight the LACP E2E rough smoke path.

This script is intentionally E2E-only. It checks the live Agent -> Harness ->
RAG/A/B/C -> dblog path and, when --execute is provided, sends the first N
turns through Harness in smoke mode. It does not run ingest, rebuild retrieval
artifacts, alter scenario files, or perform thermal/log forensics.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SCENARIO = "/home/morophi/agent/scenario/lacp_scenario_base_v2.json"
DEFAULT_HARNESS_URL = "http://10.1.1.110:9000"
DEFAULT_LOCAL_OUTPUT_DIR = Path("validation_queries/e2e_runs")
DEFAULT_PREFLIGHT_OUTPUT_DIR = Path("validation_queries/preflight")
EXPECTED_NODES = ("A", "B", "C")
THERMAL_NODES = ("inference1", "inference2", "inference3", "rag")
DB_PASSWORD_ENV = "LACP_DB_PASSWORD"

SSH_ALIASES = ("jump", "harness", "rag", "inference1", "inference2", "inference3", "dblog")
SERVICE_TARGETS = {
    "harness_api": ("10.1.1.110", 9000),
    "rag_api": ("10.1.1.120", 8000),
    "node_a_ollama": ("10.1.1.10", 11434),
    "node_b_ollama": ("10.1.1.20", 11434),
    "node_c_ollama": ("10.1.1.30", 11434),
    "dblog_mysql": ("10.1.1.130", 3306),
}


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str


class ThermalLogger:
    def __init__(
        self,
        run_id: str,
        output_dir: Path,
        interval_sec: float,
        nodes: tuple[str, ...] = THERMAL_NODES,
        cooldown_sec: float = 10.0,
    ):
        self.run_id = run_id
        self.output_dir = output_dir
        self.interval_sec = interval_sec
        self.nodes = nodes
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
                "interval_sec": self.interval_sec,
                "cooldown_sec": self.cooldown_sec,
            }
        )
        self._thread = threading.Thread(target=self._loop, name=f"thermal-{self.run_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.cooldown_sec > 0:
            self._write(
                {
                    "event": "thermal_cooldown_start",
                    "run_id": self.run_id,
                    "cooldown_sec": self.cooldown_sec,
                    "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                }
            )
            self._stop.wait(self.cooldown_sec)
            self._write(
                {
                    "event": "thermal_cooldown_end",
                    "run_id": self.run_id,
                    "cooldown_sec": self.cooldown_sec,
                    "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                }
            )
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(10.0, self.interval_sec * 8))
        self._write({"event": "thermal_logger_stop", "run_id": self.run_id})

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=len(self.nodes)) as executor:
                futures = [executor.submit(self._sample_node, node) for node in self.nodes]
                for future in as_completed(futures):
                    self._write(future.result())
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.interval_sec - elapsed))

    def _sample_node(self, node: str) -> dict:
        proc = ssh(node, remote_temperature_command(), timeout=8)
        base = {
            "event": "thermal_sample",
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "node": node,
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

    def _write(self, row: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
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
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_command], timeout=timeout)


def record(name: str, proc: subprocess.CompletedProcess[str], ok: bool | None = None) -> StepResult:
    return StepResult(
        name=name,
        ok=(proc.returncode == 0 if ok is None else ok),
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def tcp_probe_command(host: str, port: int, timeout_sec: int) -> str:
    code = (
        "import socket,sys;"
        "s=socket.socket();"
        "s.settimeout(float(sys.argv[3]));"
        "s.connect((sys.argv[1],int(sys.argv[2])));"
        "s.close()"
    )
    return " ".join(["python3", "-c", shlex.quote(code), shlex.quote(host), shlex.quote(str(port)), shlex.quote(str(timeout_sec))])


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


def check_ssh_aliases() -> list[StepResult]:
    results = []
    for alias in SSH_ALIASES:
        proc = ssh(alias, "echo ok", timeout=20)
        results.append(record(f"ssh:{alias}", proc, ok=proc.returncode == 0 and "ok" in proc.stdout))
    return results


def check_service_ports(timeout_sec: int) -> list[StepResult]:
    results = []
    for name, (host, port) in SERVICE_TARGETS.items():
        proc = ssh("jump", tcp_probe_command(host, port, timeout_sec), timeout=timeout_sec + 15)
        results.append(record(f"service:{name}", proc))
    return results


def check_remote_prereqs(scenario: str) -> list[StepResult]:
    db_password = os.environ.get(DB_PASSWORD_ENV)
    if not db_password:
        return [StepResult("dblog:schema", False, 1, "", f"{DB_PASSWORD_ENV} must be set")]
    commands = {
        "agent:scenario_loader": (
            "test -f /home/morophi/agent/run_scenario.py && "
            f"test -f {shlex.quote(scenario)} && "
            "cd /home/morophi/agent && "
            "python3 - <<'PY'\n"
            "from scenario_loader import load_scenario\n"
            f"scenario = load_scenario({scenario!r})\n"
            "print(f\"scenario_id={scenario['scenario_id']} turns={len(scenario['turns'])} scenario_hash={scenario['scenario_hash']}\")\n"
            "PY"
        ),
        "harness:service": (
            "systemctl --user is-active lacp-harness.service && "
            "ss -ltnp | grep 9000"
        ),
        "rag:heartbeat": "curl -sS --max-time 5 http://127.0.0.1:8000/api/v2/heartbeat",
        "dblog:schema": (
            f"mysqladmin -umorophi --password={shlex.quote(db_password)} ping && "
            f"mysql -umorophi --password={shlex.quote(db_password)} lacp_db -e 'SHOW COLUMNS FROM turn_node_logs;' "
            "| grep -E 'history_eligible|history_exclusion_reason|metric_trigger_eligibility'"
        ),
    }
    hosts = {
        "agent:scenario_loader": "jump",
        "harness:service": "harness",
        "rag:heartbeat": "rag",
        "dblog:schema": "dblog",
    }
    return [record(name, ssh(hosts[name], command, timeout=40)) for name, command in commands.items()]


def run_e2e(run_id: str, scenario: str, turns: int, harness_url: str) -> StepResult:
    command = (
        "cd /home/morophi/agent && "
        f"python3 run_scenario.py --scenario {shlex.quote(scenario)} "
        f"--run-id {shlex.quote(run_id)} "
        "--condition run_b --run-mode smoke "
        f"--harness-url {shlex.quote(harness_url)} "
        f"--max-turns {turns}"
    )
    return record("execute:agent_run_scenario", ssh("jump", command, timeout=max(300, turns * 180)))


def fetch_jsonl(run_id: str, output_dir: Path) -> tuple[StepResult, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    local_jsonl = output_dir / f"{run_id}.jsonl"
    remote_jsonl = f"/home/morophi/harness/logs/runs/{run_id}.jsonl"
    proc = run(["scp", f"harness:{remote_jsonl}", str(local_jsonl)], timeout=60)
    return record("fetch:harness_jsonl", proc), local_jsonl


def validate_jsonl(local_jsonl: Path, turns: int, output_dir: Path) -> StepResult:
    validation_out = output_dir / f"{local_jsonl.stem}_validation.json"
    proc = run(
        [
            sys.executable,
            "scripts/21_validate_precr_e2e_run.py",
            "--jsonl",
            str(local_jsonl),
            "--output",
            str(validation_out),
            "--expected-turns",
            str(turns),
        ],
        timeout=60,
    )
    return record("validate:jsonl", proc)


def check_db_rows(run_id: str, turns: int) -> StepResult:
    db_password = os.environ.get(DB_PASSWORD_ENV)
    if not db_password:
        return StepResult("validate:dblog_rows", False, 1, "", f"{DB_PASSWORD_ENV} must be set")
    sql = (
        "SELECT 'turn_node_logs', COUNT(*) FROM turn_node_logs t "
        "JOIN experiment_runs r ON r.id = t.experiment_run_id WHERE r.run_id="
        f"'{run_id}' UNION ALL "
        "SELECT 'intervention_logs', COUNT(*) FROM intervention_logs i "
        "JOIN turn_node_logs t ON t.id = i.turn_node_log_id "
        "JOIN experiment_runs r ON r.id = t.experiment_run_id WHERE r.run_id="
        f"'{run_id}' UNION ALL "
        "SELECT 'metric_logs', COUNT(*) FROM metric_logs m "
        "JOIN turn_node_logs t ON t.id = m.turn_node_log_id "
        "JOIN experiment_runs r ON r.id = t.experiment_run_id WHERE r.run_id="
        f"'{run_id}';"
    )
    command = f"mysql -umorophi --password={shlex.quote(db_password)} lacp_db -N -e " + shlex.quote(sql)
    proc = ssh("dblog", command, timeout=60)
    expected = turns * len(EXPECTED_NODES)
    ok = proc.returncode == 0 and all(line.rstrip().endswith(f"\t{expected}") for line in proc.stdout.splitlines() if line.strip())
    return record("validate:dblog_rows", proc, ok=ok)


def run_inference_readiness_preflight(output_dir: Path) -> StepResult:
    proc = run(
        [
            sys.executable,
            "scripts/preflight_inference_readiness.py",
            "--output-dir",
            str(output_dir),
        ],
        timeout=900,
    )
    return record("preflight:inference_readiness_db_free", proc)


def summarize(results: list[StepResult]) -> dict:
    return {
        "status": "pass" if all(result.ok for result in results) else "blocked",
        "results": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Actually send turns through Harness. Omit for preflight only.")
    parser.add_argument("--turns", type=int, default=2, help="Number of initial turns to send when --execute is used.")
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to e2e_rough_YYYYmmddTHHMMSSZ.")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--harness-url", default=DEFAULT_HARNESS_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOCAL_OUTPUT_DIR)
    parser.add_argument("--timeout-sec", type=int, default=5)
    parser.add_argument("--thermal-interval-sec", type=float, default=1.0, help="Thermal sampling interval during --execute.")
    parser.add_argument("--thermal-cooldown-sec", type=float, default=10.0, help="Continue thermal sampling this many seconds after E2E execution ends.")
    parser.add_argument("--no-thermal-log", action="store_true", help="Disable thermal logging during --execute.")
    parser.add_argument("--preflight-output-dir", type=Path, default=DEFAULT_PREFLIGHT_OUTPUT_DIR)
    parser.add_argument(
        "--skip-inference-readiness",
        action="store_true",
        help="Skip DB-free inference readiness gate before --execute. Use only for manual diagnostics.",
    )
    args = parser.parse_args()

    if args.turns < 1 or args.turns > 30:
        raise SystemExit("--turns must be between 1 and 30")

    run_id = args.run_id or time.strftime("e2e_rough_%Y%m%dT%H%M%SZ", time.gmtime())
    results: list[StepResult] = []
    results.extend(check_ssh_aliases())
    results.extend(check_service_ports(args.timeout_sec))
    results.extend(check_remote_prereqs(args.scenario))

    if all(result.ok for result in results) and args.execute and not args.skip_inference_readiness:
        results.append(run_inference_readiness_preflight(args.preflight_output_dir))

    thermal_logger = None
    if all(result.ok for result in results) and args.execute:
        if not args.no_thermal_log:
            thermal_logger = ThermalLogger(
                run_id,
                args.output_dir,
                args.thermal_interval_sec,
                cooldown_sec=args.thermal_cooldown_sec,
            )
            thermal_logger.start()
        try:
            results.append(run_e2e(run_id, args.scenario, args.turns, args.harness_url))
            if results[-1].ok:
                fetch_result, local_jsonl = fetch_jsonl(run_id, args.output_dir)
                results.append(fetch_result)
                if fetch_result.ok:
                    results.append(validate_jsonl(local_jsonl, args.turns, args.output_dir))
                results.append(check_db_rows(run_id, args.turns))
        finally:
            if thermal_logger is not None:
                thermal_logger.stop()

    payload = {
        "run_id": run_id,
        "mode": "execute" if args.execute else "preflight_only",
        "turns": args.turns,
        "scenario": args.scenario,
        "harness_url": args.harness_url,
        "thermal_log": str(thermal_logger.path) if thermal_logger is not None else None,
        "thermal_cooldown_sec": args.thermal_cooldown_sec if thermal_logger is not None else None,
        **summarize(results),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
