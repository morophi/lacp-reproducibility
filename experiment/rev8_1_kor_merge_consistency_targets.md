# rev8.1 kor merge 정합성 점검 대상

대상 파일: `experiment/lacp_ijibc_rev8.1_kor_merge.docx`

기준 파일: `experiment/lacp_ijibc_rev8.1.docx`

위치 기준: MS Word COM으로 `lacp_ijibc_rev8.1_kor_merge.docx`를 열어 계산한 page/line이다. line은 해당 문단 또는 표 셀의 시작 line이다.

## 1. 구조 및 reference 확인

| 항목 | 결과 |
|---|---|
| DOCX 구조 | 정상 |
| 원본 문단 수 | 123 |
| merge 문단 수 | 123 |
| 원본 표 수 | 7 |
| merge 표 수 | 7 |
| References 시작 위치 | page 10, line 5 |
| reference list | 원본과 동일 |

## 2. 원문에 없는 해설성 문장

아래 항목은 원문 rev8.1에 직접 대응되는 문장이 없거나, 원문 의미를 넘어 해석/설명을 추가한 문장이다. 교수님 설명용 문장으로는 유용할 수 있으나, 논문 한글화본에서는 삭제하거나 중립적 학술문장으로 낮추는 것이 좋다.

| No. | 위치 | 현재 표현 | 점검 이유 | 권장 처리 |
|---:|---|---|---|---|
| 1 | page 1, line 34 | "다시 말해, RAG가 답변의 재료만 주는지, 아니면 모델의 판단 posture까지 흔드는지를 구분해야 한다." | 원문에 없는 해설 문장. `posture`, `흔드는지`가 구어적이다. | 삭제 또는 "이는 RAG가 응답 내용의 보강을 넘어 판단 구조에 영향을 주는지를 구분하는 문제이다." 정도로 중립화 |
| 2 | page 2, line 40 | "여기서 중요한 지점은 RAG의 '성능 향상' 여부가 아니라, RAG가 관찰 가능한 response architecture를 어느 방향으로 steering하는가이다." | 원문에 없는 강조 문장. `steering`과 `response architecture`가 과도하게 해설적이다. | 삭제 또는 "본 연구의 초점은 성능 향상이 아니라 관찰 가능한 응답 구조 변화이다." |
| 3 | page 3, line 7 | "이 가설은 'RAG가 더 좋은 답을 냈는가'가 아니라, 'RAG가 판단 구조의 방향성을 측정 가능하게 움직였는가'를 묻는다." | 원문에 없는 해석 문장. 문장 자체는 명확하지만 논문 번역본에는 설명이 추가된다. | 삭제 또는 footnote/교수님 설명용 메모로 분리 |
| 4 | page 3, line 13 | "이 구조가 있어야 RAG 효과와 SC-Protocol 효과가 한 덩어리로 뭉개지지 않는다." | 원문에 없는 설명. `뭉개지지 않는다`는 학술문체와 맞지 않는다. | "이 구조는 RAG 효과와 SC-Protocol 효과를 구분하기 위한 것이다." |
| 5 | page 6, line 31 | "즉, LMS는 신호의 시작점이지 최종 판정봉이 아니다." | 원문에 없는 비유적 표현. `판정봉`은 논문 문체에 부적합하다. | 삭제 또는 "따라서 LMS는 단독 판정 기준이 아니라 보조적 신호로 해석된다." |
| 6 | page 8, line 6 | "다시 말해, 이 설계의 요지는 단일 지표의 승리가 아니라 LMS, CDS, MA, CF-F가 같은 방향을 가리키는지를 보는 것이다." | 원문에 없는 해설 문장. `단일 지표의 승리`가 구어적이다. | 삭제 또는 "따라서 설계의 핵심은 여러 지표가 일관된 방향성을 보이는지 확인하는 데 있다." |

## 3. 구어적 또는 과잉 해설적 표현

