# LACP 실험 가이드라인 rev6.1

> **문서 정보**
>
> - 버전: rev6.1
> - 작성일: 2026-05-27
> - 프로젝트: LACP (Local AI Consultation Protocol)
> - 실험 목적: RAG의 인과적 개입 메커니즘 검증
> - 논문 버전 기준: lacp_ijibc_rev9 / lacp_ijibc_rev9_kor_merge
> - 체크리스트 기준: lacp_node_checklist_v10.5
> - 기반 문서: lacp_experiment_guideline_rev1 → rev2 → rev3 → rev4 → rev5 → rev5.1 → rev5.2 → rev5.3 → rev5.4 → rev5.5 → rev5.6 → rev6 → rev6.1

---

## 문서 이력

| 버전   | 일자       | 변경 내용                                                                                                                                                                                                                                                                             |
| ------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| rev1   | 2026-05-18 | 최초 작성 — 실험 흐름·착수 조건·STEP 1~6·CF 조건·운용 원칙 통합                                                                                                                                                                                                                       |
| rev2   | 2026-05-18 | causal verification 방어선 강화 / Time Sync / Failure Handling / Metric Hierarchy / Seed Governance 명문화                                                                                                                                                                            |
| rev3   | 2026-05-18 | CDS 운용 정책 신설 / CF Runs N=5 each 명시 / Primary Test 통계 방법 명시 / SRR Secondary 근거 명시                                                                                                                                                                                    |
| rev4   | 2026-05-18 | MA Operational Definition 신설 — MA_assert(t) 수식 / θ_MA 산정 기준 / 측정 단위 / 분류 규칙 완전 명문화                                                                                                                                                                               |
| rev5   | 2026-05-20 | Pure RAG Ingest Validation / Retrieval Coherence Validation 계층 추가 — corpus semantic validity를 causal inference 이전 prerequisite로 승격                                                                                                                                          |
| rev5.1 | 2026-05-23 | Top-k selection / thinking-output contamination control / failed run archival policy 추가 — pre-CR operational validity 조건 보강                                                                                                                                                     |
| rev5.2 | 2026-05-23 | Context-window saturation / table-safe small chunking / trigger contamination control 추가 — RAG substrate validity 조건 보강                                                                                                                                                         |
| rev5.3 | 2026-05-23 | Hybrid table fallback / Harness smoke pass condition / response parser / think=false API control / done_reason truncation policy 추가 — pre-CR execution readiness 조건 보강                                                                                                          |
| rev5.4 | 2026-05-26 | Full-guideline retrieval 재검증 / body-only embedding policy / lexical-weighted hybrid RRF / source-aware table diagnostic / evidence sidecar diagnostic-only / manual retrieval freeze gate 추가 — formal CR 진입 전 retrieval substrate freeze 조건 보강                            |
| rev5.5 | 2026-05-26 | Rev8 thermal safeguard / turn-level synchronization barrier / five-turn cooldown / thermal snapshot logging 추가 — thermal drift를 operational confounder로 통제                                                                                                                      |
| rev5.6 | 2026-05-26 | 60-second cooldown validation run 근거 추가 — measured nonlinear post-load cooling behavior를 thermal safeguard empirical basis로 반영                                                                                                                                                |
| rev6   | 2026-05-26 | Formal logprobs extraction and LMS availability gate 신설 — OpenAI-compatible `/v1/chat/completions` 기반 token-level logprobs 추출, LMS 계산 조건, missing logprobs 처리 정책, 구현 파일 위치를 메이저 업데이트로 통합                                                               |
| rev6.1 | 2026-05-27 | E2E issue sampling 결과 병합 — DB-free inference readiness gate, actual first-turn dry-run, stale runner contamination control, runner unload/settle, top-k=3 formal candidate, smoke/formal num_predict 분리, CDS reference artifact freeze 및 embedding-space consistency gate 추가 |

---

# 개요

## 핵심 실험 질문

> "RAG는 단순한 정보 보강 도구인가, 아니면 LLM의 판단 방향을 재구성하는 인과적 개입 메커니즘인가?"

---

# 전체 실험 흐름

```text
드라이런
  ↓
STEP 0: Pure RAG Ingest Validation
  ↓
STEP 0.1: RAG Corpus Versioning and Rebuild Policy
  ↓
STEP 0.2: Table-safe Chunking Protocol
  ↓
STEP 0.3: Context Window Load Test
  ↓
STEP 0.4: Trigger Sensitivity Check
  ↓
STEP 0.5: Retrieval Coherence Validation
  ↓
STEP 0.6: Top-k Selection Protocol
  ↓
STEP 0.7: Thinking Output Contamination Control
  ↓
STEP 0.8: Hybrid Table Exposure Validation
  ↓
STEP 0.9: Harness Smoke Test and Generation Quality Gate
  ↓
STEP 0.10: Formal Logprobs Extraction and LMS Availability Gate
  ↓
STEP 0.11: Formal Retrieval Candidate Freeze Gate
  ↓
STEP 0.12: Pre-Formal E2E Readiness and Artifact Integrity Gate
  ↓
STEP 1: CR (Calibration Run)
  ↓
STEP 2: CR2 (Calibration Run 2)
  ↓
STEP 3: SCI 사전 타당성 검사
  ↓
STEP 4: Run B (본 실험 파일럿)
  ↓
         Power analysis → 주실험 N 확정
  ↓
STEP 5: CF Runs (CF-A ~ CF-F)
  ↓
STEP 6: 결과 내보내기 → 논문 Results 작성
```

---

# 설계 원칙

본 문서는 단순 실행 절차가 아니라 다음 항목을 명시적으로 방어 대상으로 간주한다.

1. 시간 동기화 (Time Synchronization)
2. Seed 조작 가능성 제거
3. 실패 처리 및 exclusion 기준 명문화
4. Threshold 사후 조정 방지
5. Metric hierarchy 명시
6. 실험 재현성 (reproducibility) 고정
7. Retrieval validity prior to causal inference
8. Thinking-output contamination control
9. Top-k payload stability validation
10. Failed run archival policy
11. Context-window saturation control
12. Table-safe chunking governance
13. RAG substrate versioning
14. Trigger assignment contamination control
15. Hybrid retrieval exposure logging
16. Harness path / generation quality separation
17. Generation truncation governance
18. DB-free inference readiness gate
19. Harness `/turn` non-use policy during preflight
20. Actual first-turn dry-run readiness validation
21. Stale runner / runtime occupation contamination control
22. Runner unload and settle policy
23. Smoke/formal generation-budget separation
24. Formal top-k payload envelope governance
25. CDS reference artifact freeze governance
26. CDS embedding-space consistency between reference and response vectors
27. E2E blocker classification prior to causal data generation

---

# Retrieval Validity 원칙

RAG intervention effect를 causal signal로 해석하기 위해서는,
retrieval corpus의 semantic coherence가 먼저 검증되어야 한다.

즉:

```text
문서 현실
→ canonicalization
→ semantic preservation
→ retrieval coherence
→ intervention
→ measurement
```

구조가 성립되어야 하며,
corpus preprocessing artifact가 실험 결과에 개입하지 않아야 한다.

본 실험에서 retrieval coherence validation은 단순 QA 품질 검사가 아니라:

```text
causal interpretation prerequisite
```

로 간주한다.

---

# RAG Substrate Validity 원칙

RAG intervention을 causal signal로 해석하기 위해서는 retrieval 결과가 단순히 반환되는 것만으로 부족하다. 검색된 payload가 모델 context window 안에 온전히 주입 가능해야 하며, 표와 조건문 같은 정책 의미 구조가 chunking 과정에서 훼손되지 않아야 한다.

따라서 다음 조건을 causal inference 이전 prerequisite로 간주한다.

```text
Corpus Validity
→ RAG Substrate Validity
→ Retrieval Validity
→ Calibration
→ Causal Inference
```

large chunk 기준 top-k=3에서 context-window saturation, prompt truncation, A/B concurrent timeout이 발생하는 경우 해당 조건은 단순 model execution failure가 아니라 retrieval substrate failure로 분류한다. 이 경우 기존 collection은 보존하고, 새 versioned collection으로 table-safe small chunk corpus를 재구축해야 한다.

---

# STEP 0 — Pure RAG Ingest Validation

## 목적

원본 복지행정 지침이 canonical.md 변환 이후에도
정책 의미 구조를 유지하는지 확인한다.

---

## 검증 대상

```text
□ PDF/HWPX → canonical.md 변환 품질
□ section hierarchy 보존
□ table flattening 의미 보존
□ eligibility marker tagging
□ exception marker tagging
□ conditional marker tagging
□ metadata integrity
□ chunk boundary coherence
□ exception scope leakage 여부
```

---

## 실패 시 처리

다음 조건 발생 시 CR 진입 금지:

```text
□ 대상 조건과 제외 조건이 동일 chunk에 혼합
□ 표 flattening 후 정책 의미 상실
□ conditional scope 붕괴
□ marker tagging 실패
□ metadata 누락
□ source page 추적 불가
```

