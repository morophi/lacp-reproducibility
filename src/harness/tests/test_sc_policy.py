#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from sc_policy import SCPolicyEngine


ROOT = Path(__file__).resolve().parents[1]


def engine() -> SCPolicyEngine:
    return SCPolicyEngine(str(ROOT / "config" / "sc_policy.yaml"), str(ROOT / "config" / "theta_config.json"))


def test_below_thresholds_no_trigger():
    decision = engine().evaluate_trigger({"d_lms": 0.0, "d_cds": 0.0, "d_ma": 0.0})
    assert decision.should_inject_rag is False


def test_lms_low_confidence_triggers():
    decision = engine().evaluate_trigger({"d_lms": 0.1, "d_cds": 0.0, "d_ma": 0.0})
    assert decision.should_inject_rag is True
    assert "low_confidence" in decision.reasons


def test_cds_context_drift_triggers():
    decision = engine().evaluate_trigger({"d_lms": 0.0, "d_cds": 1.1, "d_ma": 0.0})
    assert decision.should_inject_rag is True
    assert "context_drift" in decision.reasons


def test_ma_weak_assertion_triggers():
    decision = engine().evaluate_trigger({"d_lms": 0.0, "d_cds": 0.0, "d_ma": 0.1})
    assert decision.should_inject_rag is True
    assert "weak_assertion" in decision.reasons


def test_policy_block_and_hash_stable():
    e = engine()
    assert e.build_policy_block() == e.build_policy_block()
    assert e.policy_hash == engine().policy_hash
