# LACP E2E Smoke Evidence: top-k=3

작성일: 2026-05-27  
공유 목적: 2026-05-30 교수님 논의용  
Run ID: `e2e_rough_topk3_20260527T1043Z`  
Run mode: `smoke`  
Scenario: `/home/morophi/agent/scenario/lacp_scenario_base_v2.json`  
Scenario ID: `lacp_scenario_base_v2`  
Scenario hash: `025884c27aa9bdf041359862433b9d888a8e20c3e2bf61a2d4af3fcda6478979`

## 1. 요약 판단

이번 smoke run은 LACP의 핵심 E2E 경로가 실제로 동작함을 확인한 evidence이다.

검증된 경로는 다음과 같다.

```text
Scenario Agent
-> Harness /turn
-> RAG retrieval
-> Node A / Node B / Node C parallel inference
-> LMS / MA / CDS metric computation
-> JSONL evidence
-> MariaDB dblog persistence
```

핵심 결과:

| 항목                   |   결과 |
| ---------------------- | -----: |
| 요청 turn 수           |      3 |
| 완료 turn 수           |      3 |
| 노드 수                |  A/B/C |
| 기대 node-turn rows    |      9 |
| JSONL rows             |      9 |
| Agent ack              |  3 / 3 |
| Empty response rows    |  0 / 9 |
| Runtime error rows     |  0 / 9 |
| Thinking content rows  |  0 / 9 |
| Metric-complete rows   |  9 / 9 |
| Validator status       | `pass` |
| DB `turn_node_logs`    |      9 |
| DB `intervention_logs` |      9 |
| DB `metric_logs`       |      9 |

해석:

이 run은 본 실험 결과 자체는 아니며, formal run 전 operational readiness evidence이다. 그러나 이전 blocked 상태와 달리 LMS, MA, CDS가 모두 채워진 metric-complete E2E smoke pass라는 점에서 의미가 있다.

## 2. 실험 설정

| 항목                | 값                                                                 |
| ------------------- | ------------------------------------------------------------------ |
| RAG collection      | `lacp_docs_v1_full_guideline_table_safe_body_only_v1`              |
| smoke RAG `top_k`   | 3                                                                  |
| smoke `num_predict` | 256                                                                |
| endpoint            | `openai_chat_completions`                                          |
| logprobs            | enabled                                                            |
| top logprobs        | 5                                                                  |
| thinking            | disabled                                                           |
| model               | `qwen3-nothink`                                                    |
| temperature         | 0.0                                                                |
| seed                | 42                                                                 |
| node config hash    | `5dd26034d6008b20e9403f3eafd2c9172fbd97d9894f5338d1751fa845f8772a` |

주의:

`theta_locked=false` 상태의 smoke run이다. 따라서 이 run은 CR/CF causal inference가 아니라, TR 이전 경로 검증 및 formal parameter decision을 위한 operational evidence로 해석해야 한다.

## 3. A/B/C Routing Invariants

| Invariant                     |  결과 |
| ----------------------------- | ----: |
| Node A RAG injected           | 3 / 3 |
| Node B RAG injected           | 3 / 3 |
| Node C RAG injected           | 0 / 3 |
| Node A SC policy applied      | 3 / 3 |
| Node B SC policy applied      | 0 / 3 |
| Node C SC policy applied      | 0 / 3 |
| RAG rows missing chunk ids    |     0 |
| Sidecar prompt injection rows |     0 |

해석:

Node A는 `RAG + SC-Protocol`, Node B는 `RAG only`, Node C는 `baseline`으로 분기되었다. 즉, 세 노드 비교 구조의 routing invariant가 유지되었다.

## 4. Metric Completeness

| Metric               | Count |
| -------------------- | ----: |
| LMS available        | 9 / 9 |
| MA available         | 9 / 9 |
| CDS available        | 9 / 9 |
| Metric-complete rows | 9 / 9 |

이전 blocked 원인과의 차이:

