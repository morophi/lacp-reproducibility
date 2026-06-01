# LACP 노드 설정 체크리스트

**버전**: v10.3 | **작성일**: 2026년 5월 | **작성**: morophi / Stochastic Control Lab


> **v10.3 변경 요지**: v10.2의 RAG substrate validity 조건에 더해 hybrid table-exposure fallback, Harness smoke-test pass condition, response parser 검증, API top-level think=false 제어, num_predict=512 smoke 기준, done_reason=length truncation 관리를 추가한다.

---

# STEP 0 — Pure RAG Ingest Validation

## canonical.md 검증

```text
□ PDF/HWPX → canonical.md 변환 완료
□ UTF-8 인코딩 확인
□ source page metadata 유지
□ section hierarchy 유지
□ markdown heading 정상 변환
□ table flattening 의미 보존
□ key-value 구조 유지
□ 표 내부 eligibility 정보 보존
□ 표 내부 exception 정보 보존
```

---

## Marker Layer 검증

```text
□ eligibility marker tagging 확인
□ exception marker tagging 확인
□ conditional marker tagging 확인
□ benefit marker tagging 확인
□ procedure marker tagging 확인
□ marker priority 정상 동작 확인
□ section header weight 적용 확인
```

---

## Chunk 검증

```text
□ chunk size 정책 적용 확인
□ overlap 정책 적용 확인
□ chunk boundary coherence 확인
□ eligibility / exception scope leakage 없음
□ conditional clause 분리 오류 없음
□ heading inheritance 유지 확인
□ source traceability 유지 확인
```

---

## Table-safe Small Chunking 검증

```text
□ 기존 collection overwrite 금지
□ 새 collection name 기록 완료 (예: lacp_docs_v2_table_safe)
□ corpus_version 기록 완료
□ chunk_size target 800~1000 chars 적용 확인
□ overlap 100~150 chars 적용 확인
□ 단순 character split으로 표 분할 없음
□ 긴 표 row-wise segmentation 적용 확인
□ table_id 존재 확인
□ parent_table_label 존재 확인
□ table_part_label 존재 확인 (예: 표 1-1, 표 1-2)
□ table_part_no / table_part_total 기록 확인
□ repeated column header 확인
□ table_title / columns / unit / year 보존 확인
□ source_file / page / section metadata 보존 확인
□ 각 table chunk 단독 해석 가능성 확인
```

---

## Context Window / Prompt Load 검증

```text
□ top-k 후보별 final_prompt_chars 기록 완료
□ top-k 후보별 rag_context_chars 기록 완료
□ top-k 후보별 prompt_eval_count 기록 완료
□ top-k 후보별 prompt_eval_duration_ms 기록 완료
□ top-k 후보별 eval_count / eval_duration_ms 기록 완료
□ Ollama truncation log 0건 확인
□ "truncating input prompt limit=4096" 로그 발생 시 해당 조건 탈락
□ top-k=3 A/B concurrent generation 통과 확인
□ 180초 timeout / 500 error 발생 시 failed_TR 처리
□ context-window saturation 발생 시 retrieval substrate failure로 분류
```

---

## Hash Governance

```text
□ corpus hash 생성 완료
□ chunk hash 생성 완료
□ embedding hash 생성 완료
□ manifest 기록 완료
□ frozen requirements 저장 완료
□ run_id naming convention 기록 완료
□ top-k / chunking mode / thinking flag / num_predict 조건명 run_id에 포함
```

---

# STEP 0.5 — Retrieval Coherence Validation

## Retrieval Test

```text
□ representative query set 생성 완료
□ eligibility query retrieval coherence 확인
□ exception query retrieval coherence 확인
□ conditional query retrieval coherence 확인
□ benefit query retrieval coherence 확인
□ procedure query retrieval coherence 확인
□ top-k 후보별 retrieval payload completeness 확인
□ top-k 후보별 A/B/C 전 노드 nonempty response 확인
□ top-k 후보별 retrieved_chunk_ids / collection_name / corpus_version 기록 확인
□ table chunk 검색 시 table_id / table_part_label 반환 확인
```

---

## Stability Validation

```text
□ 동일 query 반복 시 ranking consistency 유지
□ top-k retrieval stability 확인
□ reranker 사용 시 ordering consistency 확인
□ retrieval noise 사례 기록 완료
□ failed retrieval 사례 저장 완료
□ elapsed_ms node별 분포 기록 완료
□ timeout threshold 근접 사례 기록 완료
□ failed_TR archive 경로 기록 완료
```

---

## Trigger Sensitivity Validation

```text
□ large-chunk corpus와 small table-safe corpus의 trigger pattern 비교 완료
□ 동일 representative query set 기준 trigger activation 변화 기록 완료
□ chunking policy 변경으로 인한 trigger 과발동 / 저발동 사례 기록 완료
□ trigger assignment contamination 의심 사례 failed_retrieval 또는 failed_TR로 보관
□ chunking policy 확정 전 CR / CR2 진입 금지
```

