#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from experiment_runner import ExperimentRunner


class DummySCEngine:
    theta_locked = False


runner = object.__new__(ExperimentRunner)
runner.sc_engine = DummySCEngine()

runner._validate_theta_lock("cr", "formal")
runner._validate_theta_lock("cr2", "formal")
runner._validate_theta_lock("run_b", "smoke")

blocked = False
try:
    runner._validate_theta_lock("run_b", "formal")
except ValueError:
    blocked = True

assert blocked, "formal run_b must be blocked when theta is unlocked"
print("theta_guard_ok")
