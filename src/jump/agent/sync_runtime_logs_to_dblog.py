#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Move completed LACP runtime logs from live nodes to dblog.

Run this from jump or from Windows with `--via-local-ssh-config`. The script is
designed around completed artifact logs, not active service logs. It stages each
node's files on the orchestrator, pushes them to `dblog:/home/lacp/lacp_logs`,
then removes source files only after the dblog push succeeds.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


NODE_IPS = {
    "agent": "local",
    "harness": "harness",
    "rag": "rag",
    "inference1": "inference-a",
    "inference2": "inference-b",
    "inference3": "inference-c",
    "dblog": "dblog",
}


@dataclass(frozen=True)
class SourceSpec:
    node: str
    path: str
    dest_subdir: str
    note: str
    preserve_relative: bool = False


SOURCES = [
    SourceSpec("agent", "/home/lacp/agent/validation_queries/", "validation_queries", "agent completed launcher artifacts"),
    SourceSpec("harness", "/home/lacp/harness/logs/runs/", "logs/runs", "harness completed run JSONL"),
    SourceSpec("harness", "/home/lacp/harness/logs/probes/", "logs/probes", "harness completed probe logs"),
    SourceSpec("harness", "/home/lacp/harness/logs/purge_audit/", "logs/purge_audit", "harness purge audit logs"),
    SourceSpec("harness", "/home/lacp/harness/logs/preformal_runs/", "logs/preformal_runs", "harness preformal JSONL"),
    SourceSpec("harness", "/home/lacp/harness/validation_queries/", "validation_queries", "harness validation query artifacts"),
    SourceSpec("rag", "/home/lacp/lacp_rag_ingest/runs/./*/logs/", "runs", "RAG ingest validation logs", True),
    SourceSpec("inference1", "/home/lacp/lacp_node_thermal/", "lacp_node_thermal", "node-local thermal logs"),
    SourceSpec("inference2", "/home/lacp/lacp_node_thermal/", "lacp_node_thermal", "node-local thermal logs"),
    SourceSpec("inference3", "/home/lacp/lacp_node_thermal/", "lacp_node_thermal", "node-local thermal logs"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Move completed LACP runtime logs to dblog.")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%dT%H%M%SKST"))
    parser.add_argument("--staging-root", default="/tmp/lacp_runtime_log_sync")
    parser.add_argument("--dblog-root", default="/home/lacp/lacp_logs")
    parser.add_argument("--node", action="append", choices=sorted(set(spec.node for spec in SOURCES)), help="Limit to one or more source nodes.")
    parser.add_argument("--execute", action="store_true", help="Actually move source files. Default is dry-run.")
    parser.add_argument("--keep-staging", action="store_true", help="Do not delete local staging after a successful push.")
    parser.add_argument("--via-local-ssh-config", default=None, help="SSH config path to use when running from Windows/local control.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = [spec for spec in SOURCES if not args.node or spec.node in set(args.node)]
    staging_root = Path(args.staging_root) / args.stamp
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "stamp": args.stamp,
        "execute": bool(args.execute),
        "dblog_root": args.dblog_root,
        "staging_root": str(staging_root),
        "sources": [],
    }
    if args.execute:
        staging_root.mkdir(parents=True, exist_ok=True)

    for spec in selected:
        result = sync_spec(args, spec, staging_root)
        manifest["sources"].append(result)

    ok_statuses = {"synced", "empty", "unreachable", "missing", "dry_run"}
    status = "completed" if all(item["status"] in ok_statuses for item in manifest["sources"]) else "failed"
    manifest["status"] = status
    manifest_path = staging_root / f"runtime_log_sync_manifest_{args.stamp}.json"
    if args.execute:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        push_manifest(args, manifest_path)
        if not args.keep_staging:
            shutil.rmtree(staging_root, ignore_errors=True)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0 if status == "completed" else 2


def sync_spec(args: argparse.Namespace, spec: SourceSpec, staging_root: Path) -> dict[str, object]:
    node_host = NODE_IPS[spec.node]
    source_exists = remote_path_exists(args, spec.node, spec.path)
    if source_exists == "unreachable":
        return {"node": spec.node, "path": spec.path, "status": "unreachable", "note": spec.note}
    if source_exists == "missing":
        return {"node": spec.node, "path": spec.path, "status": "missing", "note": spec.note}

    staged_dir = staging_root / spec.node / spec.dest_subdir
    dblog_dest = f"{args.dblog_root.rstrip('/')}/{spec.node}/{spec.dest_subdir}/"
    count = count_files(args, spec.node, spec.path)
    if count == 0:
        return {"node": spec.node, "path": spec.path, "status": "empty", "files": 0, "note": spec.note}

    if not args.execute:
        return {
            "node": spec.node,
            "path": spec.path,
            "status": "dry_run",
            "files": count,
            "dblog_dest": dblog_dest,
            "note": spec.note,
        }

    staged_dir.mkdir(parents=True, exist_ok=True)
    pull_source_to_staging(args, spec, staged_dir)
    staged_count = local_file_count(staged_dir)
    if staged_count != count:
        raise RuntimeError(
            f"staged file count mismatch for {spec.node}:{spec.path}: "
            f"source={count} staged={staged_count}; refusing source deletion"
        )
    push_staging_to_dblog(args, staged_dir, dblog_dest)
    dblog_count = count_dblog_files(args, dblog_dest)
    if dblog_count < staged_count:
        raise RuntimeError(
            f"dblog file count mismatch for {spec.node}:{spec.path}: "
            f"staged={staged_count} dblog_dest_count={dblog_count}; refusing source deletion"
        )
    remove_source_files(args, spec)
    prune_empty_source_dirs(args, spec)
    return {
        "node": spec.node,
        "path": spec.path,
        "status": "synced",
        "files": count,
        "staged_files": staged_count,
        "dblog_dest_files": dblog_count,
        "dblog_dest": dblog_dest,
        "note": spec.note,
    }