---


## Hybrid Table Exposure Validation

```text
□ vector_only_result 별도 보존 확인
□ table-sensitive query detector 동작 확인
□ vector top-k 내 table chunk 부재 시 lexical table fallback 후보화 확인
□ retrieval_source = vector / lexical / hybrid 기록 확인
□ retrieval_method 기록 확인 (vector_only / hybrid_table_fallback)
□ table_exposure=true/false 기록 확인
□ lexical_table_candidate_count 기록 확인
□ lexical_table_candidate_ids 기록 확인
□ table fallback은 retrieval exposure validation 목적이며 source table 값 변경 없음 확인
```

## Harness Smoke Test Validation

```text
□ path_ready와 generation_quality_ready 분리 확인
□ ok=true만으로 generation success 판정하지 않음
□ response_text_len > 0 조건에서만 generation_quality_ready=true 확인
□ response parser가 /api/generate data["response"]를 response_text로 추출하는지 확인
□ /api/chat 사용 시 message.content fallback 확인
□ data["thinking"]은 thinking_text로 별도 보존하고 response_text와 혼합하지 않음
□ top-level payload에 "think": false 명시 확인
□ stream=false 확인
□ num_predict=512 smoke 기준 적용 확인
□ response_field_used=response 확인
□ nonempty_response_text_rows = total_rows 확인
```

## Accepted Smoke-Test Snapshot

```text
□ top-k=3 run_id=20260523T_topk3_v2_table_safe_hybrid_thinkfalse_np512 PASS 확인
□ top-k=5 run_id=20260523T_topk5_v2_table_safe_hybrid_thinkfalse_np512 PASS 확인
□ collection lacp_docs_v2_table_safe_topk3 count=3503 확인
□ collection lacp_docs_v2_table_safe_topk5 count=3503 확인
□ top-k=3 thinking_present_rows=0 확인
□ top-k=5 thinking_present_rows=0 확인
□ top-k=3 nonempty_response_text_rows=9 확인
□ top-k=5 nonempty_response_text_rows=9 확인
□ A/B rag_injected=1, C rag_injected=0 확인
□ prompt_eval_count < 4096 확인
```

## Generation Termination / Truncation Validation

```text
□ done_reason 기록 확인
□ done_reason=stop 정상 종료로 분류
□ done_reason=length 발생 시 truncated_response=true 기록
□ smoke test에서는 warning으로 보관 가능하나 CR / Run B / CF 분석 투입 전 사전 정책 확정
□ truncated_response row를 causal evidence로 직접 해석하지 않음
```

## Thinking Output Control

```text
□ thinking=false 요청 여부 확인
□ response_text 내 <think> / reasoning trace 0건 확인
□ thinking_present_rows=0 확인
□ thinking_control_effective=true 확인
□ thinking trace 발견 시 해당 run failed_TR 처리
□ thinking trace 제거 후 재사용 금지
```

---

## Response Completeness Validation

```text
□ A/B/C 전 노드 response_text nonempty 확인
□ nonempty_response_text_rows = total_rows 확인
□ incomplete metric rows 0건 확인
□ Node C rag_injected=0 확인
□ timeout-induced empty output 0건 확인
```

# CR 진입 조건

```text
□ retrieval coherence validation 통과
□ canonical.md semantic preservation 확인
□ chunk semantic integrity 확인
□ corpus preprocessing artifact 없음
□ coherence failure unresolved 상태 아님
□ thinking_present_rows=0 확인
□ A/B/C 전 노드 nonempty response 확인
□ Node C rag_injected=0 확인
□ failed_TR unresolved 상태 아님
□ prompt truncation 0건 확인
□ table-safe chunking validation 통과
□ trigger sensitivity validation 통과
□ hybrid table exposure validation 통과
□ path_ready=true 및 generation_quality_ready=true 확인
□ top-level think=false 적용 확인
□ done_reason=length 처리 정책 확정
```

---

# Failure Handling

다음 항목 발생 시 즉시 CR 중단:

```text
□ retrieval ambiguity 급증
□ exception chunk retrieval 실패
□ table flattening semantic collapse
□ marker tagging corruption
□ metadata integrity failure
□ chunk scope leakage
□ thinking trace detected
□ timeout-induced empty output
□ missing node response
□ incomplete metric row
□ Node C RAG contamination
□ context-window saturation / prompt truncation
□ table_id 없는 table part 검색 결과
□ trigger assignment contamination 의심
□ response_text extraction failure
□ thinking control ineffective
□ done_reason=length unresolved
```

---

# 운영 원칙

```text
Corpus Validity
→ Retrieval Substrate Validity
→ Retrieval Validity
→ Calibration
→ Causal Inference
```

순서를 반드시 유지한다.

retrieval coherence가 확보되지 않은 상태에서는
CR / CR2 / Run B / CF Runs를 수행하지 않는다.
