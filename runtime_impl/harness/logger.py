#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Harness runtime loggers.

JSONL remains the durable fallback. When MariaDB is configured and PyMySQL is
available, the composite logger also writes normalized rows to dblog. The DB
writer stores quality-gate failures as observations while keeping causal
trigger eligibility explicit in dedicated columns.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _bit(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if bool(value) else 0


class JSONLLogger:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_turn(self, run_id: str, row: Dict[str, Any]) -> None:
        path = self.log_dir / f"{run_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


class MariaDBLogger:
    def __init__(self, db_config: Dict[str, Any]):
        try:
            import pymysql  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on deployment venv
            raise RuntimeError("PyMySQL is required for MariaDB logging") from exc

        self._pymysql = pymysql
        self.db_config = {
            "host": db_config.get("host", "10.1.1.130"),
            "port": int(db_config.get("port", 3306)),
            "user": db_config.get("user", "morophi"),
            "password": db_config.get("password", ""),
            "database": db_config.get("database", "lacp_db"),
            "charset": "utf8mb4",
            "autocommit": False,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        self._conn: Optional[Any] = None
        self._lock = threading.Lock()
        self._experiment_run_ids: Dict[str, int] = {}

    def log_turn(self, run_id: str, row: Dict[str, Any]) -> None:
        del run_id
        # Execute precondition:
        # This writer targets the FK-normalized schema in
        # dblog_schema/lacp_db_schema.sql. JSONL is still written first by
        # CompositeLogger, so a DB/schema mismatch cannot erase local evidence,
        # but the MariaDB transaction will fail until dblog is rebuilt/migrated.
        with self._lock:
            try:
                self._write_turn(row)
            except (self._pymysql.err.OperationalError, self._pymysql.err.InterfaceError):
                self.close()
                self._write_turn(row)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def flush(self, timeout: Optional[float] = None) -> None:
        del timeout

    def _connect(self) -> Any:
        self._conn = self._pymysql.connect(**self.db_config)
        return self._conn

    def _get_connection(self) -> Any:
        conn = self._conn
        if conn is None:
            return self._connect()
        return conn

    def _write_turn(self, row: Dict[str, Any]) -> None:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                experiment_run_id = self._get_experiment_run_id(cur, row)
                turn_node_log_id = self._upsert_turn_node(cur, row, experiment_run_id)
                self._upsert_intervention(cur, row, turn_node_log_id)
                self._upsert_metric(cur, row, turn_node_log_id)
                self._upsert_payload_audit(cur, row, turn_node_log_id)
                if row.get("rag_injected") or row.get("retrieval_audit_required"):
                    self._upsert_rag_retrieval(cur, row, turn_node_log_id)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                self.close()
            raise

    def _get_experiment_run_id(self, cur: Any, row: Dict[str, Any]) -> int:
        run_id = row["run_id"]
        cached = self._experiment_run_ids.get(run_id)
        if cached is not None:
            return cached
        experiment_run_id = self._upsert_experiment_run(cur, row)
        self._experiment_run_ids[run_id] = experiment_run_id
        return experiment_run_id

    def _upsert_experiment_run(self, cur: Any, row: Dict[str, Any]) -> int:
        sql = """
        INSERT INTO experiment_runs (
          run_id, scenario_id, scenario_hash, condition_name, run_mode,
          source_file, harness_version, node_config_hash, sc_policy_id,
          policy_hash, theta_source, theta_locked
        ) VALUES (
          %(run_id)s, %(scenario_id)s, %(scenario_hash)s, %(condition_name)s,
          %(run_mode)s, %(source_file)s, %(harness_version)s,
          %(node_config_hash)s, %(sc_policy_id)s, %(policy_hash)s,
          %(theta_source)s, %(theta_locked)s
        )
        ON DUPLICATE KEY UPDATE
          id=LAST_INSERT_ID(id),
          scenario_id=VALUES(scenario_id),
          scenario_hash=VALUES(scenario_hash),
          condition_name=VALUES(condition_name),
          run_mode=VALUES(run_mode),
          source_file=VALUES(source_file),
          harness_version=VALUES(harness_version),
          node_config_hash=VALUES(node_config_hash),
          sc_policy_id=VALUES(sc_policy_id),
          policy_hash=VALUES(policy_hash),
          theta_source=VALUES(theta_source),
          theta_locked=VALUES(theta_locked)
        """
        params = self._experiment_run_params(row)
        cur.execute(sql, params)
        return int(cur.lastrowid)

    def _upsert_turn_node(self, cur: Any, row: Dict[str, Any], experiment_run_id: int) -> int:
        sql = """
        INSERT INTO turn_node_logs (
          experiment_run_id, turn_no, node, utterance_hash, response_text,
          response_hash, elapsed_ms, model_name, model_digest, temperature,
          seed, thinking_disabled_requested, endpoint_mode, response_text_raw_hash,
          thinking_tag_present, empty_thinking_shell, thinking_content_present,
          cleaning_applied, cleaning_allowed, failed_TR, removed_prefix_chars,
          raw_logprobs_len, clean_logprobs_len, excluded_token_positions,
          quality_gate, generation_quality_ready, analysis_eligible,
          exclude_from_causal_trigger, history_eligible,
          history_exclusion_reason, usable_as_quality_outcome,
          metric_status, metric_trigger_eligibility, metrics_json,
          raw_response_keys
        ) VALUES (
          %(experiment_run_id)s, %(turn_no)s, %(node)s, %(utterance_hash)s,
          %(response_text)s, %(response_hash)s, %(elapsed_ms)s, %(model_name)s,
          %(model_digest)s, %(temperature)s, %(seed)s,
          %(thinking_disabled_requested)s, %(endpoint_mode)s,
          %(response_text_raw_hash)s, %(thinking_tag_present)s,
          %(empty_thinking_shell)s, %(thinking_content_present)s,
          %(cleaning_applied)s, %(cleaning_allowed)s, %(failed_TR)s,
          %(removed_prefix_chars)s, %(raw_logprobs_len)s,
          %(clean_logprobs_len)s, %(excluded_token_positions)s,
          %(quality_gate)s, %(generation_quality_ready)s,
          %(analysis_eligible)s, %(exclude_from_causal_trigger)s,
          %(history_eligible)s, %(history_exclusion_reason)s,
          %(usable_as_quality_outcome)s, %(metric_status)s,
          %(metric_trigger_eligibility)s, %(metrics_json)s,
          %(raw_response_keys)s
        )
        ON DUPLICATE KEY UPDATE
          id=LAST_INSERT_ID(id),
          response_text=VALUES(response_text),
          response_hash=VALUES(response_hash),
          elapsed_ms=VALUES(elapsed_ms),
          endpoint_mode=VALUES(endpoint_mode),
          response_text_raw_hash=VALUES(response_text_raw_hash),
          thinking_tag_present=VALUES(thinking_tag_present),
          empty_thinking_shell=VALUES(empty_thinking_shell),
          thinking_content_present=VALUES(thinking_content_present),
          cleaning_applied=VALUES(cleaning_applied),
          cleaning_allowed=VALUES(cleaning_allowed),
          failed_TR=VALUES(failed_TR),
          removed_prefix_chars=VALUES(removed_prefix_chars),
          raw_logprobs_len=VALUES(raw_logprobs_len),
          clean_logprobs_len=VALUES(clean_logprobs_len),
          excluded_token_positions=VALUES(excluded_token_positions),
          quality_gate=VALUES(quality_gate),
          generation_quality_ready=VALUES(generation_quality_ready),
          analysis_eligible=VALUES(analysis_eligible),
          exclude_from_causal_trigger=VALUES(exclude_from_causal_trigger),
          history_eligible=VALUES(history_eligible),
          history_exclusion_reason=VALUES(history_exclusion_reason),
          usable_as_quality_outcome=VALUES(usable_as_quality_outcome),
          metric_status=VALUES(metric_status),
          metric_trigger_eligibility=VALUES(metric_trigger_eligibility),
          metrics_json=VALUES(metrics_json),
          raw_response_keys=VALUES(raw_response_keys)
        """
        params = self._turn_node_params(row)
        params["experiment_run_id"] = experiment_run_id
        cur.execute(sql, params)
        return int(cur.lastrowid)

    def _upsert_intervention(self, cur: Any, row: Dict[str, Any], turn_node_log_id: int) -> None:
        sql = """
        INSERT INTO intervention_logs (
          turn_node_log_id, rag_injected, sc_policy_applied, sc_policy_id,
          policy_hash, trigger_mode,
          trigger_reasons, trigger_source_nodes, threshold_snapshot,
          previous_turn_used_for_trigger
        ) VALUES (
          %(turn_node_log_id)s, %(rag_injected)s, %(sc_policy_applied)s, %(sc_policy_id)s,
          %(policy_hash)s, %(trigger_mode)s, %(trigger_reasons)s,
          %(trigger_source_nodes)s, %(threshold_snapshot)s,
          %(previous_turn_used_for_trigger)s
        )
        ON DUPLICATE KEY UPDATE
          rag_injected=VALUES(rag_injected),
          sc_policy_applied=VALUES(sc_policy_applied),
          sc_policy_id=VALUES(sc_policy_id),
          policy_hash=VALUES(policy_hash),
          trigger_mode=VALUES(trigger_mode),
          trigger_reasons=VALUES(trigger_reasons),
          trigger_source_nodes=VALUES(trigger_source_nodes),
          threshold_snapshot=VALUES(threshold_snapshot),
          previous_turn_used_for_trigger=VALUES(previous_turn_used_for_trigger)
        """
        params = self._intervention_params(row)
        params["turn_node_log_id"] = turn_node_log_id
        cur.execute(sql, params)

    def _upsert_metric(self, cur: Any, row: Dict[str, Any], turn_node_log_id: int) -> None:
        sql = """
        INSERT INTO metric_logs (
          turn_node_log_id, lms_value, lms_token_count, theta_entropy, lms_delta, cds,
          ma_assert, ma_epist, ma_hedge, sent_count, srr, sci,
          metrics_json, metric_status, quality_gate, generation_quality_ready,
          analysis_eligible, exclude_from_causal_trigger,
          metric_trigger_eligibility, usable_as_quality_outcome,
          metric_pipeline_version
        ) VALUES (
          %(turn_node_log_id)s, %(lms_value)s, %(lms_token_count)s,
          %(theta_entropy)s, %(lms_delta)s, %(cds)s, %(ma_assert)s,
          %(ma_epist)s, %(ma_hedge)s, %(sent_count)s, %(srr)s, %(sci)s,
          %(metrics_json)s, %(metric_status)s, %(quality_gate)s,
          %(generation_quality_ready)s, %(analysis_eligible)s,
          %(exclude_from_causal_trigger)s, %(metric_trigger_eligibility)s,
          %(usable_as_quality_outcome)s, %(metric_pipeline_version)s
        )
        ON DUPLICATE KEY UPDATE
          lms_value=VALUES(lms_value),
          lms_token_count=VALUES(lms_token_count),
          theta_entropy=VALUES(theta_entropy),
          lms_delta=VALUES(lms_delta),
          cds=VALUES(cds),
          ma_assert=VALUES(ma_assert),
          ma_epist=VALUES(ma_epist),
          ma_hedge=VALUES(ma_hedge),
          sent_count=VALUES(sent_count),
          srr=VALUES(srr),
          sci=VALUES(sci),
          metrics_json=VALUES(metrics_json),
          metric_status=VALUES(metric_status),
          quality_gate=VALUES(quality_gate),
          generation_quality_ready=VALUES(generation_quality_ready),
          analysis_eligible=VALUES(analysis_eligible),
          exclude_from_causal_trigger=VALUES(exclude_from_causal_trigger),
          metric_trigger_eligibility=VALUES(metric_trigger_eligibility),
          usable_as_quality_outcome=VALUES(usable_as_quality_outcome)
        """
        params = self._metric_params(row)
        params["turn_node_log_id"] = turn_node_log_id
        cur.execute(sql, params)

    def _upsert_rag_retrieval(self, cur: Any, row: Dict[str, Any], turn_node_log_id: int) -> None:
        sql = """
        INSERT INTO rag_retrieval_logs (
          turn_node_log_id, query_hash, collection_name, top_k, returned_count,
          rag_context_chars, retrieval_method, table_exposure,
          retrieved_chunk_ids, chunk_lengths, block_type_distribution
        ) VALUES (
          %(turn_node_log_id)s, %(query_hash)s, %(collection_name)s, %(top_k)s,
          %(returned_count)s, %(rag_context_chars)s, %(retrieval_method)s,
          %(table_exposure)s, %(retrieved_chunk_ids)s, %(chunk_lengths)s,
          %(block_type_distribution)s
        )
        ON DUPLICATE KEY UPDATE
          query_hash=VALUES(query_hash),
          collection_name=VALUES(collection_name),
          top_k=VALUES(top_k),
          returned_count=VALUES(returned_count),
          rag_context_chars=VALUES(rag_context_chars),
          retrieval_method=VALUES(retrieval_method),
          table_exposure=VALUES(table_exposure),
          retrieved_chunk_ids=VALUES(retrieved_chunk_ids),
          chunk_lengths=VALUES(chunk_lengths),
          block_type_distribution=VALUES(block_type_distribution)
        """
        params = self._rag_retrieval_params(row)
        params["turn_node_log_id"] = turn_node_log_id
        cur.execute(sql, params)

    def _upsert_payload_audit(self, cur: Any, row: Dict[str, Any], turn_node_log_id: int) -> None:
        sql = """
        INSERT INTO payload_audit_logs (
          turn_node_log_id, prompt_hash, payload_hash, message_count,
          prompt_chars, rag_injected, sc_policy_applied
        ) VALUES (
          %(turn_node_log_id)s, %(prompt_hash)s, %(payload_hash)s,
          %(message_count)s, %(prompt_chars)s, %(rag_injected)s,
          %(sc_policy_applied)s
        )
        ON DUPLICATE KEY UPDATE
          prompt_hash=VALUES(prompt_hash),
          payload_hash=VALUES(payload_hash),
          message_count=VALUES(message_count),
          prompt_chars=VALUES(prompt_chars),
          rag_injected=VALUES(rag_injected),
          sc_policy_applied=VALUES(sc_policy_applied)
        """
        params = self._payload_audit_params(row)
        params["turn_node_log_id"] = turn_node_log_id
        cur.execute(sql, params)

    def _experiment_run_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "scenario_id": row["scenario_id"],
            "scenario_hash": row.get("scenario_hash"),
            "condition_name": row.get("condition"),
            "run_mode": row.get("run_mode"),
            "source_file": row.get("source_file"),
            "harness_version": row.get("harness_version"),
            "node_config_hash": row.get("node_config_hash"),
            "sc_policy_id": row.get("run_sc_policy_id") or row.get("sc_policy_id"),
            "policy_hash": row.get("run_policy_hash") or row.get("policy_hash"),
            "theta_source": row.get("theta_source"),
            "theta_locked": _bit(row.get("theta_locked")) or 0,
        }

    def _turn_node_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "turn_no": row["turn_no"],
            "node": row["node"],
            "utterance_hash": row.get("utterance_hash"),
            "response_text": row.get("response_text"),
            "response_hash": row.get("response_hash"),
            "elapsed_ms": row.get("elapsed_ms"),
            "model_name": row.get("model_name"),
            "model_digest": row.get("model_digest"),
            "temperature": row.get("temperature"),
            "seed": row.get("seed"),
            "thinking_disabled_requested": _bit(row.get("thinking_disabled_requested")) or 0,
            "endpoint_mode": row.get("endpoint_mode"),
            "response_text_raw_hash": row.get("response_text_raw_hash"),
            "thinking_tag_present": _bit(row.get("thinking_tag_present")),
            "empty_thinking_shell": _bit(row.get("empty_thinking_shell")),
            "thinking_content_present": _bit(row.get("thinking_content_present")),
            "cleaning_applied": _bit(row.get("cleaning_applied")),
            "cleaning_allowed": _bit(row.get("cleaning_allowed")),
            "failed_TR": _bit(row.get("failed_TR")),
            "removed_prefix_chars": row.get("removed_prefix_chars"),
            "raw_logprobs_len": row.get("raw_logprobs_len"),
            "clean_logprobs_len": row.get("clean_logprobs_len"),
            "excluded_token_positions": _json(row.get("excluded_token_positions", [])),
            "quality_gate": _json(row.get("quality_gate", {})),
            "generation_quality_ready": _bit(row.get("generation_quality_ready")),
            "analysis_eligible": _bit(row.get("analysis_eligible")),
            "exclude_from_causal_trigger": _bit(row.get("exclude_from_causal_trigger")),
            # History eligibility is stored beside analysis/trigger flags so
            # audits can prove that "excluded from analysis" did not
            # automatically mean "removed from future context."
            "history_eligible": _bit(row.get("history_eligible")),
            "history_exclusion_reason": row.get("history_exclusion_reason"),
            "usable_as_quality_outcome": _bit(row.get("usable_as_quality_outcome")),
            "metric_status": _json(row.get("metric_status", {})),
            # Metric-level trigger eligibility captures cases such as missing
            # logprobs disabling LMS triggers while MA/CDS remain policy-usable.
            "metric_trigger_eligibility": _json(row.get("metrics", {}).get("metric_trigger_eligibility", {})),
            "metrics_json": _json(row.get("metrics", {})),
            "raw_response_keys": _json(row.get("raw_response_keys", [])),
        }

    def _intervention_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rag_injected": _bit(row.get("rag_injected")) or 0,
            "sc_policy_applied": _bit(row.get("sc_policy_applied")) or 0,
            "sc_policy_id": row.get("sc_policy_id"),
            "policy_hash": row.get("policy_hash"),
            "trigger_mode": row.get("trigger_mode"),
            "trigger_reasons": _json(row.get("trigger_reasons", [])),
            "trigger_source_nodes": _json(row.get("trigger_source_nodes", [])),
            "threshold_snapshot": _json(row.get("threshold_snapshot", {})),
            "previous_turn_used_for_trigger": row.get("previous_turn_used_for_trigger"),
        }

    def _metric_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        metrics = row.get("metrics", {})
        return {
            "lms_value": metrics.get("lms_value"),
            "lms_token_count": metrics.get("lms_token_count"),
            "theta_entropy": metrics.get("theta_entropy"),
            "lms_delta": metrics.get("lms_delta"),
            "cds": metrics.get("cds"),
            "ma_assert": metrics.get("ma_assert"),
            "ma_epist": metrics.get("ma_epist"),
            "ma_hedge": metrics.get("ma_hedge"),
            "sent_count": metrics.get("sent_count"),
            "srr": metrics.get("srr"),
            "sci": metrics.get("sci"),
            "metrics_json": _json(metrics),
            "metric_status": _json(row.get("metric_status", {})),
            "quality_gate": _json(row.get("quality_gate", {})),
            "generation_quality_ready": _bit(row.get("generation_quality_ready")),
            "analysis_eligible": _bit(row.get("analysis_eligible")),
            "exclude_from_causal_trigger": _bit(row.get("exclude_from_causal_trigger")),
            "metric_trigger_eligibility": _json(metrics.get("metric_trigger_eligibility", {})),
            "usable_as_quality_outcome": _bit(row.get("usable_as_quality_outcome")),
            "metric_pipeline_version": metrics.get("metric_pipeline_version"),
        }

    def _rag_retrieval_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "query_hash": row.get("rag_query_hash") or row.get("utterance_hash"),
            "collection_name": row.get("collection_name"),
            "top_k": row.get("top_k"),
            "returned_count": row.get("returned_count"),
            "rag_context_chars": row.get("rag_context_chars"),
            "retrieval_method": row.get("retrieval_method"),
            "table_exposure": _bit(row.get("table_exposure")),
            "retrieved_chunk_ids": _json(row.get("retrieved_chunk_ids", row.get("rag_chunk_ids", []))),
            "chunk_lengths": _json(row.get("chunk_lengths", [])),
            "block_type_distribution": _json(row.get("block_type_distribution", {})),
        }

    def _payload_audit_params(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "prompt_hash": row.get("prompt_hash"),
            "payload_hash": row.get("payload_hash") or row.get("prompt_hash"),
            "message_count": row.get("message_count"),
            "prompt_chars": row.get("prompt_chars"),
            "rag_injected": _bit(row.get("rag_injected")) or 0,
            "sc_policy_applied": _bit(row.get("sc_policy_applied")) or 0,
        }


