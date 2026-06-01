#!/usr/bin/env python3
"""Detect and sync allowlisted node changes into the local canonical repo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "node_sync_targets.json"
DEFAULT_SECRET_PATTERNS = [
    "PRIVATE" + " KEY",
    "ssh-" + "rsa",
    "ssh-" + "ed25519",
    "node" + "key:",
]


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run(cmd: list[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def remote_run(host: str, command: str) -> str:
    result = run(["ssh", host, command], check=True)
    return result.stdout


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(path: Path, state: dict[str, str]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_expression(include_names: list[str], exclude_paths: list[str]) -> str:
    name_expr = " -o ".join(f"-name {sh_quote(name)}" for name in include_names)
    parts = [f"\\( {name_expr} \\)"]
    for excluded in exclude_paths:
        parts.append(f"! -path {sh_quote(excluded)}")
    return " ".join(parts)


def parse_sha256sum(output: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        digest, _, path = line.partition("  ")
        if not path:
            digest, _, path = line.partition(" ")
        if digest and path:
            items.append((path.strip(), digest.strip()))
    return items


def list_remote_tree(host: str, target: dict[str, Any]) -> list[dict[str, str]]:
    remote_root = target["remote_root"].rstrip("/")
    include_names = target.get("include_names", ["*"])
    exclude_paths = target.get("exclude_paths", [])
    expr = find_expression(include_names, exclude_paths)
    command = (
        f"if [ -d {sh_quote(remote_root)} ]; then "
        f"find {sh_quote(remote_root)} -type f {expr} -exec sha256sum {{}} \\; ; "
        "fi"
    )
    files = []
    for remote_path, digest in parse_sha256sum(remote_run(host, command)):
        rel = remote_path.removeprefix(remote_root).lstrip("/")
        local_path = str(Path(target["local_root"]) / Path(rel))
        files.append({"remote": remote_path, "local": local_path, "sha256": digest})
    return files


def list_remote_files(host: str, target: dict[str, Any]) -> list[dict[str, str]]:
    files = []
    for item in target["files"]:
        remote_path = item["remote"]
        command = f"if [ -f {sh_quote(remote_path)} ]; then sha256sum {sh_quote(remote_path)}; fi"
        output = remote_run(host, command)
        parsed = parse_sha256sum(output)
        if parsed:
            _, digest = parsed[0]
            files.append({"remote": remote_path, "local": item["local"], "sha256": digest})
    return files


def list_remote_inventory(config: dict[str, Any]) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    for node in config["nodes"]:
        host = node["host"]
        for target in node["targets"]:
            if target["kind"] == "tree":
                files = list_remote_tree(host, target)
            elif target["kind"] == "files":
                files = list_remote_files(host, target)
            else:
                raise ValueError(f"Unsupported target kind: {target['kind']}")
            for item in files:
                item["node"] = node["name"]
                item["host"] = host
                item["key"] = f"{node['name']}:{item['remote']}"
            inventory.extend(files)
    return inventory


def local_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def changed_items(inventory: list[dict[str, str]], state: dict[str, str]) -> list[dict[str, str]]:
    changed = []
    for item in inventory:
        local_path = REPO_ROOT / item["local"]
        current_local = local_sha256(local_path)
        if item["sha256"] != current_local:
            changed.append(item)
    return changed


def copy_item(item: dict[str, str]) -> None:
    local_path = REPO_ROOT / item["local"]
    local_path.parent.mkdir(parents=True, exist_ok=True)
    spec = f"{item['host']}:{sh_quote(item['remote'])}"
    run(["scp", spec, str(local_path)], check=True)


def scan_staged() -> list[str]:
    hits: list[str] = []
    extra = [p for p in os.environ.get("LACP_SECRET_SCAN_PATTERNS", "").split(";") if p]
    for pattern in DEFAULT_SECRET_PATTERNS + extra:
        result = run(["git", "grep", "--cached", "-n", "-F", pattern], check=False)
        if result.returncode == 0:
            hits.append(result.stdout.strip())
    return [hit for hit in hits if hit]


def commit_changes(message: str, push: bool) -> None:
    run(["git", "add", "--all"], check=True)
    status = run(["git", "diff", "--cached", "--quiet"], check=False)
    if status.returncode == 0:
        print("No staged changes to commit.")
        return
    hits = scan_staged()
    if hits:
        print("Secret scan failed. Review these hits before committing:", file=sys.stderr)
        print("\n".join(hits), file=sys.stderr)
        raise SystemExit(2)
    run(["git", "commit", "-m", message], check=True)
    if push:
        run(["git", "push", "origin", "main"], check=True)


def print_items(title: str, items: list[dict[str, str]]) -> None:
    print(title)
    if not items:
        print("  none")
        return
    for item in items:
        print(f"  {item['node']} {item['remote']} -> {item['local']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["detect", "sync"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--apply", action="store_true", help="copy changed files; default is dry-run")
    parser.add_argument("--commit", action="store_true", help="commit copied changes after sync")
    parser.add_argument("--push", action="store_true", help="push to origin/main after commit")
    parser.add_argument("--message", default=None, help="commit message override")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    state_path = REPO_ROOT / config.get("state_file", ".node_sync_state.json")
    state = load_state(state_path)
    inventory = list_remote_inventory(config)
    changed = changed_items(inventory, state)

    print_items("Changed allowlisted node files:", changed)
    if args.mode == "detect":
        return 1 if changed else 0

    if not args.apply:
        print("Dry-run only. Re-run with --apply to copy changes.")
        return 1 if changed else 0

    for item in changed:
        copy_item(item)
        state[item["key"]] = item["sha256"]
    save_state(state_path, state)

    if args.commit:
        message = args.message or "Sync allowlisted node changes"
        commit_changes(message, args.push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