| 이전 문제                                       | 현재 조치                                                        |
| ----------------------------------------------- | ---------------------------------------------------------------- |
| native Ollama endpoint에서 LMS logprobs 부재    | OpenAI-compatible `/v1/chat/completions` 사용                    |
| CDS reference embedding 누락                    | frozen Chroma stored embeddings 평균으로 reference artifact 생성 |
| empty `<think>` shell이 metric 입력에 섞일 위험 | empty shell strip 및 해당 token positions LMS 제외               |

CDS reference artifact는 Harness가 생성하지 않고, RAG/corpus freeze 단계의 산출물로 생성한 뒤 Harness에 read-only로 배치했다.

## 5. Per-Turn Evidence

| Turn | Node | Prompt chars | Response chars | Elapsed ms |    CDS |    LMS | MA assert |
| ---: | ---- | -----------: | -------------: | ---------: | -----: | -----: | --------: |
|    1 | A    |        4,766 |            133 |   20,271.6 | 0.4562 | 5.9527 |    0.7500 |
|    1 | B    |        4,319 |            157 |   21,494.1 | 0.4238 | 6.0682 |    0.6000 |
|    1 | C    |          217 |            185 |   12,201.8 | 0.4950 | 5.9515 |    0.6000 |
|    2 | A    |        4,433 |            335 |   26,090.3 | 0.3734 | 5.2982 |    0.8333 |
|    2 | B    |        4,010 |            396 |   28,013.8 | 0.5211 | 5.7034 |    0.4444 |
|    2 | C    |          456 |            360 |   17,417.1 | 0.4356 | 5.2770 |    0.6667 |
|    3 | A    |        3,303 |            379 |   23,985.2 | 0.4329 | 6.0046 |    0.8571 |
|    3 | B    |        2,941 |            394 |   25,108.3 | 0.3056 | 5.3490 |    0.5000 |
|    3 | C    |          854 |            375 |   17,979.7 | 0.5305 | 5.7888 |    0.7500 |

## 6. Node-Level Summary

| Node | Condition | top_k | Prompt avg | Prompt max | RAG context avg | Latency avg ms | Latency max ms | CDS avg | LMS avg |
| ---- | --------- | ----: | ---------: | ---------: | --------------: | -------------: | -------------: | ------: | ------: |
| A    | RAG + SC  |     3 |    4,167.3 |      4,766 |         2,841.7 |       23,449.0 |       26,090.3 |  0.4208 |  5.7518 |
| B    | RAG only  |     3 |    3,756.7 |      4,319 |         2,841.7 |       24,872.1 |       28,013.8 |  0.4168 |  5.7069 |
| C    | Baseline  |   N/A |      509.0 |        854 |               0 |       15,866.2 |       17,979.7 |  0.4870 |  5.6724 |

관찰:

- Node A/B는 같은 RAG context를 사용했고, Node A에만 SC policy가 추가되었다.
- Node C는 RAG가 주입되지 않았고 prompt size도 명확히 작다.
- top-k=3에서도 A/B prompt는 4k chars 수준까지 올라가므로, formal top-k=5는 안전하다고 보기 어렵다.

## 7. top-k=2 vs top-k=3 비교

이전 pass run:

- `top_k=2`: `e2e_rough_20260527T1032Z`
- `top_k=3`: `e2e_rough_topk3_20260527T1043Z`

| 항목                 |  top-k=2 |  top-k=3 |
| -------------------- | -------: | -------: |
| A prompt avg         |  3,083.3 |  4,167.3 |
| A prompt max         |    3,436 |    4,766 |
| B prompt avg         |  2,614.0 |  3,756.7 |
| B prompt max         |    2,989 |    4,319 |
| A latency avg ms     | 20,822.2 | 23,449.0 |
| B latency avg ms     | 20,027.7 | 24,872.1 |
| Metric-complete rows |    9 / 9 |    9 / 9 |
| Empty response rows  |    0 / 9 |    0 / 9 |
| Runtime error rows   |    0 / 9 |    0 / 9 |
| Validator status     |   `pass` |   `pass` |

판단:

