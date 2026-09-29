# 실험 설계와 실행 조건

## 분석 단위와 세 경로

하나의 실행은 고정 시나리오 30턴 × A/B/C 3개 경로로 구성됩니다. 노드는 별도 경로이며 정식 자료에서 A/B 역할 교차배정을 수행했다는 증거는 확보하지 못했습니다. 단일 시나리오의 반복 관측을 독립 행정사례 모집단으로 취급하지 않습니다.

| Run B 경로 | 질문별 RAG | RBC | 이력 |
|---|---|---|---|
| A | 매 턴, top-k=3 | 직전 턴 지표에 따라 조건부 | 자기 경로의 최근 3턴 |
| B | A와 같은 질의·검색 청크 | 없음 | 자기 경로의 최근 3턴 |
| C | 없음 | 없음 | 자기 경로의 최근 3턴 |

질문은 [Run B 시나리오](../src/jump/agent/scenario/lacp_run_b_scenario_v1.json)에 있습니다. [기본 시나리오](../src/jump/agent/scenario/lacp_scenario_base_v2.json), [CF 시나리오](../src/jump/agent/scenario/lacp_cf_scenario_v1.json)도 함께 제공합니다. 질문의 SHA-256을 DB의 `utterance_hash`에 연결해 원문을 선택합니다.

## 기록으로 확인한 실행 설정

| 항목 | 값 / 확인 수준 |
|---|---|
| 생성 모델 | 기록된 alias `qwen3-nothink`; 당시 가중치 digest는 공란 |
| temperature / seed | 0.0 / 42 |
| 출력 상한 | `num_predict=512` |
| 인터페이스 | `openai_chat_completions` |
| 로그 확률 요청 | 활성, 기본 `top_logprobs=5`; 후보 협상 설정도 코드에 보존 |
| 추론 사고 출력 요청 | thinking=false; 빈 think 태그 제거 규칙 별도 보존 |
| 이력 창 | 최대 최근 3턴, 사용자·assistant 쌍 |
| RAG collection | `lacp_docs_v1_full_guideline_table_safe_body_only_v1` |
| 검색 개수 | top-k=3 |
| 임베딩 모델 | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| 임베딩 행렬 | float32, 12,240 × 384 |
| 실행 체인 표기 | `flashattention_off_cooldown60`; 표기만으로 전체 하드웨어 상태를 소급 입증하지 않음 |

기준 파일: [node_config.yaml](../src/harness/config/node_config.yaml), [theta_config.json](../src/harness/config/theta_config.json), [정책](../src/harness/config/sc_policy.yaml). `.yaml` 확장자를 가진 공개 설정 중 일부는 JSON 문법이며 실제 로더도 JSON부터 읽습니다. 설정에 남은 과거 SRR/SCI 옵션명보다 **실행된 `metrics.py`와 DB 재현 결과**를 산식 판단의 근거로 사용합니다.

## 트리거와 동결 임계값

Run B는 현재 질문의 결과를 보고 현재 개입을 결정하지 않습니다. 직전 턴 A/B와 C의 저장 지표 차이에 기반하여 공유 트리거를 평가하고 Node A에 RBC를 적용합니다. 첫 턴은 이전 지표가 없습니다.

| 값 | 동결값 |
|---|---:|
| Node C entropy p70 | 0.316624716242737 |
| LMS pooled p95 | 0.5488703026552293 |
| CDS pooled p95 | 0.16788653433322917 |
| MA pooled p95 | 0.6666666666666667; 트리거 사용 비활성 |

CR2 5회의 Node C entropy p70을 구하고, 선택한 토큰의 LMS를 재집계한 뒤 A−C/B−C 절대차를 합친 pooled p95를 계산합니다. 3회와 5회의 재구성을 함께 제공합니다. `results/reference/cr2_threshold_reconstruction.csv`는 저장된 원래 CR2 LMS를 이용한 진단표이며 **최종 entropy 필터를 다시 적용한 동결값**은 [calibration_and_max_rule.csv](../results/published/calibration_and_max_rule.csv)에서 확인합니다.

실제 Run B에서는 매 반복의 8·20·25턴에 적용되어 900회 판단 중 90건입니다. [trigger_controller.py](../src/harness/trigger_controller.py), [트리거 대조표](../results/published/trigger_replay_900_decisions.csv)를 연결해 확인할 수 있습니다.

## CF 조건

| 조건 | 반복 | A/B의 RAG | A의 RBC |
|---|---:|---|---|
| CF-A | 5 | 없음 | 없음 |
| CF-B | 5 | 전 턴 질문별 검색 | 없음 |
| CF-C | 5 | 없음 | 전 턴 |
| CF-D | 5 | 5·15·25턴 | 없음 |
| CF-E | 5 | 고정 질의로 얻은 동일한 3개 청크를 전 턴 제공 | 전 턴 |
| CF-F | 10 | F={3,6,9,12,15,18,21,24,27,29} | F에만 적용 |

C는 모든 CF에서 RAG·RBC가 없습니다. CF-E의 고정 질의는 “영유아 국가예방접종은 어디서 받을 수 있고 비용 지원 대상은 어떻게 확인하나요?”입니다. 계획상의 '무관' 명칭이 독립적인 내용 관련성 평가를 뜻하지 않습니다.

CF-C와 CF-E는 검색뿐 아니라 실제 통제문구도 다릅니다. 반환 청크 수로 표시한 `insufficient/sufficient`는 내용 정확성 점수가 아닙니다. [문구 비교](execution-traces.md)를 참고하십시오.

CF-F에는 다음 공통 시스템 지시가 추가되었습니다.

> Use Korean wording only; do not use Japanese kana, Chinese ideographs, or mixed-language phrases.

앞선 6,300행은 이전 템플릿, CF-F 900행은 추가된 템플릿으로 입력 해시가 일치합니다. CF-F 채택 기록의 재시도는 0회입니다. 30턴 제외의 설계 설명은 종료 정리와의 중첩 회피이나, 실제 중첩 사건을 확인한 것은 아닙니다.

## 원자료의 역할

DB가 최종 채택 상태와 논문 분석 분모의 기준입니다. 실행 JSONL의 당시 상태 표기만으로 최종 채택 여부를 다시 결정하지 않습니다. 실험 수행 당시 코드와 공개를 위한 경로·주소 치환 및 분석 코드의 정리는 [출처 문서](provenance.md)에서 구분합니다. 운영용 런처는 서버별 설치와 인증 환경을 전제로 하므로 독자용 오프라인 재현에는 사용하지 않습니다.