---

# STEP 0.1 — RAG Corpus Versioning and Rebuild Policy

## 목적

chunking policy 변경이 CDS reference embedding과 trigger baseline을 오염시키지 않도록, corpus version과 collection name을 명시적으로 분리한다.

## 원칙

```text
□ 기존 collection overwrite 금지
□ 기존 large-chunk collection 보존
□ 새 collection name 생성 (예: lacp_docs_v2_table_safe)
□ corpus_version 명시
□ source hash / chunk hash / embedding hash 재생성
□ CDS reference embedding 재생성 전 corpus version 고정
□ collection_name / corpus_version / chunking_mode run_id에 포함
```

## 실패 시 처리

```text
□ 기존 collection 덮어쓰기 발생 시 해당 ingest invalid 처리
□ corpus hash 누락 시 CR 진입 금지
□ collection version 불명확 시 failed_retrieval 처리
```

---

# STEP 0.2 — Table-safe Chunking Protocol

## 목적

small chunking이 표의 의미 구조를 훼손하지 않도록, 표를 독립 해석 가능한 retrieval unit으로 재구성한다.

## 기본 정책

```text
CHUNK_SIZE_TARGET = 800~1000 chars
CHUNK_OVERLAP = 100~150 chars
MIN_CHUNK_SIZE = 250 chars
MAX_TABLE_PART_CHARS = 1100 chars
```

## 표 처리 원칙

긴 표는 단순 문자 수 기준으로 자르지 않는다. row-wise segmentation을 적용하되, 각 part마다 동일 표 식별자와 반복 header를 포함한다.

```text
[TABLE_START]
table_id: tbl_001_income_standard_2026
parent_table_label: 표 1
table_part_label: 표 1-1
table_part: 1/3
source: 2026_기초생활보장_운영지침.pdf
section: 생계급여 선정기준
table_title: 2026년 기준 중위소득 및 급여별 선정기준
columns: 가구원수 | 기준중위소득 | 생계급여 | 의료급여 | 주거급여 | 교육급여
unit: 원
year: 2026

가구원수 | 기준중위소득 | 생계급여 | 의료급여 | 주거급여 | 교육급여
1인가구 | ... | ... | ... | ... | ...
2인가구 | ... | ... | ... | ... | ...
3인가구 | ... | ... | ... | ... | ...
[TABLE_END]
```

## 필수 metadata

```text
□ chunk_id
□ corpus_version
□ source_file
□ source_hash
□ page 또는 page_range
□ section
□ block_type: text | table | mixed
□ chunk_index
□ chunk_chars
□ chunk_sha256
□ table_id (table block)
□ parent_table_label (table block)
□ table_part_label (table block)
□ table_part_no / table_part_total (table block)
□ table_title / columns / unit / year (table block)
```

## Go / No-Go

```text
□ table_id 없는 table chunk 없음
□ repeated header 없는 table part 없음
□ source/page/section metadata 없는 chunk 없음
□ table part 단독 해석 가능성 확인
□ table flattening semantic collapse 없음
```

---

# STEP 0.3 — Context Window Load Test

## 목적

retrieval payload 증가가 context-window saturation 또는 model execution failure로 이어져 causal signal로 오인되는 것을 방지한다.

## 검증 항목

```text
□ top-k별 final_prompt_chars 기록
□ top-k별 rag_context_chars 기록
□ top-k별 prompt_eval_count 기록
□ top-k별 prompt_eval_duration_ms 기록
□ top-k별 eval_count / eval_duration_ms 기록
□ Ollama truncation log 확인
□ A/B concurrent generation 통과 여부 확인
□ timeout / 500 error 발생 여부 확인
```

## 탈락 조건

```text
□ "truncating input prompt limit=4096" 발생
□ prompt_eval_count >= num_ctx
□ A/B concurrent generation 180초 timeout
□ 500 error 발생
□ nonempty response 불충족
```

---

# STEP 0.4 — Trigger Sensitivity Check

## 목적

chunking policy 변경이 trigger activation pattern을 바꾸어 RAG intervention assignment를 오염시키는지 확인한다.

## 검증 방식

동일 representative query set 또는 TR subset에 대해 large-chunk corpus와 small table-safe corpus의 다음 항목을 비교한다.

```text
□ retrieved_chunk_ids
□ block_type 분포
□ table_id 포함 여부
□ rag_context_chars
□ prompt_eval_count
□ LMS / CDS / MA_assert 변화
□ trigger activation 여부
□ trigger 과발동 / 저발동 사례
```

## 해석 원칙

chunking policy 변경으로 인해 trigger pattern이 크게 변하면, 해당 변화는 RAG causal effect가 아니라 chunking policy effect 또는 treatment assignment contamination 후보로 분류한다.

```text
□ trigger assignment contamination 의심 사례 기록
□ unresolved contamination 존재 시 CR 진입 금지
□ 해결 전 Run B / CF Runs 수행 금지
```

---

# STEP 0.5 — Retrieval Coherence Validation

## 목적

Embedding 이후 retrieval 결과가
원문 정책 의미를 유지하는지 검증한다.

---

## 검증 항목

```text
□ 대표 query set 생성 완료
□ eligibility query top-k coherence 확인
□ exception query top-k coherence 확인
□ conditional query top-k coherence 확인
□ retrieval stability 확인
□ 동일 query 반복 시 ranking consistency 유지
□ retrieval noise 사례 기록
□ failed retrieval case 저장
```

---

## 산출물

```text
canonical_sample_review.md
chunk_manifest.jsonl
embedding_manifest.json
retrieval_test_queries.json
retrieval_coherence_report.md
failed_cases.md
corpus_hash.txt
embedding_hash.txt
```

---

# STEP 0.6 — Top-k Selection Protocol

## 목적

RAG retrieval payload가 응답 안정성에 미치는 영향을 사전에 검증하여,
retrieval load 또는 timeout artifact가 causal signal로 오인되지 않도록 한다.

---

## 후보군

```text
k = 1
k = 3
k = 5
```

---

## 평가 항목

```text
□ retrieval coherence
□ response completeness
□ timeout rate
□ node-wise elapsed_ms distribution
□ Node C baseline independence
□ failed retrieval case 기록
□ final_prompt_chars
□ rag_context_chars
□ prompt_eval_count
□ prompt_eval_duration_ms
□ eval_count / eval_duration_ms
□ Ollama truncation log 발생 여부
□ collection_name / corpus_version
```

---

## 선택 기준

```text
□ 모든 노드 nonempty response
□ timeout-induced empty output 없음
□ retrieval coherence validation 통과
□ exception / eligibility query retrieval 실패 없음
□ elapsed_ms node별 분포 기록 완료
```

---

## 탈락 조건

```text
□ 특정 노드 반복 무응답
□ elapsed_ms hard timeout 근접
□ exception chunk retrieval failure
□ eligibility chunk retrieval failure
□ retrieval payload 증가로 인한 response incompleteness
□ context-window saturation
□ prompt truncation 발생
□ A/B concurrent generation timeout
□ table-safe chunking validation 미통과
□ trigger sensitivity validation 미통과
```

---

# STEP 0.7 — Thinking Output Contamination Control

## 목적

Qwen 계열 reasoning/thinking 출력이 LMS·MA·CDS·SRR·SCI 측정값을 오염시키지 않도록,
생성 단계에서 thinking output을 비활성화하고 로그 수준에서 이를 검증한다.

---

## 검증 항목

```text
□ model invocation에 think=false 명시
□ thinking_disabled_requested=true 확인
□ response_text 내 <think> / reasoning trace 0건 확인
□ thinking_present_rows=0 확인
□ thinking_control_effective=true 확인
```

---

## 실패 시 처리

```text
□ thinking trace 발견 시 해당 run failed_TR 처리
□ thinking trace를 사후 제거한 데이터는 재사용 금지
□ failed run은 infrastructure diagnosis 용도로만 보관
□ CR / CR2 / Run B / CF Runs 진입 금지
```

---

# STEP 0.8 — Hybrid Table Exposure Validation

## 목적

vector-only retrieval이 table-sensitive query에서 실제 table chunk를 top-k 안에 올리지 못하는 경우, 표 기반 정책 질의의 RAG exposure가 누락되는 것을 방지한다. 이 절차는 답변을 조작하기 위한 장치가 아니라, 표 chunk가 실험 조건상 prompt에 실제 노출되었는지 검증하기 위한 최소 fallback이다.

## 작동 조건

```text
1. query가 table-sensitive로 분류됨
2. vector-only top-k 결과에 block_type=table chunk가 없음
3. lexical metadata/text matching으로 table candidate를 후보화함
4. 최종 payload에는 vector 결과 일부와 lexical table candidate 1개를 포함할 수 있음
```

## 필수 로그

