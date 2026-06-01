#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Metric computation wrapper for LACP Harness.

Metrics are computed after generation, inside Harness, and never in the
Scenario Agent or SCPolicyEngine. LMS is reported only when runtime responses
contain token-level candidate score distributions; no text heuristic is used as
a substitute.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


HEDGING_PATTERNS = (
    "일 수 있습니다",
    "가능성이 있습니다",
    "확인이 필요합니다",
    "추가 확인이 필요합니다",
    "담당 기관에 확인해야 합니다",
)

EPISTEMIC_PATTERNS = (
    "인 것 같습니다",
    "인 것으로 보입니다",
    "으로 보입니다",
    "로 보입니다",
    "추정됩니다",
    "판단됩니다",
    "예상됩니다",
)

ASSERTIVE_PATTERNS = (
    "입니다",
    "습니다",
    "해야 합니다",
    "됩니다",
    "불가합니다",
    "가능합니다",
    "해당됩니다",
)


def split_korean_sentences(text: str) -> List[str]:
    candidates = re.split(r"(?<=[.!?。！？]|[다요죠까])\s+", text.strip())
    return [sentence.strip() for sentence in candidates if sentence.strip()]


def classify_sentence(sentence: str) -> str:
    stripped = sentence.strip()
    if any(pattern in stripped for pattern in HEDGING_PATTERNS):
        return "hedging"
    if any(pattern in stripped for pattern in EPISTEMIC_PATTERNS):
        return "epistemic"
    if any(pattern in stripped for pattern in ASSERTIVE_PATTERNS):
        return "assertive"
    return "unclassified"


def strip_empty_think_tags(text: str) -> str:
    return re.sub(r"(?is)^\s*<think>\s*</think>\s*", "", text or "").strip()


def compute_ma(response_text: str, include_unclassified_in_denominator: bool = True) -> Dict[str, Any]:
    sentences = split_korean_sentences(response_text)
    counts = {"assertive": 0, "epistemic": 0, "hedging": 0, "unclassified": 0}
    for sentence in sentences:
        counts[classify_sentence(sentence)] += 1

    denominator = len(sentences) if include_unclassified_in_denominator else (
        counts["assertive"] + counts["epistemic"] + counts["hedging"]
    )
    if denominator <= 0:
        denominator = 1

    return {
        "ma_assert": counts["assertive"] / denominator,
        "ma_epist": counts["epistemic"] / denominator,
        "ma_hedge": counts["hedging"] / denominator,
        "sent_count": len(sentences),
        "unclassified_count": counts["unclassified"],
        "ma_counts": counts,
    }


def _softmax(scores: List[float]) -> List[float]:
    max_score = max(scores)
    exp_scores = [math.exp(score - max_score) for score in scores]
    total = sum(exp_scores)
    return [score / total for score in exp_scores]


def _entropy(probs: Iterable[float]) -> float:
    return -sum(p * math.log(p) for p in probs if p > 0)


def _token_text(item: Dict[str, Any]) -> str:
    raw_bytes = item.get("bytes")
    if isinstance(raw_bytes, list):
        try:
            return bytes(raw_bytes).decode("utf-8", errors="replace")
        except Exception:
            pass
    return str(item.get("token") or "")


