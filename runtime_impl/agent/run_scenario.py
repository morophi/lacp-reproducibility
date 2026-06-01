#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CLI entrypoint for the LACP Scenario Agent.

This script only replays pre-written scenario JSON turns to Harness. It does
not mutate scenario files or perform experiment-control work.
"""

from __future__ import annotations

import argparse
import asyncio

from scenario_sender import send_scenario


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send an existing LACP scenario JSON to Harness turn-by-turn.")
    parser.add_argument("--scenario", required=True, help="Path to existing scenario JSON")
    parser.add_argument("--run-id", required=True, help="Experiment run id")
    parser.add_argument("--condition", default=None, help="Experiment condition, e.g. run_b")
    parser.add_argument("--run-mode", default=None, choices=["formal", "smoke"], help="Harness run mode")
    parser.add_argument("--harness-url", default="http://10.1.1.110:9000", help="Harness base URL")
    parser.add_argument("--max-turns", type=int, default=None, help="Optional preflight limit; scenario JSON is not modified")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        send_scenario(
            args.scenario,
            args.harness_url,
            args.run_id,
            args.condition,
            args.run_mode,
            max_turns=args.max_turns,
        )
    )


if __name__ == "__main__":
    main()