class AsyncMariaDBLogger:
    """Queue-backed MariaDB writer.

    JSONL remains synchronous in CompositeLogger. This wrapper moves normalized
    DB writes off the turn barrier and gives callers an explicit flush point for
    end-of-run evidence checks.
    """

    _ROW = "row"
    _FLUSH = "flush"
    _STOP = "stop"

    def __init__(
        self,
        db_logger: MariaDBLogger,
        queue_maxsize: int = 1000,
        flush_timeout_s: float = 30.0,
    ):
        self.db_logger = db_logger
        self.flush_timeout_s = flush_timeout_s
        self._queue: "queue.Queue[Tuple[str, Any, Any]]" = queue.Queue(maxsize=max(1, int(queue_maxsize)))
        self._closed = False
        self._error: Optional[BaseException] = None
        self._error_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, name="lacp-mariadb-logger", daemon=False)
        self._worker.start()

    def log_turn(self, run_id: str, row: Dict[str, Any]) -> None:
        self._raise_if_closed()
        self._queue.put((self._ROW, run_id, dict(row)))

    def flush(self, timeout: Optional[float] = None) -> None:
        self._raise_if_closed()
        done = threading.Event()
        self._queue.put((self._FLUSH, done, None))
        wait_s = self.flush_timeout_s if timeout is None else timeout
        if not done.wait(wait_s):
            raise TimeoutError(f"Timed out waiting for MariaDB logger queue flush after {wait_s:.1f}s")
        self._raise_worker_error()

    def close(self) -> None:
        if self._closed:
            return
        done = threading.Event()
        self._queue.put((self._STOP, done, None))
        wait_s = self.flush_timeout_s
        if not done.wait(wait_s):
            raise TimeoutError(f"Timed out waiting for MariaDB logger shutdown after {wait_s:.1f}s")
        self._worker.join(timeout=1.0)
        self._closed = True
        self._raise_worker_error()

    def _run(self) -> None:
        while True:
            kind, first, second = self._queue.get()
            try:
                if kind == self._ROW:
                    self.db_logger.log_turn(first, second)
                elif kind == self._FLUSH:
                    first.set()
                elif kind == self._STOP:
                    try:
                        self.db_logger.close()
                    finally:
                        first.set()
                    return
            except BaseException as exc:
                self._record_error(exc)
                if kind in {self._FLUSH, self._STOP}:
                    first.set()
            finally:
                self._queue.task_done()

    def _record_error(self, exc: BaseException) -> None:
        with self._error_lock:
            if self._error is None:
                self._error = exc
        print(f"WARNING: async MariaDB logger write failed: {exc}")

    def _raise_worker_error(self) -> None:
        with self._error_lock:
            error = self._error
        if error is not None:
            raise RuntimeError("Async MariaDB logger failed") from error

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError("Async MariaDB logger is closed")


