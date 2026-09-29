#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from metrics import compute_sci, compute_srr


def test_srr_first_turn_is_zero_and_available():
    result = compute_srr(
        response_text="Submit the application at the local office.",
        history=[],
        embedding_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    assert result["srr_available"] is True
    assert result["srr"] == 0.0
    assert result["srr_history_sentence_count"] == 0


def test_sci_replacement_is_available_without_cr2_baseline():
    result = compute_sci(
        "The rule applies. Evidence is required because eligibility depends on income. Therefore submit documents."
    )
    assert result["sci_available"] is True
    assert result["sci"] is not None
    assert result["sci_method"] == "replacement_sentence_type_proportion"