```text
□ vector_only_result
□ table_sensitive_query
□ table_exposure
□ retrieval_method
□ retrieval_source: vector | lexical | hybrid
□ lexical_table_candidate_count
□ lexical_table_candidate_ids
□ retrieved_chunk_ids
□ collection_name
□ corpus_version
```

## 해석 원칙

```text
□ hybrid fallback은 RAG treatment 자체가 아니라 retrieval exposure validation control로 분류한다.
□ source table 값, chunk 원문, eligibility threshold는 변경하지 않는다.
□ broad query에서 lexical score가 높은 table chunk가 들어갈 수 있으므로 table_id 적합성은 TR subset에서 샘플링 확인한다.
□ vector_only_result를 보존하지 않은 run은 retrieval 비교 불가능으로 failed_retrieval 처리한다.
```

---

# STEP 0.9 — Harness Smoke Test and Generation Quality Gate

## 목적

Harness가 RAG 노드와 A/B/C inference nodes를 실제로 호출하는 것과, 그 호출이 측정 가능한 응답 본문을 생성하는 것은 구분되어야 한다. 따라서 path readiness와 generation-quality readiness를 분리한다.

## 판정 항목

```text
□ path_ready=true
□ generation_quality_ready=true
□ overall_ready=true
□ A/B rag_injected=1
□ C rag_injected=0
□ response_text_len > 0
□ nonempty_response_text_rows = total_rows
□ thinking_disabled_requested=true
□ thinking_present_rows=0
□ thinking_control_effective=true
□ prompt_eval_count < 4096
```

## Response Parser Policy

```text
□ /api/generate 응답의 data["response"]를 response_text로 사용
□ /api/chat 응답 사용 시 message.content fallback 적용
□ data["thinking"]은 thinking_text로 별도 보존
□ thinking_text를 response_text에 병합하지 않음
□ response_field_used 기록
□ raw_response_keys / response_text_len / thinking_text_len / empty_response_text 기록
```

## Ollama Invocation Policy

```text
□ stream=false
□ top-level "think": false
□ temperature=0.0
□ seed=42
□ smoke-test 기준 num_predict=512
```

## Accepted Pre-CR Smoke Snapshot

```text
□ top-k=3 run_id=20260523T_topk3_v2_table_safe_hybrid_thinkfalse_np512 통과
□ top-k=5 run_id=20260523T_topk5_v2_table_safe_hybrid_thinkfalse_np512 통과
□ lacp_docs_v2_table_safe_topk3 collection_count=3503
□ lacp_docs_v2_table_safe_topk5 collection_count=3503
□ top-k=3 nonempty_response_text_rows=9, thinking_present_rows=0
□ top-k=5 nonempty_response_text_rows=9, thinking_present_rows=0
□ top-k=3 / top-k=5 모두 path_ready=true, generation_quality_ready=true, overall_ready=true
```

## Generation Termination Policy

```text
□ done_reason 기록
□ done_reason=stop은 정상 종료로 분류
□ done_reason=length는 truncated_response risk로 분류
□ smoke test에서는 warning으로 허용 가능
□ CR / Run B / CF Runs에서는 truncated_response 포함 여부를 사전 규칙으로 결정
□ truncated_response를 causal evidence로 직접 해석하지 않음
```

---

# STEP 0.10 — Formal Logprobs Extraction and LMS Availability Gate

## 목적

LMS(Logit Margin Score)는 token-level logprobs 또는 이에 준하는 token candidate distribution이 있을 때만 계산할 수 있다. 따라서 CR, CR2, Run B, CF Runs에 진입하기 전에 Harness가 formal endpoint에서 logprobs를 실제로 요청하고, 응답에서 추출하며, LMS 계산 가능성을 검증해야 한다.

이 단계는 smoke readiness와 구분된다. Smoke test는 path readiness와 generation-quality readiness를 확인하지만, formal LMS measurement는 반드시 token-level logprobs availability를 별도로 통과해야 한다.

## 핵심 원칙

```text
□ LMS는 text-only heuristic으로 대체 계산하지 않는다.
□ native Ollama endpoint의 logprobs absence를 causal evidence로 해석하지 않는다.
□ formal measurement path는 OpenAI-compatible /v1/chat/completions를 사용한다.
□ formal path에서는 logprobs=true, top_logprobs=5를 요청한다.
□ response choices[0].logprobs.content를 token-level logprobs source로 사용한다.
□ empty <think></think> shell 제거 시 해당 prefix token positions는 LMS 계산에서 제외한다.
□ missing logprobs는 LMS/LMS_delta evidence를 무효화하지만 CDS/MA evidence를 자동 무효화하지 않는다.
```

## Endpoint Mode Policy

Harness의 endpoint mode는 run mode에 따라 분리한다.

```text
smoke:
  endpoint_mode = native_chat
  endpoint = Ollama native /api/chat
  purpose = path readiness + response parser + generation-quality check
  logprobs absence = 허용 가능, causal evidence로 사용 금지

formal:
  endpoint_mode = openai_chat_completions
  endpoint = OpenAI-compatible /v1/chat/completions
  purpose = CR / CR2 / Run B / CF measurement
  request_logprobs = true
  top_logprobs = 5
  logprobs absence = guarded failure
```

현재 구현 기준:

```text
runtime_impl/harness/config/node_config.yaml
  model.endpoint_by_run_mode.smoke = native_chat
  model.endpoint_by_run_mode.formal = openai_chat_completions
  model.request_logprobs = true
  model.top_logprobs = 5
  model.thinking = false
  model.temperature = 0.0
  model.seed = 42
  model.num_predict = 512
```

## Formal Request Payload

Formal run에서 NodeClient는 OpenAI-compatible chat completions payload를 사용한다.

```json
{
  "model": "qwen3-nothink",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ],
  "temperature": 0.0,
  "seed": 42,
  "max_tokens": 512,
  "logprobs": true,
  "top_logprobs": 5,
  "think": false
}
```

URL 변환 규칙:

```text
if node url contains /api/chat:
  replace /api/chat with /v1/chat/completions
else if node url ends with /:
  append v1/chat/completions
else:
  use configured url as-is
```

## Response Extraction Policy

Formal response에서 본문과 logprobs는 분리해서 추출한다.

```text
response_text_raw:
  choices[0].message.content

raw_logprobs:
  choices[0].logprobs.content

clean_logprobs:
  raw_logprobs에서 empty <think></think> shell prefix token positions를 제외한 목록

excluded_token_positions:
  removed_prefix_chars 안에 완전히 포함되는 token index 목록
```

현재 구현 기준:

```text
runtime_impl/harness/node_client.py
  NodeClient.chat()
  NodeClient._openai_chat_url()
  NodeClient._extract_openai_logprobs()
  NodeClient._split_logprobs_by_prefix()
```

추출 실패 조건:

```text
□ choices가 없거나 비어 있음
□ choices[0].logprobs가 dict가 아님
□ choices[0].logprobs.content가 list가 아님
□ content item에 top_logprobs 후보가 없음
```

## LMS Computation Policy

LMS는 다음 source 중 하나가 있을 때만 계산한다.

```text
primary:
  OpenAI-compatible choices[0].logprobs.content

legacy fallback:
  response_raw.token_candidates
  response_raw.logprobs
  item.top_logprobs / item.candidates / item.scores
```

금지 사항:

```text
□ response text만으로 LMS를 추정하지 않는다.
□ token count, output length, certainty phrase를 LMS proxy로 사용하지 않는다.
□ missing logprobs를 0 또는 평균값으로 보정하지 않는다.
□ missing logprobs turn을 LMS_delta 계산에 포함하지 않는다.
```

현재 구현 기준:

```text
runtime_impl/harness/metrics.py
  compute_lms()
  _extract_openai_logprob_items()
  _extract_legacy_token_candidates()
  compute_cross_node_metrics()
```

## LMS / Logprob Preflight

Formal measurement 진입 전 A/B/C 모든 node에 대해 다음을 확인한다.

```text
□ endpoint_mode=openai_chat_completions
□ HTTP status=200
□ response_text_len > 0
□ choices list present
□ raw_logprobs_len > 0
□ clean_logprobs_len > 0
□ lms_available=true
□ lms_token_count > 0
□ thinking_tag_present=false 또는 empty_thinking_shell만 cleaning 처리
□ thinking_content_present=false
□ failed_TR=false
```

검증 스크립트:

```text
verify_remote/check_harness_formal_nodeclient.py
  formal endpoint 호출
  raw_logprobs_len 출력
  clean_logprobs_len 출력
  excluded_token_positions 출력
  lms_available 출력
  lms_token_count 출력
  lms_value 출력

verify_remote/check_lms_fields.py
  native /api/chat 및 /api/generate 응답 field 탐색용
  formal LMS path의 최종 기준이 아니라 compatibility/readiness 조사 도구로 사용
```

## Missing Logprobs Execute Policy

Formal measurement path에서 missing logprobs는 기대되는 정상 상태가 아니다. LMS / Logprob Preflight를 통과한 뒤에는 A/B/C formal endpoint가 token-level logprobs를 제공해야 한다.