class CompositeLogger:
    def __init__(self, jsonl_logger: JSONLLogger, db_logger: Optional[Any] = None):
        self.jsonl_logger = jsonl_logger
        self.db_logger = db_logger

    def log_turn(self, run_id: str, row: Dict[str, Any]) -> None:
        # JSONL is always written first so a DB outage cannot erase runtime evidence.
        self.jsonl_logger.log_turn(run_id, row)
        if self.db_logger is not None:
            self.db_logger.log_turn(run_id, row)

    def flush(self, timeout: Optional[float] = None) -> None:
        if self.db_logger is not None and hasattr(self.db_logger, "flush"):
            self.db_logger.flush(timeout)

    def close(self) -> None:
        if self.db_logger is not None and hasattr(self.db_logger, "close"):
            self.db_logger.close()


def build_logger(logging_config: Dict[str, Any]) -> CompositeLogger:
    jsonl = JSONLLogger(logging_config["jsonl_fallback_dir"])
    db_cfg = logging_config.get("db", {})
    if not db_cfg.get("enabled", False):
        return CompositeLogger(jsonl)
    try:
        db_logger = MariaDBLogger(db_cfg)
        if db_cfg.get("async_enabled", False):
            db_logger = AsyncMariaDBLogger(
                db_logger,
                queue_maxsize=int(db_cfg.get("async_queue_maxsize", 1000)),
                flush_timeout_s=float(db_cfg.get("async_flush_timeout_s", 30.0)),
            )
    except Exception as exc:
        if db_cfg.get("require_db", False):
            raise
        print(f"WARNING: MariaDB logger disabled; using JSONL fallback only: {exc}")
        db_logger = None
    return CompositeLogger(jsonl, db_logger)
