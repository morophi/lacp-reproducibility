#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
import types

import pytest

sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=object))
sys.modules.setdefault("chromadb", types.SimpleNamespace(HttpClient=object))
sys.modules.setdefault(
    "sentence_transformers",
    types.SimpleNamespace(SentenceTransformer=object),
)

from experiment_runner import ExperimentRunner


class DummySCEngine:
    theta_locked = False

    def threshold_snapshot(self):
        return {"theta_lms": 0.0}

    def build_policy_block(self):
        return "[SC-PROTOCOL OPERATING POLICY]\npolicy_id: test\n[/SC-PROTOCOL OPERATING POLICY]"


def runner(config=None):
    obj = object.__new__(ExperimentRunner)
    obj.config = {
        "rag": {"top_k": 5},
        "counterfactual": config or {},
    }
    obj.sc_engine = DummySCEngine()
    return obj


def base_plan():
    trigger = {
        "should_inject_rag": False,
        "apply_sc_to_a": False,
        "apply_sc_to_b": False,
        "reasons": [],
        "trigger_source_nodes": [],
        "threshold_snapshot": {"theta_lms": 0.0},
        "mode": "no_intervention",
        "previous_turn_used_for_trigger": None,
    }
    return {
        "A": {"rag_chunks": [], "sc_policy_block": None, "trigger": trigger},
        "B": {"rag_chunks": [], "sc_policy_block": None, "trigger": trigger},
        "C": {"rag_chunks": [], "sc_policy_block": None, "trigger": trigger},
    }, trigger


def test_cf_b_empty_result_records_audit_without_rag():
    plan, trigger = base_plan()
    result = asyncio.run(runner()._prepare_counterfactual_interventions("cf_b", "u", 1, plan, trigger))
    assert result["A"]["rag_chunks"] == []
    assert result["B"]["rag_chunks"] == []
    assert result["C"]["rag_chunks"] == []
    cf_trigger = result["A"]["trigger"]
    assert cf_trigger["mode"] == "cf_b_empty_result"
    assert cf_trigger["retrieval_audit_required"] is True
    assert cf_trigger["cf_returned_count"] == 0


def test_cf_d_only_forces_manuscript_turns():
    plan, trigger = base_plan()
    result = asyncio.run(
        runner({"cf_d": {"forced_turns": [5, 15, 25]}})._prepare_counterfactual_interventions(
            "cf_d", "u", 4, plan, trigger
        )
    )
    assert result == plan


def test_cf_f_samples_seed_fixed_non_trigger_eligible_turns():
    cfg = {
        "cf_f": {
            "seed": 7,
            "n": 3,
            "non_trigger_eligible_turns": [2, 4, 6, 8, 10],
        }
    }
    assert runner(cfg)._cf_f_injection_turns(cfg) == [4, 6, 8]


def test_cf_a_requires_frozen_substitution_query():
    with pytest.raises(ValueError, match="cf_a.substitution_query"):
        runner()._required_cf_value({}, "cf_a", "substitution_query")


def test_formal_run_b_requires_locked_theta():
    with pytest.raises(ValueError, match="theta_config.locked"):
        runner()._validate_theta_lock("run_b", "formal")


def test_formal_cr_and_cr2_allow_unlocked_theta():
    runner()._validate_theta_lock("cr", "formal")
    runner()._validate_theta_lock("cr2", "formal")


def test_smoke_run_b_allows_unlocked_theta():
    runner()._validate_theta_lock("run_b", "smoke")


def test_formal_cf_requires_locked_theta():
    with pytest.raises(ValueError, match="cf_f"):
        runner()._validate_theta_lock("cf_f", "formal")