아래 표현은 원문 의미를 크게 훼손하지는 않지만, 학술 한글 표현으로 다듬는 것이 좋다.

| No. | 위치 | 현재 표현 | 문제 유형 | 권장 처리 |
|---:|---|---|---|---|
| 1 | page 1, line 34 | "판단 posture까지 흔드는지" | 영어 혼합 + 구어적 은유 | "judgment direction과 confidence structure에 영향을 주는지" |
| 2 | page 2, line 40 | "response architecture를 어느 방향으로 steering" | 영어 동사형 은유 | "response structure가 어떤 방향으로 변화하는지" |
| 3 | page 3, line 13 | "한 덩어리로 뭉개지지 않는다" | 구어적 표현 | "서로 구분되어 추정될 수 있다" |
| 4 | page 6, line 31 | "최종 판정봉" | 비유적 표현 | "최종 판단 기준" 또는 "독립적 causal evidence" |
| 5 | page 8, line 6 | "단일 지표의 승리" | 구어적 표현 | "단일 지표의 우위" 또는 삭제 |
| 6 | page 8, line 36 | "trigger가 firing된 것인가" | 영어 동사형 접합 | "trigger가 발생한 것인가" 또는 "trigger가 작동한 것인가" |
| 7 | page 8, line 38 | "RAG를 injection하며" | 영어 명사/동사 혼합 | "RAG를 주입하며" 또는 "RAG injection을 수행하며" |

## 4. 영어 혼합 표현 정리 대상

아래 항목은 중심 개념어를 원어로 유지하는 방향과 충돌하지 않지만, 한국어 문장 안에서 어색한 접합 형태가 보인다. 개념어 자체는 유지하되 조사/서술어를 한국어로 정리하면 좋다.

| No. | 위치 | 현재 표현 | 점검 이유 | 권장 처리 |
|---:|---|---|---|---|
| 1 | page 2, line 4 | "operationalized된다" | 영어 동사형을 한국어 피동으로 직접 접합 | "operationalize된다"보다 "조작적으로 정의된다" 또는 "operationalize된다" 중 하나로 통일 |
| 2 | page 3, line 34 | "disabled한 상태" | 영어 형용/동사형 접합 | "비활성화한 상태" |
| 3 | page 5, line 7 | "logged된 뒤" | 영어 동사형 접합 | "logging된 뒤" 또는 "기록된 뒤" |
| 4 | page 4, line 22 | "archived되며" | 영어 동사형 접합 | "archive되며" 또는 "보관되며" |
| 5 | page 7, line 16 | "Post-CR2 modification은 허용되지 않는다." | 핵심 개념은 유지 가능하지만 문장 혼합도가 높음 | "CR2 이후의 modification은 허용되지 않는다." |
| 6 | page 10, line 4 | "External funding은 없었다." | 일반 문장은 한글화 가능 | "외부 연구비 지원은 없었다." |
| 7 | page 10, line 4 | "Authors는 AI-assisted..." | 일반 문장은 한글화 가능 | "저자들은 AI-assisted..." 또는 "저자들은 AI 보조..." |

## 5. 제목 및 caption 한글화 미완료 대상

아래 제목/표 caption은 원어 개념어를 유지하더라도 "전면 한글화" 기준에서는 한글 제목 + 원어 병기 형태로 정리하는 편이 좋다.