```text
formal path:
  run_mode=formal
  endpoint_mode=openai_chat_completions
  request_logprobs=true

expected:
  logprobs present
  LMS available
  LMS_delta available when Node C and compared node both have LMS

guarded failure:
  missing logprobs
    -> LMS unavailable
    -> LMS_delta unavailable
    -> LMS-based trigger evidence invalid for that node-turn
    -> node-turn is stored with missing-logprobs audit fields
```

단, missing logprobs는 CDS/MA evidence를 자동 무효화하지 않는다. MA는 response text 기반 지표이고, CDS는 embedding 기반 지표이므로 metric availability는 trigger policy에서 별도로 판단한다.

반복적으로 missing logprobs가 발생하면 run-level readiness failure로 판정하고 formal CR / CR2 / Run B / CF Runs에 진입하지 않는다.

## DB and Audit Fields

logprobs extraction과 LMS eligibility는 DB/JSONL에 추적 가능해야 한다.

```text
turn_node_logs:
  endpoint_mode
  raw_response
  thinking_tag_present
  empty_thinking_shell
  thinking_content_present
  cleaning_applied
  failed_TR
  removed_prefix_chars
  raw_logprobs_len
  clean_logprobs_len
  excluded_token_positions

metric_logs:
  lms_value
  lms_token_count
  theta_entropy
  lms_delta
  lms_trigger_eligible
  metric_trigger_eligible
```

해석 규칙:

```text
□ raw_logprobs_len은 model response 원본에서 확인된 token-level evidence 규모를 뜻한다.
□ clean_logprobs_len은 LMS 계산에 실제 사용 가능한 token-level evidence 규모를 뜻한다.
□ excluded_token_positions는 cleaning 때문에 LMS에서 제외된 token positions이다.
□ lms_trigger_eligible=false는 LMS 기반 trigger evidence 부재를 뜻하며, response 자체가 무효라는 뜻은 아니다.
```

## Go / No-Go

```text
GO:
  A/B/C formal endpoint에서 clean_logprobs_len > 0
  compute_lms()가 lms_available=true 반환
  missing-logprobs audit fields 저장 확인
  thinking output contamination 없음

NO-GO:
  formal endpoint가 native endpoint로 drift
  logprobs request가 payload에서 누락
  choices[0].logprobs.content absence
  lms_available=false 반복 발생
  LMS를 text heuristic으로 대체하려는 코드 또는 분석 절차 발견
```

## 논문/분석 반영 규칙

```text
□ LMS 결과를 보고할 때 logprobs source와 endpoint_mode를 함께 명시한다.
□ LMS_delta는 Node C baseline과 비교 대상 node 모두 LMS available일 때만 계산한다.
□ LMS 부재 turn은 causal evidence로 보강하지 않는다.
□ CDS/MA만 남은 turn은 LMS-based causal evidence가 아니라 partial metric evidence로 분류한다.
□ missing logprobs 반복 발생 시 실험 결과가 아니라 infrastructure readiness failure로 보고한다.
```

---

# STEP 0.11 — Formal Retrieval Candidate Freeze Gate

## 목적

CR / CR2 / Run B 진입 전에 retrieval substrate가 조용히 바뀌지 않도록
full-guideline corpus 기반 formal retrieval candidate를 명시적으로 고정한다.
이 단계는 causal result가 아니라 pre-calibration operational validity control이다.

## Candidate Identity

```text
run_id = 20260525T_full_guideline_v1
corpus_version = v1_full_guideline_table_safe
base_collection_name = lacp_docs_v1_full_guideline_table_safe
candidate_collection_name = lacp_docs_v1_full_guideline_table_safe_body_only_v1
chunk_count = 12240
source_count = 18
embedding_dimension = 384
rag_node_ingest = pending / not accepted until write manifest exists
```

## Embedding Text Policy

Formal candidate의 embedding surface는 `body_only_v1`로 고정한다.
저장된 chunk document에는 source boundary와 provenance text를 보존하지만,
embedding에는 반복되는 `[LACP_SOURCE_BOUNDARY]` wrapper를 제거하고 chunk body만 사용한다.

이 정책은 source provenance를 삭제하는 것이 아니라,
반복 provenance wrapper가 vector retrieval을 지배하는 것을 막기 위한 embedding-surface policy이다.

Diagnostic evidence:

```text
original_with_source_boundary vector-only expected-any top5 = 0.2000
body_only_v1 vector-only expected-any top5 = 0.8667
body_only_v1 vector-only candidate top30 = 0.9889
source dominance warning disappeared under body_only_v1
```

## Primary Fusion Candidate

Formal candidate는 다음 retrieval route로 고정한다.

```text
candidate_generation = vector_top30 + lexical_top30
fusion = hybrid_union_rrf_lexical_weighted_07_03
dedup_key = chunk_id
RRF_k = 60
vector_weight = 0.3
lexical_weight = 0.7
final_topK = 5
```

단, prompt-size gate에서 top5가 context-window saturation 또는 generation-quality failure를 유발하면
run-specific gate에 따라 top3를 사용할 수 있다. 이 경우 top-k 변경은 run log에 반드시 기록한다.

Diagnostic evidence:

```text
expected-any top5 = 0.9222
expected-any candidate top30 = 0.9889
primary top5 = 0.7889
dominant top1 ratio = 0.1000
g04 wrong top1 count = 1
lexical-hit union-miss count = 0
zero-hit primary sources = none
```

## Source-Aware Table Diagnostic

Table-sensitive query에 대해서는 source-aware table route를 diagnostic-only로 허용한다.
이는 treatment payload를 임의로 조작하기 위한 장치가 아니라,
table evidence exposure risk를 진단하기 위한 logging route이다.

작동 원칙:

```text
□ table_sensitive=true query에만 적용
□ base route는 body_only_v1 + hybrid_union_rrf_lexical_weighted_07_03 유지
□ table candidates는 base top5에 이미 등장한 source/guideline 안에서만 후보화
□ unrelated source의 table chunk 강제 삽입 금지
□ vector-only result와 primary union result를 별도 보존
□ formal table freeze는 manual labels 통과 전 선언 금지
```

Diagnostic evidence:

```text
expected-any top5 = 0.9222
table-sensitive expected-any top5 = 0.9333
table exposure hit = 0.4667
dominant top1 ratio = 0.1000
g04 wrong top1 count = 1
```

해석:

```text
□ source-aware table route는 source dominance를 재발시키지 않으면서 table exposure를 개선했다.
□ 그러나 table exposure hit 0.4667은 formal target 0.80 미만이다.
□ 따라서 table route는 manual section/chunk/table label 검토 전까지 diagnostic-only이다.
```

## Evidence Sidecar Policy

Evidence sidecar는 base retrieval policy와 분리한다.

```text
sidecar_logging_enabled = true
sidecar_prompt_injection_enabled = false
sidecar_status = diagnostic_only
CR/CR2 default retrieval must not include sidecar prompt injection
```

Sidecar v1 diagnostic:

```text
expected-any top5 preserved = 0.9222
candidate top30 preserved = 0.9889
dominant top1 ratio preserved = 0.1000
section_or_chunk_hit_rate = 0.625
combined_context_evidence_hit_rate = 0.6500
sidecar_expected_evidence_hit_rate = 0.3500
critical_failure_count = 24
table_sensitive_critical_failure_count = 7
sidecar_wrong_evidence_count = 21
sidecar attached queries = 70/90
average added chars when present = about 2297
```

해석:

```text
□ sidecar v1은 base retrieval quality를 손상하지 않는다.
□ 그러나 section/chunk/table-level assisted gate를 통과하지 못했다.
□ prompt payload도 CR/CR2 default injection으로 쓰기에는 과중하다.
□ 따라서 sidecar v1은 logging-only diagnostic evidence로만 보존한다.
```

Future sidecar v2 diagnostic은 다음 제약을 만족해야 한다.

```text
□ sidecar_max_items = 1
□ sidecar_max_chars_per_query = 800~1000
□ base top5 evidence-miss risk가 있을 때만 적용
□ table_sensitive / exception / eligibility / procedure query에 한정
□ source/guideline anchor match 필수
□ query-type marker match 필수
□ high-confidence evidence score 필수
□ prompt injection eligibility를 별도 기록
```

## Manual Freeze Gate

Formal retrieval freeze는 40-query stratified v2 manual label set이 통과해야 선언할 수 있다.
수동 라벨은 source-level hit가 아니라 실제 section/chunk/table evidence hit를 확인한다.

필수 라벨:

```text
□ expected_section
□ expected_chunk_id
□ expected_block_type
□ expected_table_id
```

Stratified v2 set:

```text
table_sensitive = 10
eligibility = 8
exception = 8
procedure = 6
concept = up to 4, with corpus-query deficit filled by borderline cases
title_direct = 2
previous failure/borderline = at least 2
```

Freeze thresholds:

