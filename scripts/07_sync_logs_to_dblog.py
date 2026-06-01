"""
Step 07: Sync iMac ingest logs and manifests to dblog.

This step keeps the iMac as the local producer of embedding artifacts while
archiving reproducibility evidence on the central dblog node. It does not route
anything through Harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ingest_config as config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync iMac ingest logs and manifests directly to dblog."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the sync plan only.")
    parser.add_argument(
        "--dblog-host",
        default=config.DBLOG_HOST,
        help="SSH host alias for dblog. Defaults to LACP_DBLOG_HOST or dblog.",
    )
    parser.add_argument(
        "--remote-root",
        default=config.DBLOG_REMOTE_ROOT,
        help="Remote path relative to dblog HOME. Defaults to lacp_logs/imac_embedding.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prefix = f"{config.ARTIFACT_PREFIX}_{config.RUN_ID}"
    files = collect_files(prefix)
    remote_dir = f"{args.remote_root.rstrip('/')}/{config.RUN_ID}/{config.ARTIFACT_PREFIX}"
    package_path = config.DIRS.logs / f"{prefix}_dblog_archive.tar.gz"
    plan = {
        "step": "07_sync_logs_to_dblog",
        "run_id": config.RUN_ID,
        "artifact_prefix": config.ARTIFACT_PREFIX,
        "dblog_host": args.dblog_host,
        "remote_dir": f"~/{remote_dir}",
        "package": str(package_path),
        "file_count": len(files),
        "files": [str(path) for path in files],
        "routes_through_harness": False,
    }

    if args.dry_run:
        print_json(plan)
        return 0

    if not files:
        print_json({**plan, "status": "failed", "reason": "no matching logs or manifests"}, stream=None)
        return 2

    source_info = write_source_info(prefix, files)
    files.append(source_info)
    write_archive(package_path, files)
    package_sha = sha256_file(package_path)
    package_size = package_path.stat().st_size

    remote_home = run_capture(["ssh", args.dblog_host, "printf '%s' \"$HOME\""]).strip()
    remote_dir_abs = f"{remote_home}/{remote_dir}"
    run(["ssh", args.dblog_host, "mkdir", "-p", remote_dir_abs])
    run(["scp", str(package_path), f"{args.dblog_host}:{remote_dir_abs}/{package_path.name}"])
    remote_sha = run_capture(
        [
            "ssh",
            args.dblog_host,
            remote_sha_command(f"{remote_dir_abs}/{package_path.name}"),
        ]
    ).strip()
    remote_size = int(
        run_capture(
            [
                "ssh",
                args.dblog_host,
                f"wc -c < {shlex.quote(remote_dir_abs + '/' + package_path.name)} | tr -d ' '",
            ]
        ).strip()
    )
    run(
        [
            "ssh",
            args.dblog_host,
            "tar",
            "-xzf",
            f"{remote_dir_abs}/{package_path.name}",
            "-C",
            remote_dir_abs,
        ]
    )

    sync_record = {
        **plan,
        "status": "completed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_sha256": package_sha,
        "remote_sha256": remote_sha,
        "remote_home": remote_home,
        "remote_dir_abs": remote_dir_abs,
        "package_size": package_size,
        "remote_size": remote_size,
        "sha256_match": package_sha == remote_sha,
        "size_match": package_size == remote_size,
        "sync_log": str(config.DBLOG_SYNC_LOG),
    }
    config.DBLOG_SYNC_LOG.write_text(
        json.dumps(sync_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run(["scp", str(config.DBLOG_SYNC_LOG), f"{args.dblog_host}:{remote_dir_abs}/{config.DBLOG_SYNC_LOG.name}"])
    print_json(sync_record)
    return 0 if sync_record["sha256_match"] and sync_record["size_match"] else 3


def collect_files(prefix: str) -> list[Path]:
    candidates = [
        *(config.DIRS.logs.glob(f"{prefix}_*.json")),
        *(config.DIRS.logs.glob(f"{prefix}_*.md")),
        *(config.DIRS.manifest.glob(f"{prefix}_*.json")),
        *(config.DIRS.manifest.glob(f"{prefix}_*.md")),
        *(config.DIRS.manifest.glob(f"{prefix}_*.txt")),
    ]
    excluded = {config.DBLOG_SYNC_LOG.name}
    return sorted(path for path in candidates if path.is_file() and path.name not in excluded)


def write_source_info(prefix: str, files: list[Path]) -> Path:
    source_info = {
        "run_id": config.RUN_ID,
        "artifact_prefix": config.ARTIFACT_PREFIX,
        "target_pdf": str(config.TARGET_PDF),
        "target_pdf_exists": config.TARGET_PDF.exists(),
        "target_pdf_sha256": sha256_file(config.TARGET_PDF) if config.TARGET_PDF.exists() else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "archived_files": [
            {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}
            for path in files
        ],
    }
    path = config.DIRS.manifest / f"{prefix}_dblog_source_info.json"
    path.write_text(
        json.dumps(source_info, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_archive(package_path: Path, files: list[Path]) -> None:
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(package_path, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(config.PROJECT_ROOT)))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_sha_command(path: str) -> str:
    quoted = shlex.quote(path)
    return (
        f"if command -v sha256sum >/dev/null 2>&1; then "
        f"sha256sum {quoted} | cut -d ' ' -f 1; "
        f"else shasum -a 256 {quoted} | cut -d ' ' -f 1; fi"
    )


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, timeout=60)


def run_capture(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=60
    ).stdout


def print_json(payload: dict[str, Any], stream: Any = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
