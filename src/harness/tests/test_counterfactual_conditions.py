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
    policy_id = "test_policy"
    policy_hash = "test_policy_hash"
    theta_locked = False

    def threshold_snapshot(self):
        return {"theta_lms": 0.0}

    def build_policy_payload(self, trigger, rag_chunks, expected_top_k=None):
        return {
            "sc_trigger_reason": ",".join(trigger.get("reasons", [])),
            "sc_trigger_rule_id": trigger.get("mode"),
            "sc_policy_anchor_chunk_ids": [chunk.get("chunk_id") for chunk in rag_chunks],
            "sc_evidence_sufficiency": "sufficient" if rag_chunks else "insufficient",
            "sc_response_mode": "grounded_guidance_not_final_decision",
            "sc_verification_required": ["verify"],
        }

    def build_policy_block(self, payload=None):
        return "[SC-PROTOCOL OPERATING POLICY]\npolicy_id: test\n[/SC-PROTOCOL OPERATING POLICY]"


class DummyRAG:
    async def retrieve(self, utterance, top_k=5):
        return [{"chunk_id": "rev11_chunk_1", "text": f"evidence:{utterance}", "top_k": top_k}]


class EmptyRAG:
    async def retrieve(self, utterance, top_k=5):
        return []


class DummyNodeClient:
    model_name = "dummy-model"
    temperature = 0
    seed = 42
    thinking = False

    def _num_predict_for_run_mode(self, run_mode):
        return 128

    def _top_logprobs_for_run_mode(self, run_mode):
        return 5

    def _request_logprobs_for_run_mode(self, run_mode):
        return True


def runner(config=None):
    obj = object.__new__(ExperimentRunner)
    obj.config = {
        "nodes": {
            "A": {"role": "rag_sc"},
            "B": {"role": "rag_only"},
            "C": {"role": "baseline"},
        },
        "rag": {"top_k": 5},
        "counterfactual": config or {},
    }
    obj.active_nodes = ["A", "B", "C"]
    obj.sc_engine = DummySCEngine()
    obj.node_client = DummyNodeClient()
    obj.config_path = __file__
    obj.theta_path = "theta_config.json"
    return obj


def legacy_rev11_runner():
    obj = runner()
    obj.config["nodes"] = {
        "A": {"role": "rag_only"},
        "B": {"role": "baseline"},
        "C": {"role": "inactive"},
    }
    obj.config["run"] = {
        "experiment_design": "rag_response_shift_rev11",
        "active_nodes": ["A", "B"],
        "intervention_mode": "fixed_rag_exposure",
        "sc_enabled": False,
    }
    obj.active_nodes = ["A", "B"]
    obj._rag_client = lambda: DummyRAG()
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


def test_cf_a_baseline_replay_has_no_rag_or_sc():
    plan, trigger = base_plan()
    result = asyncio.run(runner()._prepare_counterfactual_interventions("cf_a", "u", 1, plan, trigger))
    assert result["A"]["rag_chunks"] == []
    assert result["B"]["rag_chunks"] == []
    assert result["C"]["rag_chunks"] == []
    cf_trigger = result["A"]["trigger"]
    assert cf_trigger["mode"] == "cf_a_baseline_replay"
    assert cf_trigger["should_inject_rag"] is False
    assert cf_trigger["apply_sc_to_a"] is False


def test_cf_b_forces_rag_only_across_ab():
    plan, trigger = base_plan()
    r = runner()
    r._rag_client = lambda: DummyRAG()
    result = asyncio.run(r._prepare_counterfactual_interventions("cf_b", "u", 1, plan, trigger))
    assert result["A"]["rag_chunks"]
    assert result["B"]["rag_chunks"]
    assert result["C"]["rag_chunks"] == []
    assert result["A"]["sc_policy_block"] is None
    assert result["B"]["sc_policy_block"] is None
    assert result["A"]["trigger"]["mode"] == "cf_b_rag_only_forced"


def test_cf_c_applies_sc_only_to_a_without_rag():
    plan, trigger = base_plan()
    result = asyncio.run(runner()._prepare_counterfactual_interventions("cf_c", "u", 1, plan, trigger))
    assert result["A"]["rag_chunks"] == []
    assert result["B"]["rag_chunks"] == []
    assert result["C"]["rag_chunks"] == []
    assert result["A"]["sc_policy_block"]
    assert result["B"]["sc_policy_block"] is None
    assert result["A"]["trigger"]["mode"] == "cf_c_sc_only_rag_off"


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
            "condition_label": "cf_f_cr2_sampled_non_trigger",
            "seed": 7,
            "n": 3,
            "non_trigger_eligible_turns": [2, 4, 6, 8, 10],
        }
    }
    assert runner(cfg)._cf_f_injection_turns(cfg) == [4, 6, 8]


