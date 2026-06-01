"""Check closed-network reachability through the configured jump host.

The iMac sits outside the closed experiment network, so direct TCP probes to
10.1.1.x are expected to fail.  This script verifies only the transport path
that matters for an E2E run:

1. SSH alias reachability from the iMac using ~/.ssh/config.
2. Service-port reachability from the jump node to the closed-network targets.

It deliberately does not call harness /turn, RAG retrieval, Ollama generation,
or the metrics database protocol.  The goal is a connectivity yes/no check
without creating experiment rows or changing any service state.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SSH_OPTS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=5",
]

SSH_ALIASES = ["jump", "harness", "rag", "inference1", "inference2", "inference3", "dblog"]

SERVICE_TARGETS = {
    "harness_api": ("10.1.1.110", 9000),
    "rag_api": ("10.1.1.120", 8000),
    "node_a_ollama": ("10.1.1.10", 11434),
    "node_b_ollama": ("10.1.1.20", 11434),
    "node_c_ollama": ("10.1.1.30", 11434),
    "dblog_mysql": ("10.1.1.130", 3306),
}

# Keep the jump-side probe as one physical line.  OpenSSH sends the remote
# command through the user's login shell, and a multi-line `python3 -c` payload
# can be split by that shell before Python receives it.  A compact one-liner
# avoids quoting ambiguity while still performing only a raw TCP connect.
JUMP_TCP_PROBE = (
    "import socket,sys;"
    "s=socket.socket();"
    "s.settimeout(float(sys.argv[3]));"
    "s.connect((sys.argv[1],int(sys.argv[2])));"
    "s.close()"
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    target: str
    reachable: bool
    returncode: int
    stdout: str
    stderr: str


def run_command(args: list[str], timeout_sec: float) -> subprocess.CompletedProcess[str]:
    """Run a bounded subprocess and preserve stdout/stderr for audit output."""
    return subprocess.run(
        args,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )


def check_ssh_alias(alias: str, timeout_sec: float) -> CheckResult:
    """Verify that the iMac can open an SSH session to a configured alias."""
    proc = run_command(["ssh", *SSH_OPTS, alias, "echo", "ok"], timeout_sec)
    return CheckResult(
        name=f"ssh:{alias}",
        target=alias,
        reachable=proc.returncode == 0 and "ok" in proc.stdout,
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def check_service_from_jump(name: str, host: str, port: int, timeout_sec: float) -> CheckResult:
    """Ask the jump node to open a raw TCP socket to a closed-network service."""
    # Unlike local subprocess argv, OpenSSH ultimately sends a remote command
    # string to the target user's shell.  Quote the Python code and arguments
    # explicitly so parentheses and semicolons remain Python syntax instead of
    # being parsed by bash on the jump host.
    remote_command = " ".join(
        [
            "python3",
            "-c",
            shlex.quote(JUMP_TCP_PROBE),
            shlex.quote(host),
            shlex.quote(str(port)),
            shlex.quote(str(timeout_sec)),
        ]
    )
    proc = run_command(
        [
            "ssh",
            *SSH_OPTS,
            "jump",
            remote_command,
        ],
        timeout_sec + 7,
    )
    return CheckResult(
        name=f"service:{name}",
        target=f"{host}:{port}",
        reachable=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    ssh_results = [check_ssh_alias(alias, args.timeout_sec + 7) for alias in SSH_ALIASES]
    service_results = [
        check_service_from_jump(name, host, port, args.timeout_sec)
        for name, (host, port) in SERVICE_TARGETS.items()
    ]

    payload = {
        "purpose": "closed-network connectivity check through jump only",
        "state_changing_calls_executed": False,
        "ssh_alias_checks": [result.__dict__ for result in ssh_results],
        "service_port_checks_from_jump": [result.__dict__ for result in service_results],
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)

    # Exit success when the check itself completed; individual unreachable
    # targets are reported in JSON instead of being collapsed into process exit.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
