#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HTTP receiver for the LACP Harness runtime.

POST /turn is the only runtime entrypoint used by the agent/jump scenario
sender. All RAG, SC-Protocol, prompt assembly, node calls, histories, metrics,
and logging happen inside Harness after receipt.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict

from aiohttp import web

from config_utils import load_config
from experiment_runner import ExperimentRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LACP Harness /turn server.")
    parser.add_argument("--config", default="/home/morophi/harness/config/node_config.yaml")
    parser.add_argument("--sc-policy", default="/home/morophi/harness/config/sc_policy.yaml")
    parser.add_argument("--theta", default="/home/morophi/harness/config/theta_config.json")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser.parse_args()


def create_app(args: argparse.Namespace) -> web.Application:
    runner = ExperimentRunner(args.config, args.sc_policy, args.theta)
    app = web.Application()
    app["runner"] = runner

    async def handle_turn(request: web.Request) -> web.Response:
        try:
            payload: Dict[str, Any] = await request.json()
            result = await request.app["runner"].handle_turn(payload)
            return web.json_response(result)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def flush_logs(request: web.Request) -> web.Response:
        try:
            timeout = float(request.query.get("timeout", "30"))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, request.app["runner"].flush_logs, timeout)
            return web.json_response({"ok": True})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def close_runner(app: web.Application) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, app["runner"].close)

    app.router.add_post("/turn", handle_turn)
    app.router.add_post("/flush", flush_logs)
    app.on_cleanup.append(close_runner)
    return app


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    host = args.host or cfg.get("harness", {}).get("host", "0.0.0.0")
    port = args.port or int(cfg.get("harness", {}).get("port", 9000))
    web.run_app(create_app(args), host=host, port=port)


if __name__ == "__main__":
    main()