| No. | 위치 | 현재 표현 | 권장 처리 |
|---:|---|---|---|
| 1 | page 2, line 17 | "2.1 Retrieval-Augmented Generation" | "2.1 Retrieval-Augmented Generation (RAG)" 유지 가능. 단 전면 한글화라면 "2.1 Retrieval-Augmented Generation (RAG)의 개념" |
| 2 | page 2, line 25 | "2.2 LLM Confidence Measurement" | "2.2 LLM Confidence Measurement (LLM 신뢰도 측정)" |
| 3 | page 3, line 3 | "3.1 Research Hypothesis" | "3.1 Research Hypothesis (연구 가설)" |
| 4 | page 3, line 12 | "3.2 LACP and SC-Protocol" | "3.2 LACP and SC-Protocol" 유지 가능. 단 병기하려면 "(LACP와 SC-Protocol)" 추가 |
| 5 | page 3, line 21 | "3.3 Experimental Architecture" | "3.3 Experimental Architecture (실험 아키텍처)" |
| 6 | page 4, line 3 | "3.4 Experimental Run Structure" | "3.4 Experimental Run Structure (실험 실행 구조)" |
| 7 | page 4, line 4 | "Table 2. Experimental Run Structure" | "Table 2. Experimental Run Structure (실험 실행 구조)" |
| 8 | page 5, line 15 | "Table 2A. Rev. 8 Control Policy 이전 Thermal-only Direct Inference Probe" | "Table 2A. Rev. 8 Control Policy 이전 Thermal-only Direct Inference Probe (열 전용 직접 추론 사전 탐색)" |
| 9 | page 5, line 39 | "Table 3. LMS Selection Rationale" | "Table 3. LMS Selection Rationale (LMS 선택 근거)" |
| 10 | page 6, line 20 | "Table 4. LMS Primary Test Statistics" | "Table 4. LMS Primary Test Statistics (LMS 주요 검정 통계량)" |
| 11 | page 6, line 39 | "Table 5. Modality Analysis Classification" | "Table 5. Modality Analysis Classification (Modality Analysis 분류)" |
| 12 | page 9, line 2 | "Table 6. Counterfactual Conditions" | "Table 6. Counterfactual Conditions (Counterfactual 조건)" |

## 6. 표 내부 한글화 정리 대상

표 내부는 원어 개념어를 유지해야 하는 부분이 많지만, header와 일반 설명은 한글 병기 또는 한글 서술로 정리하는 것이 좋다.