```text
□ critical_failure_count = 0
□ table_sensitive_critical_failure_count = 0
□ major_failure_count <= 3
□ section_or_chunk_hit_rate >= 0.80
□ wrong_table_insertion_count = 0, or at most 1 explainable case
□ expected_source_dropped_after_table_aug <= 1
□ failures must not cluster in a single source or query type
```

Manual v2 set이 critical failure cluster를 보이지 않는 한,
CR/CR2 이전 manual freeze gate를 60 또는 90 query로 확장하지 않는다.

## Required Retrieval Logs

CR / CR2 / Run B의 모든 retrieval row는 다음 필드를 보존해야 한다.

```text
□ retrieval_mode
□ embedding_text_policy
□ collection_name
□ corpus_version
□ candidate_generation
□ final_topK
□ dedup_key
□ vector_rank
□ lexical_rank
□ table_lexical_rank
□ vector_score
□ lexical_score
□ rrf_score
□ source_routes
□ table_exposure
□ sidecar_logging_enabled
□ sidecar_prompt_injection_enabled
□ supporting_evidence_candidates, when diagnostic logging is enabled
```

## Evidence Artifacts

```text
remote_log_root = /Users/morophi/lacp_rag/full_corpus/20260525T_full_guideline_v1/logs

required_artifacts:
  retrieval_variant_comparison.csv
  retrieval_variant_comparison.json
  source_aware_table_diagnostic.csv
  manual_labeling_targets_v1.csv
  manual_labeling_targets_v2.csv
  full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_lexical_weighted_07_03_report.json
  full_guideline_retrieval_coverage_body_only_v1_hybrid_union_rrf_table_source_aware_diag_report.json
  body_only_v1_hybrid_union_rrf_table_source_aware_diag_table_sensitive_slice.csv
  full_guideline_retrieval_coverage_body_only_v1_evidence_sidecar_v1_report.json
  manual_labeling_freeze_gate_v2_evidence_sidecar.json
```

---

---

# STEP 0.12 — Pre-Formal E2E Readiness and Artifact Integrity Gate

## 목적

Pre-formal E2E readiness gate는 TR / CR / CR2 / Run B / CF Runs 직전에 inference runtime, actual first-turn payload, logprobs path, metric artifact, CDS reference, RAG top-k payload envelope, thermal state, DB persistence readiness가 formal 실행 조건에서 안정적인지 검증하는 Go/No-Go 절차이다.

이 단계는 formal experimental data를 생성하지 않는다. 따라서 experimental DB에 write하지 않으며, Harness `/turn` endpoint도 호출하지 않는다. 목적은 결과를 생성하는 것이 아니라, 결과를 오염시킬 수 있는 runtime / payload / artifact / metric completeness 위험을 formal run 이전에 차단하는 것이다.

## 2026-05-27 E2E Issue Sampling Evidence

E2E smoke/readiness sampling 과정에서 다음 stable state가 확인되었다.

```text
validated_state_date = 2026-05-27
latest_top_k_2_smoke_pass = e2e_rough_20260527T1032Z
latest_top_k_3_smoke_pass = e2e_rough_topk3_20260527T1043Z
top_k_3_actual_first_turn_readiness_pass = inference_readiness_20260527T104010Z
metric_complete_rows = 9/9
turn_node_logs = 9
intervention_logs = 9
metric_logs = 9
post_cooldown_temperature_range = approximately 47-49 C
```

해석:

```text
□ E2E path는 operational 상태에 도달했다.
□ 그러나 안정성은 runtime readiness, measurement completeness, treatment payload strength를 분리한 뒤에야 확보되었다.
□ E2E pass는 formal causal result가 아니라 formal run 진입 전 operational envelope evidence이다.
```

## DB-Free Inference Readiness Gate

`systemctl active`, open port, node reachable은 formal readiness로 충분하지 않다. 이전 실패 요청이 Ollama/Vulkan model runner를 stale occupation 상태로 남기면 다음 run을 오염시킬 수 있기 때문이다.

각 formal run 직전에 inference1 / inference2 / inference3에 대해 Harness와 동일한 inference endpoint 및 logprobs path를 직접 검증한다.

```text
□ endpoint_reachable=true
□ OpenAI-compatible /v1/chat/completions path 확인
□ logprobs=true 요청 확인
□ top_logprobs=5 반환 확인
□ response_text_len > 0
□ think=false 적용 확인
□ temperature=0.0 적용 확인
□ HTTP 500 없음
□ timeout 없음
□ raw_logprobs_len > 0
□ clean_logprobs_len > 0
□ lms_available=true
□ node별 elapsed_ms 기록
```

정책:

```text
□ Preflight는 DB write를 수행하지 않는다.
□ Preflight는 Harness /turn endpoint를 호출하지 않는다.
□ Preflight evidence는 별도 JSON artifact로만 저장한다.
□ Preflight 실패 시 formal run을 시작하지 않는다.
```

## Actual First-Turn Dry-Run Probe

Synthetic long probe는 primary Go/No-Go gate로 사용하지 않는다. E2E sampling에서 synthetic long probe는 실제 Harness intervention path를 재구성하지 못했고, 경우에 따라 Node B runtime을 오히려 destabilize할 수 있음이 확인되었다.

Readiness는 actual first-turn dry-run을 기준으로 한다.

```text
□ scenario first turn 로드
□ Run B / smoke trigger logic 적용
□ RAG retrieval 수행
□ SC policy assembly 수행
□ Node A/B/C message payload 실제 구성
□ Harness /turn 호출 없이 inference node를 직접 호출
□ DB write 없이 JSON evidence만 저장
□ response_text_len / logprobs / elapsed_ms / error field 기록
```

금지 또는 제한:

```text
□ heavy synthetic long probe를 default preflight에 포함하지 않는다.
□ synthetic 4k+ prompt probe는 manual diagnostic flag에서만 허용한다.
□ formal run 직전 redundant stress probe를 반복하지 않는다.
```

## Runner Unload and Settle Policy

DB와 Harness `/turn`을 건드리지 않더라도 direct inference probe는 model runner, GPU memory, warm state, thermal state에 영향을 줄 수 있다. 따라서 preflight 완료 후 runner unload와 settle interval을 적용한다.

```text
□ preflight probe 완료
□ keep_alive=0 또는 equivalent unload 요청
□ runner process / stale occupation 해소 확인
□ settle interval 적용
□ 필요 시 idle temperature snapshot 재확인
□ unload / settle 실패 시 formal run 시작 금지
```

해석 원칙:

```text
Preflight는 formal run의 일부가 아니며, formal first turn을 warm-start 상태로 만들면 안 된다.
```

## Node B Runtime Sensitivity Policy

E2E sampling에서 Node B는 repeated direct logprobs workload와 synthetic long probe 이후 HTTP 500 또는 `signal arrived during cgo execution` 오류에 민감하게 반응했다.

```text
observed_sensitive_node = inference2 / Node B
sample_failures = inference_readiness_20260527T101802Z, inference_readiness_20260527T102650Z
error_pattern = HTTP 500 / signal arrived during cgo execution
likely_classification = Ollama/Vulkan runner instability under repeated logprobs workload
```

정책:

```text
□ longer TR / CR 전 inference2 runner clean restart 고려
□ actual-first-turn readiness를 기준으로 통과 여부 판단
□ redundant synthetic stress probe 금지
□ cooldown 후 formal run 진입
□ Node B error는 RAG context overflow로 단정하지 않고 runtime substrate failure로 분류
```

## Smoke/Formal Generation Budget Separation

Smoke evidence는 긴 답변 본문을 필요로 하지 않는다. Smoke의 목적은 path, routing, nonempty response, logprobs, LMS/CDS/MA, DB persistence가 한 바퀴 도는지 확인하는 것이다.

```text
smoke:
  num_predict = 256
  purpose = readiness / plumbing / metric completeness evidence

formal:
  num_predict = separately configured
  purpose = CR / CR2 / Run B / CF measurement
```

정책:

```text
□ smoke와 formal generation budget을 분리한다.
□ smoke num_predict 축소는 formal treatment weakening으로 해석하지 않는다.
□ formal num_predict는 top-k와 runtime stability가 고정된 뒤 별도 결정한다.
```

## Formal Top-k Payload Envelope Governance

E2E sampling에서 `top_k=5`는 현재 BC-250 + Qwen3 + Ollama + logprobs runtime envelope에서 안전한 default로 보기 어렵다.

Observed payload evidence:

```text
top_k=5 earlier path:
  Node A actual first-turn prompt approached oversized behavior
  estimated Ollama-side prompt token count about 8525

top_k=2 smoke pass:
  run_id = e2e_rough_20260527T1032Z
  A prompt avg/max = 3083 / 3436
  B prompt avg/max = 2614 / 2989
  metric_complete = 9/9

top_k=3 smoke pass:
  run_id = e2e_rough_topk3_20260527T1043Z
  A prompt avg/max = 4167 / 4766
  B prompt avg/max = 3757 / 4319
  metric_complete = 9/9
  empty_response = 0
  HTTP 500 = 0
  DB rows = 9/9

top_k=3 actual-first-turn readiness:
  run_id = inference_readiness_20260527T104010Z
  A prompt = 4766
  B prompt = 4319
  C prompt = 217
```

