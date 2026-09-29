#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Check that the harness theta_config is locked before formal Run B/CF."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


REQUIRED_KEYS = ("theta_entropy", "theta_lms", "theta_cds", "theta_ma")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check remote theta_config locked=true.")
    parser.add_argument("--harness-host", default="harness")
    parser.add_argument("--theta-path", default="/home/lacp/harness/config/theta_config.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cmd = ["ssh", args.harness_host, "cat", args.theta_path]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
        return proc.returncode
    data = json.loads(proc.stdout)
    if data.get("locked") is not True:
        print(f"theta_locked_check_failed locked={data.get('locked')} source={data.get('source')}", file=sys.stderr)
        return 2
    missing = [key for key in REQUIRED_KEYS if not isinstance(data.get(key), (int, float))]
    if missing:
        print(f"theta_locked_check_failed missing_numeric={missing}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "theta_locked": True,
                "source": data.get("source"),
                "cr2_run_id": data.get("cr2_run_id"),
                "theta_entropy": data.get("theta_entropy"),
                "theta_lms": data.get("theta_lms"),
                "theta_cds": data.get("theta_cds"),
                "theta_ma": data.get("theta_ma"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