`top_k=3`은 `top_k=2`보다 prompt size와 latency 부담이 증가하지만, 3-turn smoke에서는 metric completeness와 DB persistence를 모두 유지했다. 따라서 `top_k=3`은 `top_k=5`와 `top_k=2` 사이에서 현재 가장 현실적인 formal candidate로 볼 수 있다.

## 8. Thermal Evidence

| Run           | inference1 max | inference2 max | inference3 max |  RAG max |
| ------------- | -------------: | -------------: | -------------: | -------: |
| top-k=2 smoke |         79.0 C |         73.0 C |         71.0 C | 43.851 C |
| top-k=3 smoke |         80.0 C |         74.0 C |         74.0 C | 44.432 C |

후속 cooldown 확인:

| Node       | Current max after cooldown |
| ---------- | -------------------------: |
| inference1 |                    47.75 C |
| inference2 |                    48.50 C |
| inference3 |                   47.125 C |

해석:

top-k=3은 짧은 3-turn smoke에서 온도 spike를 만들지만, cooldown 이후 47-49 C 수준으로 회복된다. 따라서 thermal logging과 cooldown은 formal protocol의 고정 운영 통제로 유지해야 한다.

## 9. Resolved Blockers

| Blocker                      | Evidence                                     | Resolution                                        |
| ---------------------------- | -------------------------------------------- | ------------------------------------------------- |
| LMS unavailable              | native endpoint lacked token logprobs        | `/v1/chat/completions` with logprobs              |
| CDS unavailable              | missing `reference_embedding.npy`            | frozen Chroma stored embeddings mean reference    |
| Node B intermittent 500      | `signal arrived during cgo execution`        | clean runner, unload, avoid heavy synthetic probe |
| Synthetic probe mismatch     | synthetic probe missed actual RAG+SC payload | actual first-turn dry-run gate                    |
| Synthetic probe perturbation | long probe sometimes preceded Node B failure | synthetic long probe optional only                |
| top-k=5 instability risk     | oversized payload / earlier failures         | top-k=3 selected as current candidate             |

## 10. Limitations

This smoke run does not yet prove causal claims. It proves operational readiness under a specific constrained setting.

Remaining limitations:

- Only 3 turns were executed.
- `theta_locked=false`, so this is not formal Run B evidence.
- `top_k=3` passed short smoke, but longer TR-like validation is still needed.
- `num_predict=256` is a smoke budget, not necessarily final formal budget.
- Formal `top_k=5` remains unproven and currently high-risk.

## 11. Recommended Next Step Before CR

Recommended immediate next step:

```text
Run a 5-turn TR-like smoke with:
- top_k=3
- thermal logging
- cooldown window
- actual-first-turn readiness gate
- no synthetic long probe
- metric-complete validator
- DB row check
```

Acceptance criteria:

| Criterion                        | Required |
| -------------------------------- | -------: |
| A/B/C completion                 |  15 / 15 |
| Empty response rows              |        0 |
| Runtime error rows               |        0 |
| LMS available                    |  15 / 15 |
| MA available                     |  15 / 15 |
| CDS available                    |  15 / 15 |
| DB turn/intervention/metric rows |  15 each |
| Node C RAG contamination         |        0 |
| RAG rows missing chunk ids       |        0 |

## 12. Professor Discussion Framing

This evidence is best framed as follows:

> The E2E smoke process did not merely confirm that the system can run. It identified and controlled the operational envelope required for the LACP experiment: endpoint capability for LMS, fixed CDS reference artifacts, RAG context size, inference-node stability, thermal behavior, and database persistence. The final top-k=3 smoke pass demonstrates that the experimental pipeline can produce complete observable metrics across the three-node comparison architecture.

The important point for discussion is that `top_k` is not a cosmetic runtime parameter. It directly affects prompt size, node stability, latency, and therefore the feasibility of collecting valid CDS/LMS/MA evidence. Current evidence supports `top_k=3` as the practical candidate for the next TR validation, while `top_k=5` should remain blocked until it passes the same evidence standard.
