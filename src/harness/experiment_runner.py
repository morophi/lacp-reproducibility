#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Central LACP Harness experiment runner.

Harness owns intervention control, RAG/SC injection, node-specific prompt
assembly, independent histories, concurrent node calls, metrics, and logging.
The scenario agent only supplies immutable utterances.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_utils import load_config, normalized_json_hash
from logger import build_logger
from metrics import MetricComputer
from node_client import NodeClient
from prompt_builder import build_messages
from quality_gate import check_output_quality
from rag_client import RAGClient
from sc_policy import SCPolicyEngine, TriggerDecision
from trigger_controller import TriggerController


VALID_CONDITIONS = {"tr", "run_b", "cf_a", "cf_b", "cf_c", "cf_d", "cf_e", "cf_f", "cr", "cr2"}
THETA_LOCK_REQUIRED_CONDITIONS = {"run_b", "cf_a", "cf_b", "cf_c", "cf_d", "cf_e", "cf_f"}
NODE_ROLES = {"rag_sc", "rag_only", "baseline", "inactive"}
REV11_DESIGN = "rag_response_shift_rev11"
CF_F_DEFAULT_INJECTION_TURNS = [3, 6, 9, 12, 15, 18, 21, 24, 27, 29]
CF_F_END_BOUNDARY_STRESS_CONDITION = "cf_f_end_boundary_stress"
CF_PLAN_ID = "lacp_cf_scenario_plan_v4_cff_turnset_final"
FORMAL_LANGUAGE_RETRY_POLICY = "formal_language_contamination_retry_v1"
FORMAL_LANGUAGE_RETRY_GUARD = (
    "Formal language retry guard: answer in Korean wording only. "
    "Do not use Japanese kana, Chinese ideographs, Hanja, or mixed-language phrases. "
    "If source labels or copied context contain non-Korean scripts, paraphrase them in Korean."
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class ExperimentRunner:
    def __init__(
        self,
        config_path: str = "/home/lacp/harness/config/node_config.yaml",
        sc_policy_path: str = "/home/lacp/harness/config/sc_policy.yaml",
        theta_path: str = "/home/lacp/harness/config/theta_config.json",
    ):
        self.config_path = config_path
        self.sc_policy_path = sc_policy_path
        self.theta_path = theta_path
        self.config = load_config(config_path)
        self.sc_engine = SCPolicyEngine(sc_policy_path, theta_path)
        theta_config = load_config(theta_path)
        theta_entropy = theta_config.get("theta_entropy")
        if isinstance(theta_entropy, (int, float)):
            self.config.setdefault("metrics", {}).setdefault("lms", {})["theta_entropy"] = float(theta_entropy)
        if not self.sc_engine.theta_locked:
            print("WARNING: theta_config locked=false. Use only for dev/test runs.")
        self._validate_node_roles()
        self.active_nodes = self._active_nodes()

        self.rag_client: Optional[RAGClient] = None
        self.node_client = NodeClient(
            self.config["nodes"],
            self.config["model"],
            self.config.get("run_modes", {}),
        )
        self.metric_computer = MetricComputer(self.config)
        self.trigger_controller = TriggerController(self.sc_engine, self.config)
        self.logger = build_logger(self.config["logging"])
        self.histories: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        self.last_metrics: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def flush_logs(self, timeout: Optional[float] = None) -> None:
        self.logger.flush(timeout)

    def close(self) -> None:
        self.logger.close()

    async def handle_turn(self, turn_payload: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_turn_payload(turn_payload)
        run_id = turn_payload["run_id"]
        scenario_id = turn_payload["scenario_id"]
        condition = (turn_payload.get("condition") or "run_b").lower()
        run_mode = (turn_payload.get("run_mode") or self.config.get("run", {}).get("default_mode", "formal")).lower()
        self._validate_theta_lock(condition, run_mode)
        turn_no = int(turn_payload["turn_no"])
        utterance = turn_payload["utterance"]

        histories = self._histories_for_run(run_id)
        metrics_for_run = self.last_metrics.setdefault(run_id, {})
        plan = await self._prepare_interventions(condition, utterance, metrics_for_run, turn_no, run_mode)
        prompt_histories = {
            node: self._bounded_prompt_history(histories[node], run_mode)
            for node in self.active_nodes
        }

        built = {}
        for node in self.active_nodes:
            sc_policy_block = plan[node]["sc_policy_block"]
            built[node] = build_messages(
                node,
                utterance,
                prompt_histories[node],
                plan[node]["rag_chunks"],
                sc_policy_block,
                self.sc_engine.policy_hash if sc_policy_block else None,
                plan[node].get("sc_policy_payload"),
            )
        for node, payload in built.items():
            payload["prompt_metadata"]["history_messages_total"] = len(histories[node])
            payload["prompt_metadata"]["history_messages_used"] = len(prompt_histories[node])
            payload["prompt_metadata"]["history_window_turns"] = self._history_window_for_run_mode(run_mode)
            payload["prompt_metadata"]["node_role"] = self._node_role(node)
            payload["prompt_metadata"]["physical_node_url"] = self.config["nodes"][node].get("url")

        responses = await asyncio.gather(
            *[
                self._chat_with_formal_quality_retry(
                    node,
                    built[node]["messages"],
                    run_mode,
                    utterance,
                )
                for node in self.active_nodes
            ]
        )
        pending_formal_response_failure = None
        if run_mode == "formal":
            bad_responses = [
                f"{response['node']}:status={response.get('status')}"
                for response in responses
                if not response.get("ok")
            ]
            if bad_responses:
                pending_formal_response_failure = RuntimeError(
                    f"formal node response failed: {', '.join(bad_responses)}"
                )
        # Execute compatibility note:
        # The pipeline order remains response -> quality gate -> metrics ->
        # history policy -> JSONL -> MariaDB. Earlier versions treated formal
        # failed_TR as an immediate runtime exception at this point. That made
        # the run fail fast, but it also prevented the failed node-turn from
        # reaching the evidence ledger. The current policy is preservation
        # first: failed_TR rows continue through quality_gate and logger, then
        # become analysis-ineligible, trigger-ineligible, and history-ineligible.
        # Run-level Go/No-Go must be decided from the later quality summary, not
        # by dropping the row before JSONL/DB persistence.

        nodes_completed = []
        rag_injected = {}
        sc_policy_applied = {}
        node_metrics = {}
        quality_by_node = {}
        for response in responses:
            node = response["node"]
            quality_by_node[node] = check_output_quality(
                clean_text=response.get("text", ""),
                raw_text=response.get("text_raw", ""),
                utterance=utterance,
                node_result=response,
                run_mode=run_mode,
            )
            metric_raw = dict(response.get("raw", {}))
            metric_raw["_harness_clean_logprobs"] = response.get("clean_logprobs", [])
            metric_raw["_harness_excluded_token_positions"] = response.get("excluded_token_positions", [])
            metric_raw["_harness_raw_logprobs_len"] = len(response.get("raw_logprobs", []) or [])
            metric_raw["_harness_clean_logprobs_len"] = len(response.get("clean_logprobs", []) or [])
            node_metrics[node] = self.metric_computer.compute_node_metrics(
                node=node,
                response_text=response.get("text", ""),
                response_raw=metric_raw,
                history=histories[node],
                turn_no=turn_no,
                run_mode=run_mode,
            )
            node_metrics[node]["quality_gate"] = quality_by_node[node]
            node_metrics[node]["analysis_eligible"] = quality_by_node[node]["analysis_eligible"]
            node_metrics[node]["exclude_from_causal_trigger"] = quality_by_node[node]["exclude_from_causal_trigger"]
            node_metrics[node]["history_eligible"] = quality_by_node[node]["history_eligible"]
        pending_formal_quality_failure = None
        if run_mode == "formal":
            bad_quality = [
                f"{node}:{quality.get('invalid_reason')}"
                for node, quality in quality_by_node.items()
                if (
                    not quality.get("generation_quality_ready")
                    or not quality.get("analysis_eligible")
                )
                and self._formal_quality_blocks_run(quality)
            ]
            if bad_quality:
                pending_formal_quality_failure = RuntimeError(
                    f"formal node quality gate failed: {', '.join(bad_quality)}"
                )

        cross_metrics = self.metric_computer.compute_cross_node_metrics(node_metrics)
        for node, metrics in node_metrics.items():
            metrics.update(cross_metrics.get(node, {}))
            metrics_for_run[node] = metrics

        for response in responses:
            node = response["node"]
            metadata = built[node]["prompt_metadata"]
            metrics = node_metrics[node]
            self._append_history_if_eligible(
                histories[node],
                utterance,
                response.get("text", ""),
                quality_by_node[node],
            )
            row = self._log_row(
                turn_payload=turn_payload,
                run_mode=run_mode,
                node=node,
                response=response,
                prompt_metadata=metadata,
                trigger=plan[node]["trigger"],
                metrics=metrics,
                quality_gate=quality_by_node[node],
            )
            self.logger.log_turn(run_id, row)
            nodes_completed.append(node)
            rag_injected[node] = metadata["rag_injected"]
            sc_policy_applied[node] = metadata["sc_policy_applied"]

        if pending_formal_response_failure is not None:
            raise pending_formal_response_failure
        if pending_formal_quality_failure is not None:
            raise pending_formal_quality_failure

        return {
            "ok": True,
            "run_id": run_id,
            "scenario_id": scenario_id,
            "turn_no": turn_no,
            "run_mode": run_mode,
            "nodes_completed": nodes_completed,
            "rag_injected": rag_injected,
            "sc_policy_applied": sc_policy_applied,
        }

    async def _chat_with_formal_quality_retry(
        self,
        node: str,
        messages: List[Dict[str, str]],
        run_mode: str,
        utterance: str,
    ) -> Dict[str, Any]:
        response = await self.node_client.chat(node, messages, run_mode=run_mode)
        if run_mode != "formal":
            return response

        quality = check_output_quality(
            clean_text=response.get("text", ""),
            raw_text=response.get("text_raw", ""),
            utterance=utterance,
            node_result=response,
            run_mode=run_mode,
        )
        if not self._formal_quality_retryable(quality):
            return response

        retry_messages = self._messages_with_language_retry_guard(messages)
        retry_response = await self.node_client.chat(node, retry_messages, run_mode=run_mode)
        retry_quality = check_output_quality(
            clean_text=retry_response.get("text", ""),
            raw_text=retry_response.get("text_raw", ""),
            utterance=utterance,
            node_result=retry_response,
            run_mode=run_mode,
        )
        retry_response.update({
            "quality_retry_policy": FORMAL_LANGUAGE_RETRY_POLICY,
            "quality_retry_attempted": True,
            "quality_retry_reason": quality.get("invalid_reason"),
            "quality_retry_first_response_hash": _sha256_text(response.get("text", "")),
            "quality_retry_first_response_raw_hash": _sha256_text(response.get("text_raw", "")),
            "quality_retry_first_contamination_spans": quality.get("contamination_spans", []),
            "quality_retry_first_elapsed_ms": response.get("elapsed_ms"),
            "quality_retry_final_invalid_reason": retry_quality.get("invalid_reason"),
        })
        return retry_response

    @staticmethod
    def _formal_quality_retryable(quality: Dict[str, Any]) -> bool:
        invalid_reason = quality.get("invalid_reason")
        if not invalid_reason:
            return False
        reasons = {
            part.strip()
            for part in str(invalid_reason).split("+")
            if part.strip()
        }
        return reasons == {"language_contamination"}

    @staticmethod
    def _messages_with_language_retry_guard(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        guarded: List[Dict[str, str]] = []
        inserted = False
        for index, message in enumerate(messages):
            guarded.append(dict(message))
            if index == 0 and message.get("role") == "system":
                guarded.append({"role": "system", "content": FORMAL_LANGUAGE_RETRY_GUARD})
                inserted = True
        if not inserted:
            guarded.insert(0, {"role": "system", "content": FORMAL_LANGUAGE_RETRY_GUARD})
        return guarded

    async def _prepare_interventions(
        self,
        condition: str,
        utterance: str,
        previous_metrics: Dict[str, Dict[str, Any]],
        turn_no: int,
        run_mode: str,
    ) -> Dict[str, Dict[str, Any]]:
        empty_trigger = {
            "should_inject_rag": False,
            "apply_sc_to_a": False,
            "apply_sc_to_b": False,
            "reasons": [],
            "trigger_source_nodes": [],
            "threshold_snapshot": self.sc_engine.threshold_snapshot(),
            "mode": "no_intervention",
            "previous_turn_used_for_trigger": None,
        }
        plan = {
            node: {"rag_chunks": [], "sc_policy_block": None, "sc_policy_payload": None, "trigger": empty_trigger}
            for node in self.active_nodes
        }

        if condition in {"tr", "cr"}:
            return plan

        if condition == "cr2":
            return await self._prepare_cr2_interventions(utterance, plan, empty_trigger, run_mode)

        if condition == "run_b":
            trigger = self.trigger_controller.evaluate_shared_trigger(
                previous_metrics=previous_metrics,
                turn_no=turn_no,
                condition=condition,
                run_mode=run_mode,
            )
            if self._fixed_run_b_rag_exposure_enabled():
                mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
                top_k = int(mode_cfg.get("rag_top_k", self.config["rag"].get("top_k", 5)))
                rag_chunks = await self._rag_client().retrieve(utterance, top_k=top_k)
                trigger = {
                    **trigger,
                    "rag_exposure_mode": "fixed_ab_rag_exposure",
                    "retrieval_query_hash": _sha256_text(utterance),
                    "returned_count": len(rag_chunks),
                }
                if self._rev11_fixed_rag_exposure_enabled():
                    trigger = {
                        **trigger,
                        "should_inject_rag": bool(rag_chunks),
                        "apply_sc_to_a": False,
                        "apply_sc_to_b": False,
                        "reasons": ["rev11_fixed_rag_exposure"],
                        "trigger_source_nodes": [],
                        "mode": "fixed_rag_exposure",
                    }
                self._apply_role_plan(plan, rag_chunks, trigger, apply_sc=bool(trigger.get("apply_sc_to_a")))
                return plan

            rag_chunks = []
            if trigger["should_inject_rag"]:
                mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
                top_k = int(mode_cfg.get("rag_top_k", self.config["rag"].get("top_k", 5)))
                rag_chunks = await self._rag_client().retrieve(utterance, top_k=top_k)

            self._apply_role_plan(plan, rag_chunks, trigger)
            return plan

        if condition.startswith("cf_"):
            return await self._prepare_counterfactual_interventions(condition, utterance, turn_no, plan, empty_trigger)

        raise ValueError(f"Unsupported condition: {condition}")

    async def _prepare_cr2_interventions(
        self,
        utterance: str,
        plan: Dict[str, Dict[str, Any]],
        empty_trigger: Dict[str, Any],
        run_mode: str,
    ) -> Dict[str, Dict[str, Any]]:
        mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
        top_k = int(mode_cfg.get("rag_top_k", self.config["rag"].get("top_k", 5)))
        rag_chunks = await self._rag_client().retrieve(utterance, top_k=top_k)
        if not rag_chunks:
            raise ValueError("CR2 intervention exposure requires non-empty RAG chunks")

        trigger = {
            **empty_trigger,
            "should_inject_rag": True,
            "apply_sc_to_a": True,
            "apply_sc_to_b": False,
            "reasons": ["cr2_intervention_exposure"],
            "trigger_source_nodes": [],
            "mode": "cr2_intervention_exposure",
            "retrieval_query_hash": _sha256_text(utterance),
        }
        self._apply_role_plan(plan, rag_chunks, trigger, apply_sc=True)
        return plan

    async def _prepare_counterfactual_interventions(
        self,
        condition: str,
        utterance: str,
        turn_no: int,
        plan: Dict[str, Dict[str, Any]],
        empty_trigger: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        cf_cfg = self.config.get("counterfactual", {})
        top_k = int(cf_cfg.get("top_k", self.config["rag"].get("top_k", 5)))

        if condition == "cf_a":
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_a_baseline_replay",
                ["rag_off_sc_off_baseline_replay"],
                "",
                should_inject_rag=False,
                apply_sc_to_a=False,
            )
            return self._all_nodes_plan(plan, trigger)

        if condition == "cf_b":
            chunks = await self._retrieve_cf_chunks(utterance, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_b_rag_only_forced",
                ["rag_only_forced_across_ab_sc_off"],
                utterance,
                should_inject_rag=True,
                apply_sc_to_a=False,
                returned_count=len(chunks),
            )
            return self._forced_ab_plan(plan, chunks, trigger, apply_sc=False)

        if condition == "cf_c":
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_c_sc_only_rag_off",
                ["sc_only_without_retrieved_domain_evidence"],
                "",
                should_inject_rag=False,
                apply_sc_to_a=True,
            )
            return self._forced_ab_plan(plan, [], trigger, allow_sc_without_rag=True)

        if condition == "cf_d":
            forced_turns = self._cf_turns(cf_cfg, "cf_d", default=[5, 15, 25])
            if turn_no not in forced_turns:
                return plan
            chunks = await self._retrieve_cf_chunks(utterance, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_d_temporal_shift",
                ["rag_present_sc_anchor_mismatched_or_delayed"],
                utterance,
                should_inject_rag=True,
                apply_sc_to_a=True,
                returned_count=len(chunks),
            )
            # CF-D deliberately tests RAG-present / SC-absent turns. The trigger
            # metadata records forced-assignment intent; the empty SC chunk list
            # is what keeps the actual prompt SC policy off for this condition.
            return self._forced_ab_plan(plan, chunks, trigger, sc_chunks=[])

        if condition == "cf_e":
            query = self._required_cf_value(cf_cfg, "cf_e", "external_payload_query")
            chunks = await self._retrieve_cf_chunks(query, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_e_internal_external_separation",
                ["external_payload_substituted_internal_cues_fixed"],
                query,
                should_inject_rag=True,
                apply_sc_to_a=True,
                returned_count=len(chunks),
            )
            return self._forced_ab_plan(plan, chunks, trigger)

        if condition == "cf_f":
            injection_turns = self._cf_f_injection_turns(cf_cfg)
            if turn_no not in injection_turns:
                return plan
            chunks = await self._retrieve_cf_chunks(utterance, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_f_trigger_independent_forced_assignment",
                ["pre_registered_trigger_independent_forced_assignment"],
                utterance,
                should_inject_rag=True,
                apply_sc_to_a=True,
                returned_count=len(chunks),
                extra={
                    "cf_plan_id": cf_cfg.get("cf_plan_id", CF_PLAN_ID),
                    "forced_turn_set": injection_turns,
                    "turn_30_forced": 30 in injection_turns,
                    "turn_29_runtime_smoke_required": True,
                    "cf_f_default_set": injection_turns == CF_F_DEFAULT_INJECTION_TURNS,
                },
            )
            return self._forced_ab_plan(plan, chunks, trigger)

        raise ValueError(f"Unsupported counterfactual condition: {condition}")

    async def _retrieve_cf_chunks(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if query == "":
            return []
        return await self._rag_client().retrieve(query, top_k=top_k)

    def _forced_ab_plan(
        self,
        plan: Dict[str, Dict[str, Any]],
        rag_chunks: List[Dict[str, Any]],
        trigger: Dict[str, Any],
        apply_sc: bool = True,
        allow_sc_without_rag: bool = False,
        sc_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        self._apply_role_plan(
            plan,
            rag_chunks,
            trigger,
            apply_sc=apply_sc,
            allow_sc_without_rag=allow_sc_without_rag,
            sc_chunks=sc_chunks,
        )
        return plan

    @staticmethod
    def _all_nodes_plan(
        plan: Dict[str, Dict[str, Any]],
        trigger: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        for node in plan:
            plan[node] = {
                "rag_chunks": [],
                "sc_policy_block": None,
                "sc_policy_payload": None,
                "trigger": trigger,
            }
        return plan

    def _apply_role_plan(
        self,
        plan: Dict[str, Dict[str, Any]],
        rag_chunks: List[Dict[str, Any]],
        trigger: Dict[str, Any],
        apply_sc: bool = True,
        allow_sc_without_rag: bool = False,
        sc_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        sc_policy_block = None
        sc_policy_payload = None
        sc_enabled = self._sc_enabled()
        policy_chunks = rag_chunks if sc_chunks is None else sc_chunks
        expected_top_k = self._expected_top_k_for_chunks(policy_chunks)
        if apply_sc and sc_enabled and policy_chunks:
            sc_policy_payload = self.sc_engine.build_policy_payload(trigger, policy_chunks, expected_top_k)
            sc_policy_block = self.sc_engine.build_policy_block(sc_policy_payload)
        elif apply_sc and sc_enabled and (
            allow_sc_without_rag or self.config.get("run", {}).get("sc_without_rag", False)
        ):
            sc_policy_payload = self.sc_engine.build_policy_payload(trigger, policy_chunks, expected_top_k)
            sc_policy_block = self.sc_engine.build_policy_block(sc_policy_payload)

        for node in self.active_nodes:
            role = self._node_role(node)
            plan[node] = {
                "rag_chunks": rag_chunks if role in {"rag_sc", "rag_only"} else [],
                "sc_policy_block": sc_policy_block if role == "rag_sc" else None,
                "sc_policy_payload": sc_policy_payload if role == "rag_sc" else None,
                "trigger": trigger,
            }

    def _expected_top_k_for_chunks(self, rag_chunks: List[Dict[str, Any]]) -> Optional[int]:
        if rag_chunks:
            first = rag_chunks[0]
            if first.get("top_k") is not None:
                return int(first["top_k"])
        return int(self.config.get("rag", {}).get("top_k", 0)) or None

    def _node_role(self, node: str) -> str:
        role = self.config.get("nodes", {}).get(node, {}).get("role")
        return str(role or "").strip().lower()

    def _active_nodes(self) -> List[str]:
        configured_nodes = {
            str(node).upper()
            for node in self.config.get("nodes", {})
        }
        explicit = self.config.get("run", {}).get("active_nodes")
        if explicit is not None:
            if not isinstance(explicit, list) or not explicit:
                raise ValueError("run.active_nodes must be a non-empty list when configured")
            active_nodes = [str(node).upper() for node in explicit]
        else:
            active_nodes = [
                node
                for node in sorted(configured_nodes)
                if self._node_role(node) != "inactive"
            ]

        unknown = [node for node in active_nodes if node not in configured_nodes]
        if unknown:
            raise ValueError(f"run.active_nodes contains unknown nodes: {unknown}")
        inactive = [node for node in active_nodes if self._node_role(node) == "inactive"]
        if inactive:
            raise ValueError(f"run.active_nodes contains inactive nodes: {inactive}")
        return active_nodes

    def _experiment_design(self) -> str:
        return str(self.config.get("run", {}).get("experiment_design") or "legacy_three_node_sc").strip().lower()

    def _sc_enabled(self) -> bool:
        return bool(self.config.get("run", {}).get("sc_enabled", True))

    def _rev11_fixed_rag_exposure_enabled(self) -> bool:
        return (
            self._experiment_design() == REV11_DESIGN
            and self.config.get("run", {}).get("intervention_mode") == "fixed_rag_exposure"
        )

    def _fixed_run_b_rag_exposure_enabled(self) -> bool:
        return self.config.get("run", {}).get("intervention_mode") == "fixed_rag_exposure"

    def _validate_node_roles(self) -> None:
        roles = {str(node).upper(): self._node_role(str(node).upper()) for node in self.config.get("nodes", {})}
        invalid = {node: role for node, role in roles.items() if role not in NODE_ROLES}
        if invalid:
            raise ValueError(f"Invalid node role mapping: {invalid}; expected roles={sorted(NODE_ROLES)}")
        active_nodes = self._active_nodes()
        active_roles = {node: roles[node] for node in active_nodes}
        counts = {role: list(active_roles.values()).count(role) for role in NODE_ROLES}

        if self._experiment_design() == REV11_DESIGN:
            if len(active_nodes) != 2 or counts["rag_only"] != 1 or counts["baseline"] != 1:
                raise ValueError(
                    "Rev11 rag_response_shift mode requires exactly two active nodes: "
                    f"one rag_only and one baseline; got {active_roles}"
                )
            if counts["rag_sc"]:
                raise ValueError(f"Rev11 formal mode excludes rag_sc/SC treatment nodes: {active_roles}")
            if self._sc_enabled():
                raise ValueError("Rev11 formal mode requires run.sc_enabled=false")
            return

        counts = {role: list(active_roles.values()).count(role) for role in NODE_ROLES}
        expected = {"rag_sc": 1, "rag_only": 1, "baseline": 1}
        actual = {role: counts[role] for role in expected}
        if actual != expected:
            raise ValueError(f"Node roles must contain exactly one rag_sc, one rag_only, and one baseline: {roles}")
        if roles.get("A") != "rag_sc":
            raise ValueError("Node A must remain the rag_sc node because SC-Protocol is A-only by design")

    def _cf_trigger(
        self,
        base: Dict[str, Any],
        condition: str,
        turn_no: int,
        mode: str,
        reasons: List[str],
        retrieval_query: str,
        retrieval_audit_required: bool = False,
        returned_count: Optional[int] = None,
        should_inject_rag: Optional[bool] = None,
        apply_sc_to_a: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query_hash = _sha256_text(retrieval_query) if retrieval_query else _sha256_text("")
        inject = bool(retrieval_query) if should_inject_rag is None else bool(should_inject_rag)
        apply_sc = bool(retrieval_query) if apply_sc_to_a is None else bool(apply_sc_to_a)
        return {
            **base,
            "should_inject_rag": inject,
            "apply_sc_to_a": apply_sc,
            "apply_sc_to_b": False,
            "reasons": [f"{condition}.{reason}" for reason in reasons],
            "trigger_source_nodes": ["predeclared_counterfactual_schedule"],
            "mode": mode,
            "previous_turn_used_for_trigger": None,
            "retrieval_query_hash": query_hash,
            "retrieval_audit_required": retrieval_audit_required,
            "cf_condition": condition,
            "cf_turn_no": turn_no,
            "cf_returned_count": returned_count,
            **(extra or {}),
        }

    @staticmethod
    def _required_cf_value(config: Dict[str, Any], condition: str, key: str) -> str:
        value = config.get(condition, {}).get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{condition}.{key} must be frozen in counterfactual config before execution")
        return value.strip()

    @staticmethod
    def _cf_turns(config: Dict[str, Any], condition: str, default: List[int]) -> List[int]:
        value = config.get(condition, {}).get("forced_turns", default)
        if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
            raise ValueError(f"{condition}.forced_turns must be a list of integers")
        return value

    def _cf_f_injection_turns(self, config: Dict[str, Any]) -> List[int]:
        cf_f = config.get("cf_f", {})
        explicit = cf_f.get("injection_turns")
        if isinstance(explicit, list) and all(isinstance(item, int) for item in explicit):
            return self._validate_cf_f_turn_set(explicit or list(CF_F_DEFAULT_INJECTION_TURNS), cf_f)
        candidates = cf_f.get("non_trigger_eligible_turns")
        if candidates == [] or candidates is None:
            return self._validate_cf_f_turn_set(list(CF_F_DEFAULT_INJECTION_TURNS), cf_f)
        if not isinstance(candidates, list) or not all(isinstance(item, int) for item in candidates):
            raise ValueError(
                "cf_f.injection_turns or cf_f.non_trigger_eligible_turns must be frozen from CR2 before execution"
            )
        n = int(cf_f.get("n", 5))
        seed = int(cf_f.get("seed", 424242))
        if len(candidates) < n:
            raise ValueError("cf_f.non_trigger_eligible_turns has fewer entries than required n")
        return self._validate_cf_f_turn_set(sorted(random.Random(seed).sample(candidates, n)), cf_f)

    @staticmethod
    def _validate_cf_f_turn_set(turns: List[int], cf_f: Dict[str, Any]) -> List[int]:
        if any(turn < 1 for turn in turns):
            raise ValueError("CF-F forced turns must use 1-based scenario turn numbers")
        if len(set(turns)) != len(turns):
            raise ValueError(f"CF-F forced turns must be unique: {turns}")
        if 30 in turns and cf_f.get("condition_label") != CF_F_END_BOUNDARY_STRESS_CONDITION:
            raise ValueError(
                "Turn 30 is excluded from default CF-F; use condition_label=cf_f_end_boundary_stress "
                "for a separately labeled end-of-run stress condition"
            )
        if cf_f.get("condition_label") in (None, "", "default", "cf_f_default"):
            if turns != CF_F_DEFAULT_INJECTION_TURNS:
                raise ValueError(
                    "Default CF-F forced turns must equal "
                    f"{CF_F_DEFAULT_INJECTION_TURNS}; got {turns}"
                )
        return turns

    def _histories_for_run(self, run_id: str) -> Dict[str, List[Dict[str, str]]]:
        if run_id not in self.histories:
            self.histories[run_id] = {node: [] for node in self.active_nodes}
        return self.histories[run_id]

    def _rag_client(self) -> RAGClient:
        # RAG is initialized lazily so CR/CR2 and formal turn-1 no-trigger
        # preflights can still validate inference, metrics, and DB paths
        # even when the retrieval service is temporarily unhealthy.
        if self.rag_client is None:
            rag_cfg = self.config["rag"]
            self.rag_client = RAGClient(
                host=rag_cfg.get("host", "rag"),
                port=int(rag_cfg.get("port", 8000)),
                collection=rag_cfg["collection"],
                embedding_model=rag_cfg["embedding_model"],
            )
        return self.rag_client

    @staticmethod
    def _append_history(history: List[Dict[str, str]], utterance: str, response_text: str) -> None:
        history.append({"role": "user", "content": utterance})
        history.append({"role": "assistant", "content": response_text})

    @classmethod
    def _append_history_if_eligible(
        cls,
        history: List[Dict[str, str]],
        utterance: str,
        response_text: str,
        quality_gate: Dict[str, Any],
    ) -> None:
        # History update is the only structural execute step whose downstream
        # behavior changed: the step still occurs in the same position, but it
        # now consults history_eligible before mutating the node's prompt
        # context. This keeps hard failures such as failed_TR, empty response,
        # formal truncation, and intervention contamination in JSONL/DB while
        # preventing them from shortening or steering later prompt context in an
        # undocumented way. analysis_eligible=false alone is not enough to skip
        # history; the quality gate must explicitly mark history_eligible=false.
        if quality_gate.get("history_eligible"):
            cls._append_history(history, utterance, response_text)

    def _history_window_for_run_mode(self, run_mode: str) -> Optional[int]:
        mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
        if isinstance(mode_cfg, dict) and mode_cfg.get("history_window_turns") is not None:
            value = int(mode_cfg["history_window_turns"])
            if value < 1:
                raise ValueError("history_window_turns must be >= 1 when configured")
            return value
        return None

    def _bounded_prompt_history(
        self,
        history: List[Dict[str, str]],
        run_mode: str,
    ) -> List[Dict[str, str]]:
        window_turns = self._history_window_for_run_mode(run_mode)
        if window_turns is None:
            return list(history)
        return list(history[-window_turns * 2 :])

    @staticmethod
    def _validate_turn_payload(payload: Dict[str, Any]) -> None:
        for key in ("run_id", "scenario_id", "turn_no", "utterance"):
            if key not in payload:
                raise ValueError(f"Missing required turn payload field: {key}")
        if not isinstance(payload["utterance"], str) or payload["utterance"] == "":
            raise ValueError("utterance must be a non-empty string")
        condition = (payload.get("condition") or "run_b").lower()
        if condition not in VALID_CONDITIONS:
            raise ValueError(f"Unsupported condition: {condition}")

    def _validate_theta_lock(self, condition: str, run_mode: str) -> None:
        if run_mode != "formal":
            return
        if condition not in THETA_LOCK_REQUIRED_CONDITIONS:
            return
        if self.sc_engine.theta_locked:
            return
        raise ValueError(
            "theta_config.locked must be true before formal Run B or CF execution; "
            f"condition={condition} is blocked until CR2-derived theta values are frozen"
        )

    @staticmethod
    def _formal_quality_blocks_run(quality: Dict[str, Any]) -> bool:
        """Keep policy-anchor misses as baseline observations.

        A policy-anchor failure marks the node-turn as analysis- and
        trigger-ineligible, but by itself it is still a coherent model output
        from the no-intervention baseline. Hard context or infrastructure
        failures continue to stop formal execution.
        """

        invalid_reason = quality.get("invalid_reason")
        if not invalid_reason:
            return False
        reasons = {
            part.strip()
            for part in str(invalid_reason).split("+")
            if part.strip()
        }
        return bool(reasons - {"policy_anchor_failure"})

    @staticmethod
    def _trigger_eligible(condition: str, trigger: Dict[str, Any]) -> bool:
        if condition in {"tr", "cr", "cr2"}:
            return False
        mode = trigger.get("mode")
        if mode == "no_intervention":
            return False
        if condition == "run_b" and mode == "metric_catch_trigger":
            return trigger.get("previous_turn_used_for_trigger") is not None
        if condition.startswith("cf_"):
            return bool(trigger.get("reasons") or trigger.get("trigger_source_nodes"))
        return bool(
            trigger.get("should_inject_rag")
            or trigger.get("apply_sc_to_a")
            or trigger.get("apply_sc_to_b")
            or trigger.get("reasons")
        )

    def _log_row(
        self,
        turn_payload: Dict[str, Any],
        node: str,
        response: Dict[str, Any],
        prompt_metadata: Dict[str, Any],
        trigger: Dict[str, Any],
        metrics: Dict[str, Any],
        run_mode: str,
        quality_gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        response_text = response.get("text", "")
        condition = (turn_payload.get("condition") or "run_b").lower()
        sc_applied = bool(prompt_metadata["sc_policy_applied"])
        sc_payload = prompt_metadata.get("sc_policy_payload") or {}
        history_window = prompt_metadata.get("history_window_turns")
        cf_metadata = {
            key: trigger.get(key)
            for key in (
                "cf_plan_id",
                "forced_turn_set",
                "turn_30_forced",
                "turn_29_runtime_smoke_required",
                "cf_f_default_set",
            )
            if trigger.get(key) is not None
        }
        if cf_metadata:
            metrics = dict(metrics)
            metrics["cf_metadata"] = cf_metadata
        return {
            "run_id": turn_payload["run_id"],
            "scenario_id": turn_payload["scenario_id"],
            "scenario_hash": turn_payload.get("scenario_hash"),
            "condition": condition,
            "stage": turn_payload.get("stage") or condition,
            "run_mode": run_mode,
            "runtime_chain": self.config.get("run", {}).get("runtime_chain"),
            "acceptance_status": "pending",
            "failure_reason": None,
            "turn_no": int(turn_payload["turn_no"]),
            "node": node,
            "node_role": prompt_metadata.get("node_role"),
            "physical_node_url": prompt_metadata.get("physical_node_url"),
            "source_file": turn_payload.get("source_file"),
            "harness_version": self.config.get("harness_version"),
            "node_config_hash": _sha256_file(self.config_path),
            "utterance_hash": _sha256_text(turn_payload["utterance"]),
            "response_text": response_text,
            "response_hash": _sha256_text(response_text),
            "elapsed_ms": response.get("elapsed_ms"),
            "rag_injected": bool(prompt_metadata["rag_injected"]),
            "sc_policy_applied": sc_applied,
            "sc_policy_id": self.sc_engine.policy_id if sc_applied else None,
            "policy_hash": prompt_metadata.get("policy_hash") if sc_applied else None,
            "run_sc_policy_id": self.sc_engine.policy_id,
            "run_policy_hash": self.sc_engine.policy_hash,
            "theta_source": self.theta_path,
            "theta_locked": self.sc_engine.theta_locked,
            "trigger_mode": trigger.get("mode"),
            "trigger_reasons": trigger.get("reasons", []),
            "trigger_eligible": self._trigger_eligible(condition, trigger),
            "cr2_routing_active": condition == "cr2" and trigger.get("mode") == "cr2_intervention_exposure",
            "trigger_source_nodes": trigger.get("trigger_source_nodes", []),
            "cf_plan_id": trigger.get("cf_plan_id"),
            "forced_turn_set": trigger.get("forced_turn_set"),
            "turn_30_forced": trigger.get("turn_30_forced"),
            "turn_29_runtime_smoke_required": trigger.get("turn_29_runtime_smoke_required"),
            "cf_f_default_set": trigger.get("cf_f_default_set"),
            "threshold_snapshot": trigger.get("threshold_snapshot", {}),
            "previous_turn_used_for_trigger": trigger.get("previous_turn_used_for_trigger"),
            "sc_triggered": sc_payload.get("sc_triggered"),
            "sc_trigger_reason": sc_payload.get("sc_trigger_reason"),
            "sc_trigger_rule_id": sc_payload.get("sc_trigger_rule_id"),
            "sc_policy_anchor_chunk_ids": sc_payload.get("sc_policy_anchor_chunk_ids"),
            "sc_evidence_sufficiency": sc_payload.get("sc_evidence_sufficiency"),
            "sc_response_mode": sc_payload.get("sc_response_mode"),
            "sc_verification_required": sc_payload.get("sc_verification_required"),
            "sc_responsibility_boundary_applied": sc_payload.get("sc_responsibility_boundary_applied"),
            "sc_policy_payload": sc_payload if sc_applied else None,
            "rag_chunk_ids": prompt_metadata["rag_chunk_ids"],
            "rag_query_hash": trigger.get("retrieval_query_hash") or _sha256_text(turn_payload["utterance"]),
            "retrieval_audit_required": trigger.get("retrieval_audit_required", False),
            "rag_context_chars": prompt_metadata.get("rag_context_chars"),
            "retrieved_chunk_ids": prompt_metadata.get("retrieved_chunk_ids", prompt_metadata["rag_chunk_ids"]),
            "retrieved_chunk_ids_hash": prompt_metadata.get("retrieved_chunk_ids_hash"),
            "chunk_lengths": prompt_metadata.get("chunk_lengths", []),
            "block_type_distribution": prompt_metadata.get("block_type_distribution", {}),
            "collection_name": prompt_metadata.get("collection_name"),
            "corpus_hash": self.config.get("rag", {}).get("corpus_hash"),
            "corpus_version": self.config.get("rag", {}).get("corpus_version") or self.config.get("rag", {}).get("collection"),
            "top_k": prompt_metadata.get("top_k"),
            "returned_count": trigger.get("cf_returned_count", prompt_metadata.get("returned_count")),
            "retrieval_method": prompt_metadata.get("retrieval_method"),
            "table_exposure": prompt_metadata.get("table_exposure"),
            "configured_rag_top_k": self.config.get("rag", {}).get("top_k"),
            "run_mode_rag_top_k": (self.config.get("run_modes", {}).get(run_mode, {}) or {}).get("rag_top_k"),
            "num_predict": self.node_client._num_predict_for_run_mode(run_mode),
            "top_logprobs": self.node_client._top_logprobs_for_run_mode(run_mode),
            "request_logprobs": self.node_client._request_logprobs_for_run_mode(run_mode),
            "prompt_hash": prompt_metadata["prompt_hash"],
            "payload_hash": prompt_metadata.get("payload_hash"),
            "message_count": prompt_metadata.get("message_count"),
            "prompt_chars": prompt_metadata.get("prompt_chars"),
            "final_prompt_chars": prompt_metadata.get("final_prompt_chars"),
            "sc_block_chars": prompt_metadata.get("sc_block_chars"),
            "sc_block_hash": prompt_metadata.get("sc_block_hash"),
            "prompt_contains_sc_marker": prompt_metadata.get("prompt_contains_sc_marker"),
            "history_window_turns_configured": history_window,
            "history_turns_used": int(prompt_metadata.get("history_messages_used", 0)) // 2,
            "model_name": self.node_client.model_name,
            "temperature": self.node_client.temperature,
            "seed": self.node_client.seed,
            "thinking_disabled_requested": not self.node_client.thinking,
            "endpoint_mode": response.get("endpoint_mode"),
            "quality_retry_policy": response.get("quality_retry_policy"),
            "quality_retry_attempted": response.get("quality_retry_attempted", False),
            "quality_retry_reason": response.get("quality_retry_reason"),
            "quality_retry_first_response_hash": response.get("quality_retry_first_response_hash"),
            "quality_retry_first_response_raw_hash": response.get("quality_retry_first_response_raw_hash"),
            "quality_retry_first_contamination_spans": response.get("quality_retry_first_contamination_spans", []),
            "quality_retry_first_elapsed_ms": response.get("quality_retry_first_elapsed_ms"),
            "quality_retry_final_invalid_reason": response.get("quality_retry_final_invalid_reason"),
            "response_text_raw_hash": _sha256_text(response.get("text_raw", "")),
            "thinking_tag_present": response.get("thinking_tag_present"),
            "empty_thinking_shell": response.get("empty_thinking_shell"),
            "thinking_content_present": response.get("thinking_content_present"),
            "cleaning_applied": response.get("cleaning_applied"),
            "cleaning_allowed": response.get("cleaning_allowed"),
            "failed_TR": response.get("failed_TR"),
            "removed_prefix_chars": response.get("removed_prefix_chars"),
            "raw_logprobs_len": len(response.get("raw_logprobs", []) or []),
            "clean_logprobs_len": len(response.get("clean_logprobs", []) or []),
            "excluded_token_positions": response.get("excluded_token_positions", []),
            "quality_gate": quality_gate,
            "generation_quality_ready": quality_gate.get("generation_quality_ready"),
            "analysis_eligible": quality_gate.get("analysis_eligible"),
            "exclude_from_causal_trigger": quality_gate.get("exclude_from_causal_trigger"),
            "history_eligible": quality_gate.get("history_eligible"),
            "history_exclusion_reason": quality_gate.get("history_exclusion_reason"),
            "usable_as_quality_outcome": quality_gate.get("usable_as_quality_outcome"),
            "metrics": metrics,
            "metric_status": metrics.get("metric_status", {}),
            "raw_response_keys": sorted(response.get("raw", {}).keys()) if isinstance(response.get("raw"), dict) else [],
            "created_at": _now_iso(),
        }