Policy:

```text
□ formal top_k=5는 추가 증거 전까지 unsafe로 취급한다.
□ top_k=3을 leading formal candidate로 검토한다.
□ top-k는 retrieval quality뿐 아니라 Node A maximum-payload condition의 prompt-load stability로 선정한다.
□ smoke-only top-k override는 formal readiness를 대표하지 않는다.
□ TR / CR2 / Run B / CF는 동일 formal top-k를 사용해야 한다.
□ formal top-k 변경 시 retrieval freeze와 CR2 threshold freeze를 변경된 top-k 기준으로 재수행한다.
```

## CDS Reference Artifact Freeze and Embedding-Space Consistency

CDS는 response embedding과 fixed policy reference embedding 사이의 cosine distance를 계산한다. 따라서 reference embedding과 response embedding은 반드시 동일 embedding space에 있어야 한다.

E2E issue sampling에서 다음 문제가 확인되었다.

```text
missing_artifact = /home/morophi/harness/reference/reference_embedding.npy
Chroma stored embedding dimension = 384
initial CDS config model = snunlp/KR-SBERT-V40K-klueNLI-augSTS
initial CDS config dimension = 768
risk = reference / response embedding dimension mismatch
```

Action and policy:

```text
□ CDS reference는 RAG corpus / embedding freeze 단계의 offline artifact로 생성한다.
□ Harness/readiness 단계에서 Chroma document를 재인코딩하지 않는다.
□ Harness는 fixed reference files만 read-only로 사용한다.
□ Reference는 RAG node에서 frozen Chroma stored embeddings 전체 평균으로 생성한다.
□ response embedding model은 reference embedding stream과 동일한 384-dim MiniLM 계열로 정렬한다.
□ manifest에 collection_name, collection_count, embedding_model, source embedding stream hash, output hash를 기록한다.
```

Allowed structure:

```text
RAG/corpus node
  → frozen Chroma stored embeddings 평균
  → reference_embedding.npy 생성
  → reference_embedding.sha256 생성
  → reference_embedding_manifest.json 생성
  → Harness reference directory로 fixed artifact만 배치
  → Harness는 metric computation 시 read-only 사용
```

Forbidden structure:

```text
Harness
  → Chroma collection 직접 접근
  → corpus document 재인코딩
  → reference artifact 즉석 생성
  → readiness와 artifact generation 혼합
```

## Harness / RAG Role Boundary

Academic defensibility를 위해 역할 경계를 유지한다.

```text
RAG / corpus node:
  chunking, embeddings, Chroma, reference artifact generation

Harness:
  orchestration, intervention policy, prompt assembly, fixed artifact 기반 metric computation, logging

Inference nodes:
  generation only
```

Operational pressure to make E2E pass must not blur architectural roles.

## Validator Strictness Policy

Validator가 `metric_complete_rows`, `response_empty_rows`, `timeout_or_500_rows`를 엄격히 차단한 것은 올바른 동작으로 본다. Validator를 완화하지 말고 missing artifact와 runtime error를 해결한다.

```text
blocked_sample:
  response_text empty rows = 1
  timeout_or_500_rows = 1
  metric complete rows = 0/9

after_fix:
  metric_complete_rows = 9/9
  response_empty_rows = 0
  row_count = 9
```

정책:

```text
□ TR readiness에서는 strict validator를 유지한다.
□ run mode별 acceptance criteria가 다르면 문서화한다.
□ silent weakening 금지
```

## DB Path and Async Logging Health

E2E sampling에서 short E2E/TR readiness 기준 DB path와 async logging은 정상으로 확인되었다.

```text
turn_node_logs = 9
intervention_logs = 9
metric_logs = 9
flush_completed = true
```

정책:

```text
□ DB schema check는 E2E script에 유지한다.
□ scenario execution 후 explicit /flush 유지
□ longer CR / CF에서는 DB write jitter와 partial row를 별도 monitoring한다.
```

## Thermal Evidence Policy

E2E sampling에서 logprobs + RAG + parallel A/B/C generation은 유의미한 heat spike를 만들었다.

```text
top_k=2 smoke thermal max:
  inference1 = 79 C
  inference2 = 73 C
  inference3 = 71 C

top_k=3 smoke thermal max:
  inference1 = 80 C
  inference2 = 74 C
  inference3 = 74 C

later cooldown:
  inference1 = 47.75 C
  inference2 = 48.5 C
  inference3 = 47.125 C
```

정책:

```text
□ formal runs는 fixed cooldown policy와 thermal evidence를 유지한다.
□ temperature control은 experimental treatment가 아니라 infrastructure control이다.
□ high thermal state에서 repeated readiness stress probe를 수행하지 않는다.
```

## E2E Blocker Classification

Formal run 시작 전 발견된 문제는 causal result failure가 아니라 pre-formal readiness blocker로 분류한다.

```text
□ native endpoint LMS unavailability
□ thinking artifact contamination risk
□ synthetic readiness probe insufficiency
□ synthetic long probe-induced runtime perturbation
□ stale runner occupation
□ HTTP 500 / empty response
□ CDS reference artifact missing
□ CDS embedding dimension mismatch
□ Harness/RAG role boundary violation risk
□ top_k=5 payload instability
□ smoke/formal generation-budget mismatch
□ metric completeness blocker
□ thermal overload risk
□ SSH/sandbox environment mismatch
□ service ownership misidentification
```

분류 원칙:

```text
□ causal data generation 전 발견된 blocker는 experimental result DB에 기록하지 않는다.
□ blocker는 logs/preflight 또는 diagnostic evidence로 보존한다.
□ unresolved blocker가 있으면 TR / CR / CR2 / Run B / CF에 진입하지 않는다.
```

## Preflight Evidence JSON Minimum Fields

```json
{
  "run_id": "string",
  "gate_name": "pre_formal_e2e_readiness",
  "timestamp": "ISO-8601",
  "status": "PASS_or_FAIL",
  "decision": "GO_or_NO_GO",
  "db_write": false,
  "harness_turn_called": false,
  "formal_run_started": false,
  "nodes": {
    "inference1": {
      "endpoint_reachable": true,
      "generation_ok": true,
      "response_text_len": 1,
      "raw_logprobs_len": 1,
      "clean_logprobs_len": 1,
      "top_logprobs_present": true,
      "think_false_applied": true,
      "elapsed_ms": 0,
      "http_status": 200,
      "runtime_error": null
    },
    "inference2": {},
    "inference3": {}
  },
  "payload": {
    "formal_top_k_candidate": 3,
    "final_prompt_chars_node_a": 0,
    "final_prompt_chars_node_b": 0,
    "final_prompt_chars_node_c": 0,
    "prompt_eval_count_node_a": 0,
    "rag_context_chars": 0,
    "done_reason": "stop"
  },
  "cds_reference": {
    "reference_embedding_exists": true,
    "reference_shape": [384],
    "response_embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "reference_embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "embedding_space_consistent": true,
    "sha256": "string",
    "manifest_exists": true
  },
  "runner_cleanup": {
    "unload_requested": true,
    "settle_completed": true,
    "stale_runner_detected": false
  }
}
```

## Professor Discussion Framing

교수 면담에서는 다음 문장으로 정리한다.

```text
The E2E process converted informal system readiness into explicit, auditable experimental controls. Each failure identified a boundary condition: LMS endpoint capability, CDS artifact completeness, RAG context size, inference-node runtime stability, thermal behavior, and DB persistence. The final pass is therefore not merely a successful run; it is evidence that the experiment now has a defined operational envelope.
```

한국어 요약:

```text
E2E는 단순히 버그를 고쳐 통과시킨 절차가 아니라, formal causal data 생성 전에 runtime, metric, payload, artifact, thermal, DB persistence의 경계 조건을 명시적으로 드러낸 operational validity gate이다.
```

# Failed Run Classification

