#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Small config helpers for the LACP Harness runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def load_config(path: str) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"{path} is not JSON and PyYAML is unavailable") from exc
        data = yaml.safe_load(text)

    if not isinstance(data, dict):
        raise ValueError(f"Config must decode to an object: {path}")
    return _expand_env_values(data)


def _expand_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_values(item) for item in value]
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def normalized_json_hash(obj: Any) -> str:
    import hashlib

    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
