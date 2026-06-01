#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tiny test runner used when pytest is not installed on the harness node."""

from __future__ import annotations

import importlib
import sys
import traceback
import types


class Raises:
    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, typ, val, tb):
        if typ is None:
            raise AssertionError(f"Expected {self.exc.__name__}")
        return issubclass(typ, self.exc)


sys.modules["pytest"] = types.SimpleNamespace(raises=lambda exc: Raises(exc))

MODULES = [
    "tests.test_sc_policy",
    "tests.test_prompt_builder",
    "tests.test_trigger_controller",
    "tests.test_metrics_ma",
    "tests.test_metrics_lms",
    "tests.test_quality_gate",
]


def main() -> int:
    passed = 0
    failed = 0
    for name in MODULES:
        mod = importlib.import_module(name)
        for attr in sorted(dir(mod)):
            if not attr.startswith("test_"):
                continue
            try:
                getattr(mod, attr)()
                print(f"PASS {name}.{attr}")
                passed += 1
            except Exception:
                print(f"FAIL {name}.{attr}")
                traceback.print_exc()
                failed += 1
    print(f"passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