| 실패 유형                      | 의미                                                                                                               | 처리                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| corpus failure                 | canonical / chunk / embedding 문제                                                                                 | STEP 0 재수행                                               |
| retrieval failure              | top-k coherence 또는 retrieval miss                                                                                | STEP 0.5 재수행                                             |
| pipeline failure               | DB / logging / node routing 문제                                                                                   | TR 재수행                                                   |
| model execution failure        | timeout / empty response                                                                                           | failed_TR archive                                           |
| metric contamination           | thinking trace / missing LMS·MA·CDS row                                                                            | failed_TR archive, CR 진입 금지                             |
| retrieval substrate failure    | context-window saturation / table semantic collapse / chunking policy-trigger contamination                        | STEP 0.1~0.4 재수행, collection version bump                |
| retrieval exposure failure     | vector-only table miss without fallback logging / missing vector_only_result                                       | STEP 0.8 재수행                                             |
| generation quality failure     | ok=true but response_text empty / parser mismatch / thinking control ineffective                                   | STEP 0.9 재수행                                             |
| logprobs availability failure  | formal endpoint drift / logprobs request 누락 / choices[0].logprobs.content absence / lms_available=false 반복     | STEP 0.10 재수행, CR 진입 금지                              |
| retrieval freeze failure       | manual section/chunk/table label gate 미통과 / sidecar prompt injection true / table diagnostic을 treatment로 사용 | STEP 0.11 재수행, CR 진입 금지                              |
| pre-formal readiness failure   | actual first-turn dry-run failure / stale runner occupation / DB-free preflight failure / Node B 500 반복          | STEP 0.12 재수행, formal run 시작 금지                      |
| CDS artifact failure           | reference_embedding.npy 누락 / reference-response embedding dimension mismatch / manifest hash 부재                | RAG corpus freeze artifact 재생성, STEP 0.12 재수행         |
| top-k payload envelope failure | Node A RAG+SC maximum payload가 timeout / HTTP 500 / prompt instability를 유발                                     | formal top-k 재선정, retrieval freeze와 CR2 재수행          |
| role-boundary failure          | Harness가 Chroma/RAG corpus factory 역할을 수행하거나 readiness와 artifact generation이 혼합됨                     | artifact generation을 RAG/corpus node offline step으로 분리 |
| truncation risk                | done_reason=length unresolved                                                                                      | pre-registered truncation policy 확정 전 CR 진입 금지       |

---

# Failed Run Archival Policy

```text
□ failed run 삭제 금지
□ failed_TR / failed_retrieval / failed_pipeline 유형별 보관
□ run_id / timestamp / top-k / thinking flag / num_predict / chunking mode 기록
□ failed run은 causal effect estimation에서 제외
□ failed run은 infrastructure diagnosis 및 reproducibility report에만 사용
```

---

# Go / No-Go 기준 추가

## Retrieval Coherence

```text
□ canonical.md semantic preservation 확인
□ chunk boundary coherence 확인
□ eligibility / exception scope preservation 확인
□ retrieval top-k coherence 확인
□ retrieval stability 확인
□ corpus hash 기록 완료
□ embedding hash 기록 완료
□ coherence failure 발생 시 CR 진입 금지
□ top-k selection protocol 통과
□ thinking_present_rows=0 확인
□ A/B/C 전 노드 nonempty response 확인
□ failed_TR unresolved 상태 아님
□ context-window load test 통과
□ table-safe chunking validation 통과
□ trigger sensitivity check 통과
□ retrieval substrate failure unresolved 상태 아님
□ hybrid table exposure validation 통과
□ Harness smoke test top-k=3 통과 및 top-k=5 안전성 추가 입증 또는 보류 결정
□ path_ready=true 및 generation_quality_ready=true 확인
□ response parser 검증 완료
□ top-level think=false 적용 확인
□ done_reason=length 처리 정책 확정
□ body_only_v1 embedding text policy 확인
□ hybrid_union_rrf_lexical_weighted_07_03 candidate route 확인
□ sidecar_prompt_injection_enabled=false 확인
□ source-aware table route는 diagnostic-only로 기록
□ manual_labeling_targets_v2 freeze gate 통과 전 formal freeze 선언 금지
□ retrieval policy artifact와 report hash 보존
□ DB-free inference readiness gate PASS
□ Harness /turn non-use 확인
□ preflight evidence JSON 저장 완료
□ inference1/2/3 동일 endpoint/logprobs path 통과
□ actual first-turn dry-run 통과
□ stale runner occupation 없음 확인
□ preflight 후 keep_alive=0 unload 완료
□ settle interval 완료
□ smoke-only synthetic long probe default 미사용
□ formal top-k payload stability 확인
□ top_k=3 formal candidate 검토 또는 top_k=5 안전성 추가 입증
□ smoke/formal num_predict 분리 확인
□ CDS reference_embedding.npy 존재 확인
□ CDS reference sha256 / manifest 존재 확인
□ CDS reference dimension과 response embedding dimension 일치
□ Harness가 ChromaDB / RAG collection 직접 접근하지 않음
□ metric completeness blocker 없음
□ E2E blocker unresolved 상태 아님
```

---

# 실험 해석 원칙 추가

Observed intervention effect는 다음 두 조건이 모두 충족될 때만
causal intervention candidate로 해석한다.

```text
1. Retrieval coherence validation 통과
2. Top-k payload stability validation 통과
3. Thinking-output contamination control 통과
4. Context-window / prompt truncation validation 통과
5. Table-safe chunking validation 통과
6. Trigger sensitivity validation 통과
7. Hybrid table exposure validation 통과
8. Harness smoke test 및 generation-quality gate 통과
9. Formal logprobs extraction and LMS availability gate 통과
10. Formal retrieval candidate freeze gate 통과
11. DB-free inference readiness gate 통과
12. Actual first-turn dry-run readiness 통과
13. Runner unload / settle policy 통과
14. Formal top-k payload envelope 확인
15. CDS reference artifact freeze 및 embedding-space consistency 확인
16. done_reason / truncated_response 정책 확정
17. CR / CR2 baseline 안정성 확보
```

retrieval artifact에 의해 생성된 response drift는
causal intervention evidence로 간주하지 않는다.

---

# 결론

rev5부터 LACP는 단순 orchestration 실험이 아니라:

```text
Corpus Validity
→ Retrieval Validity
→ Causal Inference
```

3단계 방어 구조를 갖는 실험 프로토콜로 정의한다.

rev5.1부터는 여기에 pre-CR operational validity 조건을 추가하여,
retrieval payload stability와 thinking-output contamination control이 확보된 run만
causal inference 대상으로 인정한다.

---

# rev5.2 추가 해석

rev5.2부터 top-k 문제는 단순 retrieval parameter 문제가 아니라 RAG substrate validity 문제로 분류한다. large chunk 기준 top-k=3이 ChromaDB에서는 정상 반환되더라도, 모델 context window에서 prompt truncation 또는 A/B concurrent timeout을 유발하면 해당 조건은 causal inference에 사용할 수 없다.

따라서 top-k=3을 유지하려면 table-safe small chunk corpus를 별도 collection으로 재구축하고, table_id / repeated header / table_part_label을 통해 표 의미 구조를 보존해야 한다. 또한 chunking policy 변경은 trigger activation pattern을 바꿀 수 있으므로, trigger sensitivity validation을 통과한 corpus만 CR / CR2 / Run B / CF Runs의 기준 corpus로 인정한다.

---

# rev5.3 추가 해석

rev5.3부터 pre-CR readiness는 단순히 Harness가 노드를 호출하는지 여부가 아니라, 실제 측정 가능한 응답 본문을 생성하는지 여부까지 포함한다. 따라서 ok=true 또는 HTTP success는 path readiness로만 인정하며, response_text_len > 0과 thinking_present_rows=0이 동시에 확인되어야 generation_quality_ready=true로 판정한다.

또한 table-sensitive query에서 vector-only retrieval이 table chunk를 노출하지 못하는 경우, minimal hybrid table fallback은 retrieval exposure validation control로 허용된다. 단, vector_only_result를 보존하고 retrieval_method / retrieval_source / table_exposure를 반드시 기록해야 하며, source value나 chunk 원문을 변경해서는 안 된다.

2026-05-23 기준 top-k=3 및 top-k=5 smoke test는 lacp_docs_v2_table_safe_topk3 / lacp_docs_v2_table_safe_topk5 collection에서 모두 pass condition을 충족했다. 이 결과는 CR 진입을 의미하지 않으며, Offset-aware Pre-CR Test Run으로 넘어가기 위한 execution readiness 조건 충족으로 해석한다.

rev6.1 기준에서는 위 rev5.3 결과를 formal top-k=5 안전성의 최종 근거로 사용하지 않는다. 2026-05-27 실제 E2E issue sampling에서 full first-turn payload, OpenAI-compatible logprobs path, RAG+SC 조립, Node B runtime sensitivity가 함께 드러났기 때문이다. 따라서 formal top-k는 rev6.1의 payload envelope gate를 우선 적용하며, 현재 evidence는 top-k=3을 leading candidate로 보고 top-k=5는 동일 기준의 추가 입증 전까지 보류한다.

---

# rev5.4 추가 해석

rev5.4부터 retrieval readiness는 단순 top-k coherence나 smoke pass를 넘어,
formal CR / CR2 / Run B에 사용할 retrieval substrate의 candidate route를
명시적으로 고정하는 단계까지 포함한다.

Full-guideline corpus 재검증 결과, 반복 source-boundary wrapper를 embedding surface에
포함한 original policy는 vector retrieval에서 source dominance를 유발했다. 따라서
stored chunk document와 provenance는 보존하되, embedding에는 chunk body만 사용하는
`body_only_v1`을 formal candidate embedding policy로 채택한다.

