#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Central LACP Harness experiment runner.

Harness owns intervention control, RAG/SC injection, node-specific prompt
assembly, independent histories, concurrent A/B/C calls, metrics, and logging.
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
        config_path: str = "/home/morophi/harness/config/node_config.yaml",
        sc_policy_path: str = "/home/morophi/harness/config/sc_policy.yaml",
        theta_path: str = "/home/morophi/harness/config/theta_config.json",
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
            for node in ("A", "B", "C")
        }

        built = {
            "A": build_messages(
                "A",
                utterance,
                prompt_histories["A"],
                plan["A"]["rag_chunks"],
                plan["A"]["sc_policy_block"],
                self.sc_engine.policy_hash if plan["A"]["sc_policy_block"] else None,
            ),
            "B": build_messages("B", utterance, prompt_histories["B"], plan["B"]["rag_chunks"], None, None),
            "C": build_messages("C", utterance, prompt_histories["C"], None, None, None),
        }
        for node, payload in built.items():
            payload["prompt_metadata"]["history_messages_total"] = len(histories[node])
            payload["prompt_metadata"]["history_messages_used"] = len(prompt_histories[node])
            payload["prompt_metadata"]["history_window_turns"] = self._history_window_for_run_mode(run_mode)

        responses = await asyncio.gather(
            self.node_client.chat("A", built["A"]["messages"], run_mode=run_mode),
            self.node_client.chat("B", built["B"]["messages"], run_mode=run_mode),
            self.node_client.chat("C", built["C"]["messages"], run_mode=run_mode),
        )
        if run_mode == "formal":
            bad_responses = [
                f"{response['node']}:status={response.get('status')}"
                for response in responses
                if not response.get("ok")
            ]
            if bad_responses:
                raise RuntimeError(f"formal node response failed: {', '.join(bad_responses)}")
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
        if run_mode == "formal":
            bad_quality = [
                f"{node}:{quality.get('invalid_reason')}"
                for node, quality in quality_by_node.items()
                if not quality.get("generation_quality_ready") or not quality.get("analysis_eligible")
            ]
            if bad_quality:
                raise RuntimeError(f"formal node quality gate failed: {', '.join(bad_quality)}")

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
            "A": {"rag_chunks": [], "sc_policy_block": None, "trigger": empty_trigger},
            "B": {"rag_chunks": [], "sc_policy_block": None, "trigger": empty_trigger},
            "C": {"rag_chunks": [], "sc_policy_block": None, "trigger": empty_trigger},
        }

        if condition in {"tr", "cr", "cr2"}:
            return plan

        if condition == "run_b":
            trigger = self.trigger_controller.evaluate_shared_trigger(
                previous_metrics=previous_metrics,
                turn_no=turn_no,
                condition=condition,
                run_mode=run_mode,
            )
            rag_chunks = []
            if trigger["should_inject_rag"]:
                mode_cfg = self.config.get("run_modes", {}).get(run_mode, {})
                top_k = int(mode_cfg.get("rag_top_k", self.config["rag"].get("top_k", 5)))
                rag_chunks = await self._rag_client().retrieve(utterance, top_k=top_k)

            sc_policy_block = None
            if trigger["apply_sc_to_a"] and (rag_chunks or self.config.get("run", {}).get("sc_without_rag", False)):
                sc_policy_block = self.sc_engine.build_policy_block()

            plan["A"] = {
                "rag_chunks": rag_chunks,
                "sc_policy_block": sc_policy_block,
                "trigger": trigger,
            }
            plan["B"] = {
                "rag_chunks": rag_chunks,
                "sc_policy_block": None,
                "trigger": trigger,
            }
            plan["C"] = {"rag_chunks": [], "sc_policy_block": None, "trigger": trigger}
            return plan

        if condition.startswith("cf_"):
            return await self._prepare_counterfactual_interventions(condition, utterance, turn_no, plan, empty_trigger)

        raise ValueError(f"Unsupported condition: {condition}")

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
            query = self._required_cf_value(cf_cfg, "cf_a", "substitution_query")
            chunks = await self._retrieve_cf_chunks(query, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_a_content_substitution",
                ["content_substitution_document_pair_frozen"],
                query,
            )
            return self._forced_ab_plan(plan, chunks, trigger)

        if condition == "cf_b":
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_b_empty_result",
                ["null_retrieval_result_injected"],
                "",
                retrieval_audit_required=True,
                returned_count=0,
            )
            return self._forced_ab_plan(plan, [], trigger, apply_sc=False)

        if condition == "cf_c":
            query = self._required_cf_value(cf_cfg, "cf_c", "opposing_query")
            chunks = await self._retrieve_cf_chunks(query, top_k=top_k)
            trigger = self._cf_trigger(
                empty_trigger,
                condition,
                turn_no,
                "cf_c_opposing_document",
                ["opposing_previous_version_document_frozen"],
                query,
            )
            return self._forced_ab_plan(plan, chunks, trigger)

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
                ["forced_temporal_shift_turn"],
                utterance,
            )
            return self._forced_ab_plan(plan, chunks, trigger)

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
                "cf_f_forced_random_intervention",
                ["seed_fixed_non_trigger_eligible_forced_random_intervention"],
                utterance,
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
    ) -> Dict[str, Dict[str, Any]]:
        sc_policy_block = None
        if apply_sc and rag_chunks:
            sc_policy_block = self.sc_engine.build_policy_block()
        plan["A"] = {"rag_chunks": rag_chunks, "sc_policy_block": sc_policy_block, "trigger": trigger}
        plan["B"] = {"rag_chunks": rag_chunks, "sc_policy_block": None, "trigger": trigger}
        plan["C"] = {"rag_chunks": [], "sc_policy_block": None, "trigger": trigger}
        return plan

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
    ) -> Dict[str, Any]:
        query_hash = _sha256_text(retrieval_query) if retrieval_query else _sha256_text("")
        return {
            **base,
            "should_inject_rag": bool(retrieval_query),
            "apply_sc_to_a": bool(retrieval_query),
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
            return explicit
        candidates = cf_f.get("non_trigger_eligible_turns")
        if not isinstance(candidates, list) or not all(isinstance(item, int) for item in candidates):
            raise ValueError(
                "cf_f.injection_turns or cf_f.non_trigger_eligible_turns must be frozen from CR2 before execution"
            )
        n = int(cf_f.get("n", 5))
        seed = int(cf_f.get("seed", 424242))
        if len(candidates) < n:
            raise ValueError("cf_f.non_trigger_eligible_turns has fewer entries than required n")
        return sorted(random.Random(seed).sample(candidates, n))

    def _histories_for_run(self, run_id: str) -> Dict[str, List[Dict[str, str]]]:
        if run_id not in self.histories:
            self.histories[run_id] = {"A": [], "B": [], "C": []}
        return self.histories[run_id]

    def _rag_client(self) -> RAGClient:
        # RAG is initialized lazily so CR/CR2 and formal turn-1 no-trigger
        # preflights can still validate A/B/C inference, metrics, and DB paths
        # even when the retrieval service is temporarily unhealthy.
        if self.rag_client is None:
            rag_cfg = self.config["rag"]
            self.rag_client = RAGClient(
                host=rag_cfg.get("host", "10.1.1.120"),
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
        sc_applied = bool(prompt_metadata["sc_policy_applied"])
        return {
            "run_id": turn_payload["run_id"],
            "scenario_id": turn_payload["scenario_id"],
            "scenario_hash": turn_payload.get("scenario_hash"),
            "condition": turn_payload.get("condition"),
            "run_mode": run_mode,
            "turn_no": int(turn_payload["turn_no"]),
            "node": node,
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
            "trigger_source_nodes": trigger.get("trigger_source_nodes", []),
            "threshold_snapshot": trigger.get("threshold_snapshot", {}),
            "previous_turn_used_for_trigger": trigger.get("previous_turn_used_for_trigger"),
            "rag_chunk_ids": prompt_metadata["rag_chunk_ids"],
            "rag_query_hash": trigger.get("retrieval_query_hash") or _sha256_text(turn_payload["utterance"]),
            "retrieval_audit_required": trigger.get("retrieval_audit_required", False),
            "rag_context_chars": prompt_metadata.get("rag_context_chars"),
            "retrieved_chunk_ids": prompt_metadata.get("retrieved_chunk_ids", prompt_metadata["rag_chunk_ids"]),
            "chunk_lengths": prompt_metadata.get("chunk_lengths", []),
            "block_type_distribution": prompt_metadata.get("block_type_distribution", {}),
            "collection_name": prompt_metadata.get("collection_name"),
            "top_k": prompt_metadata.get("top_k"),
            "returned_count": trigger.get("cf_returned_count", prompt_metadata.get("returned_count")),
            "retrieval_method": prompt_metadata.get("retrieval_method"),
            "table_exposure": prompt_metadata.get("table_exposure"),
            "prompt_hash": prompt_metadata["prompt_hash"],
            "payload_hash": prompt_metadata.get("payload_hash"),
            "message_count": prompt_metadata.get("message_count"),
            "prompt_chars": prompt_metadata.get("prompt_chars"),
            "model_name": self.node_client.model_name,
            "temperature": self.node_client.temperature,
            "seed": self.node_client.seed,
            "thinking_disabled_requested": not self.node_client.thinking,
            "endpoint_mode": response.get("endpoint_mode"),
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
