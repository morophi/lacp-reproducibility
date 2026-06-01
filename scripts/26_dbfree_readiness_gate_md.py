#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run or convert the Level 0 DB-free readiness gate into Markdown.

This gate does not call Harness /turn and does not write to dblog. It is a
non-result-generating operational validity gate for endpoint, payload,
logprobs, artifact, thermal/runner cleanup, and direct inference readiness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_DIR = REPO_ROOT / "validation_queries" / "preflight"
DEFAULT_MD_DIR = REPO_ROOT / "validation_queries" / "preformal_md"
DISCLAIMER = (
    "This artifact is a DB-free pre-formal readiness report. It is not formal "
    "experimental evidence. It is excluded from CR, CR2, Run B, CF, statistical "
    "testing, threshold estimation, effect-size estimation, and causal interpretation."
)


def run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", type=Path, default=None, help="Convert an existing readiness JSON file.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_MD_DIR)
    parser.add_argument("--json-output-dir", type=Path, default=DEFAULT_JSON_DIR)
    parser.add_argument("--execute", action="store_true", help="Run scripts/preflight_inference_readiness.py first.")
    parser.add_argument("--dry-plan", action="store_true", help="Write a plan-only Markdown artifact.")
    parser.add_argument("--timeout-sec", type=int, default=1200)
    return parser.parse_args()


def latest_json(path: Path) -> Path:
    candidates = sorted(path.glob("inference_readiness_*.json"), key=lambda item: item.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No readiness JSON found under {path}")
    return candidates[-1]


def run_readiness(json_dir: Path, timeout_sec: int) -> tuple[Path | None, subprocess.CompletedProcess[str]]:
    before = set(json_dir.glob("inference_readiness_*.json"))
    proc = run(
        [
            sys.executable,
            "scripts/preflight_inference_readiness.py",
            "--output-dir",
            str(json_dir),
        ],
        timeout=timeout_sec,
    )
    after = set(json_dir.glob("inference_readiness_*.json"))
    created = sorted(after - before, key=lambda item: item.stat().st_mtime)
    if created:
        return created[-1], proc
    if proc.returncode == 0:
        return latest_json(json_dir), proc
    return None, proc


def status(value: Any) -> str:
    return "PASS" if value else "BLOCKED"


def table_from_checks(checks: dict[str, Any]) -> str:
    lines = ["| Check | Status |", "| --- | --- |"]
    for key, value in sorted(checks.items()):
        lines.append(f"| `{key}` | {status(bool(value))} |")
    return "\n".join(lines)


def fenced(label: str, content: str) -> str:
    content = content.strip() or "(empty)"
    return f"```{label}\n{content}\n```"


def readiness_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "db_writes": payload.get("db_writes"),
        "harness_turn_called": payload.get("harness_turn_called"),
        "direct_inference_probe_called": payload.get("direct_inference_probe_called"),
        "actual_first_turn_payload_built": payload.get("actual_first_turn_payload_built"),
        "scenario": payload.get("scenario"),
        "checks": payload.get("checks", {}),
        "thresholds": payload.get("thresholds", {}),
    }


def write_md(
    output_dir: Path,
    payload: dict[str, Any],
    json_path: Path | None,
    command_result: subprocess.CompletedProcess[str] | None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = output_dir / f"dbfree_readiness_{stamp}_topk3.md"
    checks = payload.get("checks", {}) if isinstance(payload.get("checks"), dict) else {}
    lines = [
        "# DB-Free Pre-Formal Readiness Report",
        "",
        f"> {DISCLAIMER}",
        "",
        f"- Status: `{payload.get('status', 'plan-only')}`",
        f"- Created UTC: `{stamp}`",
        f"- DB writes: `{payload.get('db_writes', False)}`",
        f"- Harness /turn called: `{payload.get('harness_turn_called', False)}`",
        f"- Direct inference probe called: `{payload.get('direct_inference_probe_called', False)}`",
        f"- JSON evidence: `{json_path if json_path else '(none)'}`",
        "",
        "## Scope",
        "",
        "- Endpoint availability",
        "- Actual first-turn payload feasibility without Harness /turn",
        "- Formal logprobs availability",
        "- Fixed artifact and routing integrity signals",
        "- Response completeness",
        "- Runner unload/settle status",
        "",
        "## Exclusions",
        "",
        "- No A/B/C performance comparison",
        "- No causal signal interpretation",
        "- No top-k, threshold, or scenario tuning based on readiness output",
        "- No selective reporting of successful readiness attempts",
        "",
        "## Checks",
        "",
        table_from_checks(checks),
        "",
        "## Summary JSON",
        "",
        fenced("json", json.dumps(readiness_summary(payload), ensure_ascii=False, indent=2, sort_keys=True)),
        "",
    ]
    if command_result is not None:
        lines.extend(
            [
                "## Command Result",
                "",
                f"- Return code: `{command_result.returncode}`",
                "",
                "stdout:",
                fenced("text", command_result.stdout),
                "",
                "stderr:",
                fenced("text", command_result.stderr),
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    if args.dry_plan:
        payload = {
            "status": "plan-only",
            "db_writes": False,
            "harness_turn_called": False,
            "direct_inference_probe_called": False,
            "actual_first_turn_payload_built": False,
            "checks": {"plan_only": True},
        }
        print(write_md(args.output_dir, payload, None, None))
        return 0

    command_result = None
    json_path = args.from_json
    if args.execute:
        json_path, command_result = run_readiness(args.json_output_dir, args.timeout_sec)
    if json_path is None:
        json_path = latest_json(args.json_output_dir)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    md_path = write_md(args.output_dir, payload, json_path, command_result)
    print(md_path)
    return 0 if payload.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