| No. | 위치 | 현재 표현 | 권장 처리 |
|---:|---|---|---|
| 1 | page 3, line 27, Table 1 row 1 | "Node / Role / Intervention Level / Trigger Monitoring" | "Node / Role / Intervention Level / Trigger Monitoring" 유지 가능하나, 전면 한글화라면 한글 병기 |
| 2 | page 3, line 28, Table 1 row 2 col 3-4 | "Maximum / Subject to monitoring" | "Maximum (최대) / monitoring 대상" |
| 3 | page 3, line 29, Table 1 row 3 col 3-4 | "Intermediate / Subject to monitoring" | "Intermediate (중간) / monitoring 대상" |
| 4 | page 3, line 30, Table 1 row 4 col 2-4 | "Baseline - Concurrent Control Observation / None (fixed) / Excluded" | "Baseline - Concurrent Control Observation (동시 통제 관찰) / None (fixed, 없음) / Excluded (제외)" |
| 5 | page 4, line 6, Table 2 row 1 | "Phase / Name / Purpose / N" | "Phase / Name / Purpose / N" 유지 가능. 필요 시 "단계 / 명칭 / 목적 / N" 병기 |
| 6 | page 4, line 8, Table 2 row 2 col 2-3 | "Test Run / PDF canonicalization..." | "Test Run (TR) / PDF canonicalization, chunking..."처럼 약어와 목적 정리 |
| 7 | page 4, line 10, Table 2 row 3 col 2-3 | "Calibration Run / Inter-node hardware/runtime variance 측정" | "Calibration Run (CR) / inter-node hardware/runtime variance 측정"으로 약어 병기 |
| 8 | page 4, line 11, Table 2 row 4 col 2-3 | "Calibration Run 2 / Natural metric variation..." | "Calibration Run 2 (CR2) / natural metric variation 측정..." |
| 9 | page 4, line 13, Table 2 row 5 col 2-3 | "Main Experiment / RAG pure effect..." | "Main Experiment (Run B) / RAG pure effect..." |
| 10 | page 4, line 15, Table 2 row 6 col 1-4 | "CF Runs / Counterfactual Conditions / ... / 5 each" | "CF Runs / Counterfactual Conditions / ... / 각 5회" |
| 11 | page 5, line 16, Table 2A row 1 | "Initial / Peak / End before cooldown / 10-sec cooldown / Drop" | "Initial (초기) / Peak (최고) / End before cooldown (cooldown 전 종료) / 10-sec cooldown / Drop (감소)" |
| 12 | page 5, line 40, Table 3 row 1 | "Dimension / Justification" | "Dimension (차원) / Justification (근거)" |
| 13 | page 6, line 1, Table 3 row 2 | "Theoretical basis" | "Theoretical basis (이론적 근거)" |
| 14 | page 6, line 4, Table 3 row 3 | "Korean morphological token dilution" | "Korean morphological token dilution (한국어 형태소 token dilution)" |
| 15 | page 6, line 7, Table 3 row 4 | "Measurement objective alignment" | "Measurement objective alignment (측정 목적 정합성)" |
| 16 | page 6, line 21, Table 4 row 1 | "Variable / Formula / Causal Interpretation" | "Variable / Formula / Causal Interpretation" 유지 가능하나 한글 병기 권장 |
| 17 | page 6, line 26, Table 4 row 4 col 3 | "Auxiliary evidence only: confidence-accuracy independence" | "Auxiliary evidence only: confidence-accuracy independence (보조 증거: confidence와 accuracy의 독립성)" |
| 18 | page 6, line 28, Table 4 row 5 col 3 | "Secondary comparison: RAG-only intervention..." | "Secondary comparison (2차 비교): RAG-only intervention..." |
| 19 | page 6, line 40, Table 5 row 1 | "Type / Classification Criteria... / Variable" | "Type (유형) / Classification Criteria... (분류 기준) / Variable" |
| 20 | page 9, line 3, Table 6 row 1 | "CF Condition / Design / Causal Contribution / N" | "CF Condition / Design / Causal Contribution / N" 유지 가능하나 한글 병기 권장 |
| 21 | page 9, line 4, Table 6 row 2 col 3 | "Direct verification: content change -> response change" | "Direct verification: content change -> response change (직접 검증: content 변화 -> response 변화)" |
| 22 | page 9, line 6, Table 6 row 3 col 3 | "Baseline: RAG-absent counterfactual comparison" | "Baseline: RAG-absent counterfactual comparison (RAG 부재 counterfactual 비교)" |
| 23 | page 9, line 8, Table 6 row 4 col 2-3 | "Previous-version policy document... / strongest evidence" | "Previous-version policy document... / H1에 대한 strongest evidence"는 유지 가능하나 한글 병기 권장 |
| 24 | page 9, line 10, Table 6 row 5 col 3 | "Injection timing effect + partial reverse causality resolution" | "Injection timing effect + partial reverse causality resolution (injection timing 효과와 부분적 reverse causality 해소)" |
| 25 | page 9, line 12, Table 6 row 6 col 2-3 | "User queries의 internal contextual cues... / External attribution confirmation..." | 문장 구조를 한국어 중심으로 재정리 |
| 26 | page 9, line 16, Table 6 row 7 col 2-3 | "Uniformly sampled... / Direct reverse causality refutation..." | 핵심 개념은 유지하되 한글 병기 권장 |

## 7. 우선 수정 권장 순서

1. 원문에 없는 해설성 문장 6개를 먼저 삭제 또는 중립화한다.
2. 구어적 표현 7개를 학술문체로 정리한다.
3. 영어 동사형 접합 표현을 통일한다. 예: `operationalized된다`, `disabled한`, `logged된`, `archived되며`, `injection하며`.
4. 표 caption과 header는 한글 병기 방식으로 통일한다.
5. References는 현재 상태를 유지한다.