def test_cf_f_uses_predeclared_default_turns_when_not_overridden():
    assert runner({})._cf_f_injection_turns({}) == [3, 6, 9, 12, 15, 18, 21, 24, 27, 29]


def test_cf_f_default_rejects_turn_30():
    cfg = {
        "cf_f": {
            "condition_label": "default",
            "injection_turns": [3, 6, 9, 12, 15, 18, 21, 24, 27, 30],
        }
    }
    with pytest.raises(ValueError, match="Turn 30 is excluded"):
        runner(cfg)._cf_f_injection_turns(cfg)


def test_cf_f_turn_30_requires_end_boundary_stress_label():
    cfg = {
        "cf_f": {
            "condition_label": "cf_f_end_boundary_stress",
            "injection_turns": [30],
        }
    }
    assert runner(cfg)._cf_f_injection_turns(cfg) == [30]


def test_formal_run_b_requires_locked_theta():
    with pytest.raises(ValueError, match="theta_config.locked"):
        runner()._validate_theta_lock("run_b", "formal")


def test_formal_cr_and_cr2_allow_unlocked_theta():
    runner()._validate_theta_lock("cr", "formal")
    runner()._validate_theta_lock("cr2", "formal")


def test_cr2_activates_pre_registered_intervention_exposure():
    r = runner()
    r._rag_client = lambda: DummyRAG()
    result = asyncio.run(r._prepare_interventions("cr2", "u", {}, 1, "formal"))
    trigger = result["A"]["trigger"]

    assert trigger["mode"] == "cr2_intervention_exposure"
    assert trigger["should_inject_rag"] is True
    assert trigger["apply_sc_to_a"] is True
    assert result["A"]["rag_chunks"]
    assert result["A"]["sc_policy_block"]
    assert result["B"]["rag_chunks"]
    assert result["B"]["sc_policy_block"] is None
    assert result["C"]["rag_chunks"] == []
    assert result["C"]["sc_policy_block"] is None
    assert r._trigger_eligible("cr2", trigger) is False


def test_cr2_blocks_empty_retrieval_exposure():
    r = runner()
    r._rag_client = lambda: EmptyRAG()
    with pytest.raises(ValueError, match="CR2 intervention exposure requires non-empty RAG chunks"):
        asyncio.run(r._prepare_interventions("cr2", "u", {}, 1, "formal"))


def test_cr2_log_row_marks_routing_active_without_trigger_eligibility():
    r = runner()
    trigger = {
        "mode": "cr2_intervention_exposure",
        "reasons": ["cr2_intervention_exposure"],
        "trigger_source_nodes": [],
        "retrieval_query_hash": "query_hash",
        "threshold_snapshot": {"theta_lms": 0.0},
    }
    row = r._log_row(
        {
            "run_id": "cr2_sample#1",
            "scenario_id": "sample",
            "condition": "cr2",
            "turn_no": 1,
            "utterance": "u",
        },
        "A",
        {"text": "response", "elapsed_ms": 1, "raw": {}},
        {
            "rag_injected": True,
            "sc_policy_applied": True,
            "sc_policy_payload": {},
            "rag_chunk_ids": ["rev11_chunk_1"],
            "retrieved_chunk_ids": ["rev11_chunk_1"],
            "prompt_hash": "prompt_hash",
        },
        trigger,
        {},
        "formal",
        {},
    )

    assert row["trigger_eligible"] is False
    assert row["cr2_routing_active"] is True


def test_smoke_run_b_allows_unlocked_theta():
    runner()._validate_theta_lock("run_b", "smoke")


def test_formal_cf_requires_locked_theta():
    with pytest.raises(ValueError, match="cf_f"):
        runner()._validate_theta_lock("cf_f", "formal")


def test_legacy_rev11_mode_still_requires_explicit_fixed_rag_exposure():
    result = asyncio.run(legacy_rev11_runner()._prepare_interventions("run_b", "u", {}, 1, "formal"))
    assert result["A"]["rag_chunks"]
    assert result["B"]["rag_chunks"] == []
    assert result["A"]["sc_policy_block"] is None
    assert result["B"]["sc_policy_block"] is None
    assert result["A"]["trigger"]["mode"] == "fixed_rag_exposure"


def test_legacy_rev11_role_validation_excludes_rag_sc():
    obj = legacy_rev11_runner()
    obj.config["nodes"]["A"]["role"] = "rag_sc"
    with pytest.raises(ValueError, match="Rev11 rag_response_shift mode"):
        obj._validate_node_roles()
