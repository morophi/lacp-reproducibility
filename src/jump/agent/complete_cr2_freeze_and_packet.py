#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Complete CR2 by freezing theta and writing the professor-review packet."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "runtime_impl" / "agent"
if AGENT.exists():
    sys.path.insert(0, str(AGENT))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_experiment_stage as stage_runner  # noqa: E402
import write_cr2_theta_formula_packet as packet_writer  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze theta after 3 accepted CR2 runs and write review MD.")
    parser.add_argument("--run-ids", nargs="+", required=True, help="Exactly 3 accepted CR2 run IDs.")
    parser.add_argument("--harness-host", default=stage_runner.DEFAULT_HARNESS_HOST)
    parser.add_argument("--theta-path", default=stage_runner.DEFAULT_THETA_PATH)
    parser.add_argument("--node-config-path", default=stage_runner.DEFAULT_NODE_CONFIG_PATH)
    parser.add_argument("--entropy-percentile", type=float, default=stage_runner.DEFAULT_ENTROPY_PERCENTILE)
    parser.add_argument("--trigger-percentile", type=float, default=stage_runner.DEFAULT_TRIGGER_PERCENTILE)
    parser.add_argument("--packet-output-dir", type=Path, default=packet_writer.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--post-validation-dir", type=Path, default=packet_writer.DEFAULT_POST_VALIDATION_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_ids = packet_writer.split_run_ids(args.run_ids)
    if len(run_ids) != 3:
        raise SystemExit(f"CR2 completion requires exactly 3 accepted run IDs; got {len(run_ids)}")

    for run_id in run_ids:
        packet_writer.load_post_validation(args.post_validation_dir, run_id)

    scenario = stage_runner.load_scenario(stage_runner.DEFAULT_SCENARIO)
    turns = len(scenario["turns"])
    expected_rows = turns * len(run_ids) * 2
    calibration = stage_runner.fetch_cr2_metric_values(run_ids)
    metadata = stage_runner.fetch_cr2_run_metadata(run_ids)
    theta = stage_runner.build_theta_config(
        run_ids,
        calibration,
        expected_rows,
        args.entropy_percentile,
        args.trigger_percentile,
        metadata,
    )
    theta_path = stage_runner.write_local_theta(theta, "cr2_complete")
    stage_runner.install_theta_config(theta_path, args.harness_host, args.theta_path)
    stage_runner.install_cf_f_non_trigger_turns(
        args.harness_host,
        args.node_config_path,
        theta["calibration"]["non_trigger_eligible_turns"],
    )

    packet_cmd = [
        sys.executable,
        str(Path(__file__).with_name("write_cr2_theta_formula_packet.py")),
        "--run-ids",
        *run_ids,
        "--output-dir",
        str(args.packet_output_dir),
        "--post-validation-dir",
        str(args.post_validation_dir),
    ]
    packet_proc = subprocess.run(packet_cmd, text=True, capture_output=True, check=False)
    if packet_proc.returncode != 0:
        raise RuntimeError(packet_proc.stderr or packet_proc.stdout)

    print(
        json.dumps(
            {
                "status": "cr2_complete_theta_locked",
                "run_ids": run_ids,
                "theta_path": args.theta_path,
                "theta_local_preview": str(theta_path),
                "packet_output": packet_proc.stdout.strip().splitlines(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