def ssh_prefix(args: argparse.Namespace) -> list[str]:
    if args.via_local_ssh_config:
        return ["ssh", "-F", args.via_local_ssh_config]
    return ["ssh"]


def scp_host(args: argparse.Namespace, host: str) -> str:
    return host


def ssh_host(node: str) -> str:
    return NODE_IPS[node]


def ssh_cmd(args: argparse.Namespace, node: str, command: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    if node == "agent":
        return subprocess.run(command, shell=True, text=True, capture_output=True, check=check)
    host = ssh_host(node)
    return subprocess.run([*ssh_prefix(args), "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command], text=True, capture_output=True, check=check)


def remote_path_exists(args: argparse.Namespace, node: str, path: str) -> str:
    command = (
        "found=0; "
        f"for p in {path}; do "
        "[ -e \"$p\" ] && found=1; "
        "done; "
        "test \"$found\" -eq 1"
    )
    command = f"bash -lc {q(command)}"
    proc = ssh_cmd(args, node, command)
    if proc.returncode == 0:
        return "exists"
    stderr = (proc.stderr or "").lower()
    if "no route to host" in stderr or "permission denied" in stderr or "connection" in stderr or "could not resolve" in stderr:
        return "unreachable"
    return "missing"


def count_files(args: argparse.Namespace, node: str, path: str) -> int:
    command_inner = (
        "count=0; "
        f"for p in {path}; do "
        "[ -e \"$p\" ] || continue; "
        "c=$(find \"$p\" -type f 2>/dev/null | wc -l); "
        "count=$((count + c)); "
        "done; "
        "printf '%s\\n' \"$count\""
    )
    command = f"bash -lc {q(command_inner)}"
    proc = ssh_cmd(args, node, command)
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip() or "0")
    except ValueError:
        return 0


def pull_source_to_staging(args: argparse.Namespace, spec: SourceSpec, staged_dir: Path) -> None:
    rsync_flags = ["-aR" if spec.preserve_relative else "-a", "--prune-empty-dirs"]
    if spec.node == "agent":
        run(["rsync", *rsync_flags, *expand_local_sources(spec.path), str(staged_dir) + "/"])
        return
    source = f"{ssh_host(spec.node)}:{spec.path}"
    run(["rsync", *rsync_flags, "-e", "ssh -o BatchMode=yes -o ConnectTimeout=10", source, str(staged_dir) + "/"])


def push_staging_to_dblog(args: argparse.Namespace, staged_dir: Path, dblog_dest: str) -> None:
    run([*ssh_prefix(args), "-o", "BatchMode=yes", ssh_host("dblog"), "mkdir", "-p", dblog_dest])
    run(["rsync", "-a", "--prune-empty-dirs", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=10", str(staged_dir) + "/", f"{ssh_host('dblog')}:{dblog_dest}"])


def push_manifest(args: argparse.Namespace, manifest_path: Path) -> None:
    remote_dir = f"{args.dblog_root.rstrip('/')}/transfer_records/runtime_log_sync/"
    run([*ssh_prefix(args), "-o", "BatchMode=yes", ssh_host("dblog"), "mkdir", "-p", remote_dir])
    run(["rsync", "-a", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=10", str(manifest_path), f"{ssh_host('dblog')}:{remote_dir}"])


def local_file_count(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file())


def count_dblog_files(args: argparse.Namespace, dblog_dest: str) -> int:
    command = f"find {q(dblog_dest)} -type f 2>/dev/null | wc -l"
    proc = ssh_cmd(args, "dblog", command)
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip() or "0")
    except ValueError:
        return 0


def remove_source_files(args: argparse.Namespace, spec: SourceSpec) -> None:
    command = f"for p in {spec.path}; do [ -e \"$p\" ] && find \"$p\" -type f -delete 2>/dev/null || true; done"
    ssh_cmd(args, spec.node, f"bash -lc {q(command)}", check=True)


def prune_empty_source_dirs(args: argparse.Namespace, spec: SourceSpec) -> None:
    command = f"for p in {spec.path}; do [ -e \"$p\" ] && find \"$p\" -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true; done"
    ssh_cmd(args, spec.node, f"bash -lc {q(command)}", check=True)


def expand_local_sources(path: str) -> list[str]:
    return [path]


def q(value: str) -> str:
    return shlex.quote(value)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, timeout=300)


if __name__ == "__main__":
    raise SystemExit(main())
