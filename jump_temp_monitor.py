#!/usr/bin/env python3
"""Monitor LACP inference-node temperatures from the jump server.

Runs on the jump server and queries inference nodes over SSH. This keeps the
Harness node out of monitoring work during experiments.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


NODES = [
    ("inference1", "10.1.1.10"),
    ("inference2", "10.1.1.20"),
    ("inference3", "10.1.1.30"),
]

SENSOR_RE = re.compile(r"^(?P<name>.+?):\s+(?P<temp>[0-9.]+)\s+C\s+\((?P<source>.+)\)$")


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.home() / "temp_logs" / f"inference_temps_{stamp}.csv"


def parse_report(node_alias: str, ip: str, report: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    remote_host = ""
    section = ""
    timestamp = datetime.now().isoformat(timespec="seconds")

    for line in report.splitlines():
        line = line.strip()
        if line.startswith("host:"):
            remote_host = line.split(":", 1)[1].strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            continue

        match = SENSOR_RE.match(line)
        if not match:
            continue

        rows.append(
            {
                "timestamp": timestamp,
                "node": node_alias,
                "ip": ip,
                "remote_host": remote_host,
                "section": section,
                "sensor": match.group("name"),
                "temp_c": match.group("temp"),
                "source": match.group("source"),
                "status": "ok",
            }
        )

    if not rows:
        rows.append(
            {
                "timestamp": timestamp,
                "node": node_alias,
                "ip": ip,
                "remote_host": remote_host,
                "section": "",
                "sensor": "",
                "temp_c": "",
                "source": "",
                "status": "no_sensor_rows",
            }
        )

    return rows


def query_node(node_alias: str, ip: str, user: str, timeout: int) -> tuple[list[dict[str, str]], str]:
    target = f"{user}@{ip}"
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={timeout}",
        target,
        "python3 ~/node_temp.py",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired as exc:
        timestamp = datetime.now().isoformat(timespec="seconds")
        return (
            [
                {
                    "timestamp": timestamp,
                    "node": node_alias,
                    "ip": ip,
                    "remote_host": "",
                    "section": "",
                    "sensor": "",
                    "temp_c": "",
                    "source": "",
                    "status": f"timeout:{exc}",
                }
            ],
            f"{node_alias}=TIMEOUT",
        )

    if proc.returncode != 0:
        timestamp = datetime.now().isoformat(timespec="seconds")
        err = (proc.stderr or proc.stdout).strip().replace("\n", " ")
        return (
            [
                {
                    "timestamp": timestamp,
                    "node": node_alias,
                    "ip": ip,
                    "remote_host": "",
                    "section": "",
                    "sensor": "",
                    "temp_c": "",
                    "source": "",
                    "status": f"ssh_error:{err[:180]}",
                }
            ],
            f"{node_alias}=ERR",
        )

    rows = parse_report(node_alias, ip, proc.stdout)
    return rows, summarize(node_alias, rows)


def first_temp(rows: list[dict[str, str]], contains: str) -> str:
    for row in rows:
        if contains in row["sensor"] and row["temp_c"]:
            return f"{float(row['temp_c']):.1f}C"
    return "-"


def summarize(node_alias: str, rows: list[dict[str, str]]) -> str:
    gpu = first_temp(rows, "GPU/amdgpu/edge")
    cpu = first_temp(rows, "k10temp/Tctl")
    nvme = first_temp(rows, "nvme/Composite")
    return f"{node_alias}: gpu={gpu} cpu={cpu} nvme={nvme}"


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "node",
        "ip",
        "remote_host",
        "section",
        "sensor",
        "temp_c",
        "source",
        "status",
    ]
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor inference-node temperatures from jump.")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between samples")
    parser.add_argument("--count", type=int, default=1, help="number of samples; 0 means forever")
    parser.add_argument("--user", default=os.environ.get("LACP_NODE_USER", "morophi"))
    parser.add_argument("--timeout", type=int, default=5, help="SSH connect timeout in seconds")
    parser.add_argument("--out", type=Path, default=default_output_path())
    args = parser.parse_args()

    print(f"writing CSV: {args.out}")
    sample = 0
    while True:
        sample += 1
        all_rows: list[dict[str, str]] = []
        summaries: list[str] = []

        for node_alias, ip in NODES:
            rows, summary = query_node(node_alias, ip, args.user, args.timeout)
            all_rows.extend(rows)
            summaries.append(summary)

        append_rows(args.out, all_rows)
        print(f"{datetime.now().isoformat(timespec='seconds')} | " + " | ".join(summaries), flush=True)

        if args.count and sample >= args.count:
            break
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