또한 primary route는 `vector_top30 + lexical_top30` union 후
`hybrid_union_rrf_lexical_weighted_07_03`으로 fusion하는 방식으로 고정한다.
이 candidate는 expected-any top5 0.9222와 candidate top30 0.9889를 보였고,
dominant top1 ratio 0.1000으로 source dominance artifact를 완화했다.

다만 table-sensitive evidence와 evidence sidecar는 아직 formal prompt injection
treatment로 인정하지 않는다. Source-aware table route는 diagnostic-only이며,
evidence sidecar v1은 base retrieval quality를 보존했지만 section/chunk/table-level
assisted gate를 통과하지 못했으므로 logging-only로 제한한다.

따라서 CR / CR2 / Run B formal 진입 전에는 40-query stratified manual freeze gate가
통과되어야 한다. 이 gate는 expected source hit가 아니라 실제 section, chunk,
block type, table evidence가 노출되는지를 확인하기 위한 절차이며, 통과 전에는
formal retrieval freeze를 선언하지 않는다.

---

# Rev5.5 Addendum: Rev8 Thermal Safeguard and Turn-Level Synchronization

> Paper alignment: `experiment/lacp_ijibc_rev8.docx`
> Revision date: 2026-05-26
> Status: Mandatory operational control for all RUN stages.

## Purpose

This addendum synchronizes the experiment guideline with paper rev8. The thermal
safeguard policy is an operational validity control, not an experimental
treatment. It is applied uniformly to TR, CR, CR2, CF, and CF-F so that hardware
thermal drift does not become an uncontrolled confounder.

## Turn-Level Barrier Policy

Every experimental turn MUST use a turn-level barrier.

```text
for each turn:
  dispatch the same utterance to Nodes A, B, and C
  wait until all three node responses are completed
  persist all node-level response, intervention, metric, and quality rows
  only then advance to the next turn
```

Rationale:

- Node A/B/C requests may start at nearly the same time, but completion times
  can differ by node.
- A faster node MUST NOT advance to the next turn before the slower nodes finish
  the current turn.
- Causal comparison is based on within-turn matched responses, not on absolute
  wall-clock completion order.

Acceptance checks:

```text
□ Every turn has A/B/C completion records before the next turn begins.
□ Harness returns nodes_completed only after all three inference nodes finish.
□ No node advances independently to the next turn.
□ Turn timestamps are retained as diagnostics, not as causal ordering signals.
```

## Five-Turn Cooldown Policy

After every five completed turns, Harness MUST apply a fixed 30-second cooldown
barrier before dispatching the next turn batch.

```text
after turns 5, 10, 15, 20, 25, and 30:
  record thermal snapshot before cooldown for inference1/2/3
  record cooldown_start event
  sleep 30 seconds
  record thermal snapshot after cooldown for inference1/2/3
  record cooldown_end event
  resume the next turn batch
```

The cooldown policy MUST be identical across TR, CR, CR2, CF, and CF-F.
Therefore, it is not interpreted as part of the RAG intervention. It is a
fixed infrastructure safeguard to reduce thermal throttling, response omission,
node instability, and emergency shutdown risk.

Acceptance checks:

```text
□ 30-second cooldown occurs after every five completed turns.
□ Cooldown is applied to all RUN conditions.
□ Cooldown is not condition-specific or node-specific.
□ Thermal snapshots are recorded before and after cooldown.
□ Cooldown metadata is linked to run_id and batch boundary.
```

## Thermal Snapshot Logging

Thermal snapshots MUST include all inference nodes.

Required fields:

```text
run_id
condition
run_mode
batch_end_turn
event_type = cooldown_start | cooldown_end | thermal_snapshot
cooldown_sec
node
timestamp
max_temp_c
temperatures[]
reachable
source = hwmon | thermal_zone | sensors-derived
```

For Fedora-based inference nodes, the preferred primary source is:

```text
/sys/class/hwmon/hwmon*/temp*_input
```

Thermal zone fallback is allowed only when hwmon readings are unavailable:

```text
/sys/class/thermal/thermal_zone*/temp
```

## Fan and Ambient Assumption

The pre-RUN baseline assumes active fan cooling. Preliminary thermal-only direct
inference probing showed that a five-turn load can raise node temperatures from
the high-40 C range to approximately 69-74 C. Accordingly, full-speed fan
operation is treated as the default defensive state for formal RUN stages unless
a later thermal validation run proves a quieter fan curve maintains equivalent
thermal margins.

## Pre-Run and Post-Run Thermal Evidence

Before formal RUN execution:

```text
□ Confirm inference1/2/3 are reachable.
□ Confirm Ollama is listening on each inference node.
□ Confirm hwmon temperature readings are available.
□ Confirm fan full-speed or approved fan-curve state.
□ Record pre-run idle thermal snapshot.
```

After formal RUN execution:

```text
□ Record final turn completion thermal snapshot.
□ Record cooldown-end thermal snapshot.
□ Archive thermal JSONL or DB thermal event rows with run_id.
□ Confirm no emergency shutdown, throttling, or node dropout occurred.
```

## Interpretation Rule

Thermal safeguards may affect throughput and elapsed wall-clock duration.
Therefore, throughput and latency MUST NOT be interpreted as primary causal
outcomes in runs using this policy. The policy is compatible with the LACP
causal design because all causal conditions receive the same barrier and
cooldown treatment.

## Rev5.6 Thermal Safeguard Empirical Basis

The rev8 thermal safeguard is supported by a second thermal-only validation run
using parallel node temperature sampling and a longer cooldown observation
window.

```text
run_id = thermal_only_5turn_cooldown60_parallel_20260526T170010
mode = thermal_only_direct_inference
nodes = inference1, inference2, inference3
turns = 5
thermal_interval_sec = 1.0
observed_average_sample_interval = approximately 1.004 sec
cooldown_observation = 60 sec
inference_requests = 15
inference_failures = 0
```

Observed cooldown results:

```text
inference1: 72.0 C -> 51.875 C, drop 20.125 C
inference2: 69.0 C -> 52.25 C,  drop 16.75 C
inference3: 73.0 C -> 52.125 C, drop 20.875 C
```

The 60-second cooldown curves are not well represented by a simple linear
cooling assumption. Linear fits remained visually plausible over short windows,
but quadratic and exponential-style decay fits reduced residual error by
approximately one to two orders of magnitude. Segment slopes also show a clear
early-fast and late-slow cooling pattern:

```text
inference1: early -0.515 C/sec, late -0.175 C/sec
inference2: early -0.377 C/sec, late -0.139 C/sec
inference3: early -0.522 C/sec, late -0.179 C/sec
```

Interpretation:

```text
□ Cooling should be treated as nonlinear over the post-load interval.
□ A 30-second cooldown is a conservative operational safeguard, not a complete
  return-to-idle guarantee.
□ Formal RUN stages should retain turn-level barriers and five-turn cooldowns.
□ Thermal evidence is linked to run_id and can be reproduced independently
  without contaminating dblog causal result tables.
```

This empirical basis upgrades the thermal safeguard from a precautionary rule
to a measured operational validity control.

---

# rev6.1 추가 해석

rev6.1부터 E2E는 단순 smoke execution이 아니라 formal causal data 생성 전 operational envelope를 정의하는 pre-formal validity gate로 취급한다. 2026-05-27 E2E issue sampling은 LMS endpoint capability, actual first-turn payload, stale runner contamination, Node B runtime instability, CDS artifact completeness, embedding-space consistency, top-k payload envelope, thermal behavior, DB persistence, Harness/RAG role boundary를 동시에 검증해야 함을 보여주었다.

따라서 `top_k=5`는 현재 formal default로 동결하지 않는다. 현재 evidence는 `top_k=3`을 leading formal candidate로 지지하며, formal top-k 결정은 retrieval quality뿐 아니라 Node A RAG+SC maximum-payload stability를 함께 만족해야 한다. Smoke-only override는 formal readiness를 대표하지 않는다.

CDS reference embedding은 readiness 또는 Harness runtime에서 즉석 생성하지 않는다. 이 artifact는 RAG/corpus freeze 단계에서 생성된 고정 산출물이어야 하며, Harness는 `.npy`, `.sha256`, `manifest.json`만 read-only로 사용한다. Reference embedding과 response embedding은 동일 model stream 및 동일 vector dimension을 가져야 한다.

Preflight는 DB-free, Harness `/turn`-free 방식으로 수행한다. 다만 direct probe는 runner warm state와 thermal state에 영향을 줄 수 있으므로, preflight 이후 `keep_alive=0` unload와 settle interval을 mandatory로 적용한다. Formal run 시작 전 발견된 blocker는 causal result failure가 아니라 pre-formal readiness blocker로 보존한다.

Source evidence file:

```text
E2E_ISSUE_SAMPLING_SUMMARY_20260527.md
SMOKE_EVIDENCE_TOPK3_20260527.md
```
