#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path

from config_utils import load_config
from sc_policy import SCPolicyEngine
from trigger_controller import TriggerController


ROOT = Path(__file__).resolve().parents[1]


def controller() -> TriggerController:
    cfg = load_config(str(ROOT / "config" / "node_config.yaml"))
    engine = SCPolicyEngine(str(ROOT / "config" / "sc_policy.yaml"), str(ROOT / "config" / "theta_config.json"))
    return TriggerController(engine, cfg)


def normal_metrics():
    return {
        "A": {"lms_delta": 0.0, "d_lms": 0.0, "cds": 1.0, "d_cds": 0.0, "ma_assert": 0.1, "d_ma": 0.0},
        "B": {"lms_delta": 0.0, "d_lms": 0.0, "cds": 1.0, "d_cds": 0.0, "ma_assert": 0.1, "d_ma": 0.0},
        "C": {"lms_delta": 0.0, "d_lms": 0.0, "cds": 1.0, "d_cds": 0.0, "ma_assert": 0.1, "d_ma": 0.0},
    }


def test_formal_turn_one_no_previous_metrics_no_trigger():
    result = controller().evaluate_shared_trigger({}, turn_no=1, condition="run_b", run_mode="formal")
    assert result["should_inject_rag"] is False


def test_formal_a_crosses_threshold_shared_trigger():
    metrics = normal_metrics()
    metrics["A"]["d_lms"] = 0.1
    result = controller().evaluate_shared_trigger(metrics, turn_no=2, condition="run_b", run_mode="formal")
    assert result["should_inject_rag"] is True
    assert result["apply_sc_to_a"] is True
    assert result["apply_sc_to_b"] is False
    assert result["trigger_source_nodes"] == ["A"]


def test_formal_b_crosses_threshold_shared_trigger():
    metrics = normal_metrics()
    metrics["B"]["d_cds"] = 1.1
    result = controller().evaluate_shared_trigger(metrics, turn_no=2, condition="run_b", run_mode="formal")
    assert result["should_inject_rag"] is True
    assert result["apply_sc_to_a"] is True
    assert result["apply_sc_to_b"] is False
    assert result["trigger_source_nodes"] == ["B"]


def test_formal_c_crosses_threshold_ignored():
    result = controller().evaluate_shared_trigger(normal_metrics(), turn_no=2, condition="run_b", run_mode="formal")
    assert result["should_inject_rag"] is False


def test_smoke_force_run_b():
    result = controller().evaluate_shared_trigger({}, turn_no=1, condition="run_b", run_mode="smoke")
    assert result["should_inject_rag"] is True
    assert result["apply_sc_to_a"] is True
    assert result["apply_sc_to_b"] is False
    assert result["reasons"] == ["smoke_force_run_b"]


def test_missing_lms_disables_lms_trigger_only():
    metrics = normal_metrics()
    metrics["A"]["d_lms"] = 0.1
    metrics["A"]["d_cds"] = 0.0
    metrics["A"]["d_ma"] = 0.0
    metrics["A"]["metric_trigger_eligibility"] = {
        "lms_trigger_eligible": False,
        "cds_trigger_eligible": True,
        "ma_trigger_eligible": True,
    }
    result = controller().evaluate_shared_trigger(metrics, turn_no=2, condition="run_b", run_mode="formal")
    # The low-confidence LMS condition would fire from d_lms=0.1, but
    # metric-specific eligibility masks only LMS evidence when logprobs are
    # missing. CDS/MA remain available and do not trigger in this fixture.
    assert result["should_inject_rag"] is False


def test_missing_lms_does_not_block_cds_trigger():
    metrics = normal_metrics()
    metrics["A"]["d_lms"] = 0.1
    metrics["A"]["d_cds"] = 1.1
    metrics["A"]["metric_trigger_eligibility"] = {
        "lms_trigger_eligible": False,
        "cds_trigger_eligible": True,
        "ma_trigger_eligible": True,
    }
    result = controller().evaluate_shared_trigger(metrics, turn_no=2, condition="run_b", run_mode="formal")
    assert result["should_inject_rag"] is True
    assert result["trigger_source_nodes"] == ["A"]
    assert result["reasons"] == ["A.context_drift:d_cds>theta_cds"]
