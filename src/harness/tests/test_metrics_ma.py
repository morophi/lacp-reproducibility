#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from metrics import classify_sentence, compute_ma


def test_assertive_ending():
    assert classify_sentence("이 조건은 해당됩니다.") == "assertive"


def test_epistemic_ending():
    assert classify_sentence("현재 조건상 대상인 것으로 보입니다.") == "epistemic"


def test_hedging_ending_priority_over_assertive():
    assert classify_sentence("추가 확인이 필요합니다.") == "hedging"


def test_compute_ma_counts():
    result = compute_ma("이 조건은 해당됩니다. 현재는 대상인 것으로 보입니다. 추가 확인이 필요합니다.")
    assert result["sent_count"] == 3
    assert result["ma_counts"]["assertive"] == 1
    assert result["ma_counts"]["epistemic"] == 1
    assert result["ma_counts"]["hedging"] == 1