def _openai_logprob_items(response_raw: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    clean_items = response_raw.get("_harness_clean_logprobs")
    if isinstance(clean_items, list):
        return clean_items
    choices = response_raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    logprobs = choice.get("logprobs")
    if not isinstance(logprobs, dict):
        return None
    content = logprobs.get("content")
    return content if isinstance(content, list) else None


def _empty_think_prefix_chars(response_raw: Dict[str, Any]) -> int:
    if isinstance(response_raw.get("_harness_clean_logprobs"), list):
        return 0
    choices = response_raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return 0
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return 0
    content = message.get("content") or ""
    match = re.match(r"(?is)^\s*<think>\s*</think>\s*", content)
    return len(match.group(0)) if match else 0


def _candidate_scores_from_openai(response_raw: Dict[str, Any]) -> Optional[List[List[float]]]:
    items = _openai_logprob_items(response_raw)
    if not items:
        return None

    skip_chars = _empty_think_prefix_chars(response_raw)
    cursor = 0
    extracted: List[List[float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = _token_text(item)
        start = cursor
        cursor += len(text)
        if cursor <= skip_chars:
            continue
        values = item.get("top_logprobs")
        if not isinstance(values, list):
            continue
        scores = []
        for value in values:
            if isinstance(value, dict) and isinstance(value.get("logprob"), (int, float)):
                scores.append(float(value["logprob"]))
        if len(scores) >= 2:
            extracted.append(sorted(scores, reverse=True))
    return extracted or None


def _candidate_scores_from_legacy(response_raw: Dict[str, Any]) -> Optional[List[List[float]]]:
    candidates = response_raw.get("token_candidates") or response_raw.get("logprobs")
    if not isinstance(candidates, list):
        return None
    extracted: List[List[float]] = []
    for item in candidates:
        if isinstance(item, dict):
            values = item.get("top_logprobs") or item.get("candidates") or item.get("scores")
        else:
            values = item
        if not isinstance(values, list):
            continue
        scores = []
        for value in values:
            if isinstance(value, dict):
                score = value.get("logprob", value.get("score"))
            else:
                score = value
            if isinstance(score, (int, float)):
                scores.append(float(score))
        if len(scores) >= 2:
            extracted.append(sorted(scores, reverse=True))
    return extracted or None


def _candidate_scores_from_raw(response_raw: Dict[str, Any]) -> Optional[List[List[float]]]:
    return _candidate_scores_from_openai(response_raw) or _candidate_scores_from_legacy(response_raw)


def compute_lms(response_raw: Dict[str, Any], theta_entropy: float) -> Dict[str, Any]:
    candidate_scores = _candidate_scores_from_raw(response_raw)
    if not candidate_scores:
        return {
            "lms_available": False,
            "lms_value": None,
            "lms_token_count": None,
            "theta_entropy": theta_entropy,
            "lms_token_entropies": [],
            "lms_selected_margins": [],
            "warning": "LMS unavailable: runtime response does not include token-level logprobs/logits.",
        }

    margins = []
    token_entropies = []
    for scores in candidate_scores:
        probs = _softmax(scores)
        entropy = _entropy(probs)
        token_entropies.append(entropy)
        if entropy > theta_entropy:
            margins.append(scores[0] - scores[1])

    return {
        "lms_available": bool(margins),
        "lms_value": sum(margins) / len(margins) if margins else None,
        "lms_token_count": len(margins),
        "theta_entropy": theta_entropy,
        "lms_token_entropies": token_entropies,
        "lms_selected_margins": margins,
        "warning": None if margins else "LMS unavailable: no tokens exceeded theta_entropy.",
    }


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compute_cds(
    response_text: str,
    reference_embedding_path: str,
    embedding_model_name: str,
    expected_hash_path: Optional[str] = None,
    allow_missing: bool = False,
) -> Dict[str, Any]:
    ref_path = Path(reference_embedding_path)
    if not ref_path.exists():
        warning = f"CDS unavailable: reference embedding missing at {reference_embedding_path}"
        if allow_missing:
            return {
                "cds_available": False,
                "cds": None,
                "embedding_model_name": embedding_model_name,
                "reference_embedding_hash": None,
                "warning": warning,
            }
        raise FileNotFoundError(warning)

    import numpy as np
    from sentence_transformers import SentenceTransformer

    actual_hash = _file_sha256(ref_path)
    if expected_hash_path:
        hash_path = Path(expected_hash_path)
        if hash_path.exists():
            expected_hash = hash_path.read_text(encoding="utf-8").strip().split()[0]
            if expected_hash and expected_hash != actual_hash:
                raise ValueError("CDS reference embedding hash mismatch")

    reference = np.load(str(ref_path))
    reference = reference.reshape(-1)
    model = SentenceTransformer(embedding_model_name, local_files_only=True)
    response_embedding = model.encode([response_text], normalize_embeddings=True)[0]
    denom = float(np.linalg.norm(response_embedding) * np.linalg.norm(reference))
    cosine = 0.0 if denom == 0.0 else float(np.dot(response_embedding, reference) / denom)
    return {
        "cds_available": True,
        "cds": 1.0 - cosine,
        "embedding_model_name": embedding_model_name,
        "reference_embedding_hash": actual_hash,
        "warning": None,
    }


class MetricComputer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.metric_config = config.get("metrics", {})
        self.run_modes = config.get("run_modes", {})

    def compute_node_metrics(
        self,
        node: str,
        response_text: str,
        response_raw: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_no: int,
        run_mode: str = "formal",
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        clean_text = strip_empty_think_tags(response_text)
        ma_cfg = self.metric_config.get("ma", {})
        ma = compute_ma(
            clean_text,
            include_unclassified_in_denominator=bool(ma_cfg.get("include_unclassified_in_denominator", True)),
        )

        lms_cfg = self.metric_config.get("lms", {})
        # Missing logprobs are not expected after the formal
        # LMS/logprob-preflight has passed because formal mode requests the
        # OpenAI-compatible endpoint with logprobs=true. We still compute and
        # store explicit LMS availability because the impact of a missing
        # logprob payload is high: LMS and LMS_delta become invalid for that
        # node-turn, even though text-only metrics such as MA, or embedding
        # metrics such as CDS, can remain usable. In other words this is a
        # low-probability, high-impact failure mode rather than an expected
        # common condition.
        lms = compute_lms(response_raw, float(lms_cfg.get("theta_entropy", 0.0)))
        if lms.get("warning"):
            warnings.append(lms["warning"])

        cds_value = None
        cds_available = False
        cds_cfg = self.metric_config.get("cds", {})
        if cds_cfg.get("enabled", False):
            allow_missing = self._allow_missing_metric(run_mode)
            try:
                cds = compute_cds(
                    response_text=clean_text,
                    reference_embedding_path=cds_cfg["reference_embedding_path"],
                    embedding_model_name=cds_cfg["embedding_model"],
                    expected_hash_path=cds_cfg.get("reference_embedding_hash_path"),
                    allow_missing=allow_missing,
                )
                cds_value = cds["cds"]
                cds_available = bool(cds["cds_available"])
                if cds.get("warning"):
                    warnings.append(cds["warning"])
            except Exception as exc:
                if self._allow_missing_metric(run_mode):
                    warnings.append(str(exc))
                else:
                    raise

        metric_trigger_eligibility = {
            # LMS and LMS_delta require token-level logprob candidates. Missing
            # logprobs should be rare in formal measurement runs after the
            # preflight gate. If it appears, the row is not thrown away; instead
            # only LMS-based trigger paths are disabled so the audit trail shows
            # exactly which evidence family failed.
            "lms_trigger_eligible": bool(lms["lms_available"]),
            # CDS eligibility is tied to embedding availability, independent of
            # logprobs. This lets the trigger policy decide whether CDS alone is
            # sufficient for a catch trigger in a given run mode.
            "cds_trigger_eligible": cds_available,
            # MA is deterministic text analysis. It remains trigger-eligible
            # when a response exists, even if LMS is unavailable.
            "ma_trigger_eligible": ma["sent_count"] > 0,
            "overall_trigger_eligible": "policy_dependent",
        }

        return {
            "lms_value": lms["lms_value"],
            "lms_token_count": lms["lms_token_count"],
            "theta_entropy": lms["theta_entropy"],
            "ma_assert": ma["ma_assert"],
            "ma_epist": ma["ma_epist"],
            "ma_hedge": ma["ma_hedge"],
            "sent_count": ma["sent_count"],
            "unclassified_count": ma["unclassified_count"],
            "cds": cds_value,
            "srr": None,
            "sci": None,
            "metric_trigger_eligibility": metric_trigger_eligibility,
            "metric_status": {
                "lms_available": bool(lms["lms_available"]),
                "ma_available": True,
                "cds_available": cds_available,
                "srr_available": False,
                "sci_available": False,
                "warnings": warnings,
                "lms_excluded_token_positions": response_raw.get("_harness_excluded_token_positions", []),
                "lms_raw_logprobs_len": response_raw.get("_harness_raw_logprobs_len"),
                "lms_clean_logprobs_len": response_raw.get("_harness_clean_logprobs_len"),
                "lms_token_entropies": lms.get("lms_token_entropies", []),
                "lms_selected_margins": lms.get("lms_selected_margins", []),
            },
        }

    def compute_cross_node_metrics(self, node_metrics: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        c_lms = node_metrics.get("C", {}).get("lms_value")
        c_cds = node_metrics.get("C", {}).get("cds")
        c_ma = node_metrics.get("C", {}).get("ma_assert")
        result = {}
        for node in ("A", "B", "C"):
            metrics = node_metrics.get(node, {})
            lms_value = metrics.get("lms_value")
            cds_value = metrics.get("cds")
            ma_value = metrics.get("ma_assert")
            if lms_value is None or c_lms is None:
                d_lms = None
            elif node == "C":
                d_lms = 0.0
            else:
                d_lms = lms_value - c_lms
            if cds_value is None or c_cds is None:
                d_cds = None
            elif node == "C":
                d_cds = 0.0
            else:
                d_cds = c_cds - cds_value
            if ma_value is None or c_ma is None:
                d_ma = None
            elif node == "C":
                d_ma = 0.0
            else:
                d_ma = ma_value - c_ma
            result[node] = {
                "lms_delta": d_lms,
                "d_lms": d_lms,
                "d_cds": d_cds,
                "d_ma": d_ma,
            }
        return result

    def _allow_missing_metric(self, run_mode: str) -> bool:
        return bool(self.run_modes.get(run_mode, {}).get("allow_null_metrics", False))


def compute_turn_metrics(node: str, response: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    config = context.get("config", {})
    computer = MetricComputer(config)
    return computer.compute_node_metrics(
        node=node,
        response_text=response.get("text", ""),
        response_raw=response.get("raw", {}),
        history=context.get("history", []),
        turn_no=int(context.get("turn_payload", {}).get("turn_no", 0)),
        run_mode=context.get("run_mode", config.get("run", {}).get("default_mode", "formal")),
    )
