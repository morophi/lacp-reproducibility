# 논문–원자료–처리 코드–결과 대응표

대응 기준은 국문 「공공부문 생성형AI의 일관성과 책임성확보를 위한 운영체계 연구」 REV9(2026-09-29)입니다. 기술 원고 `LACP_FINAL_0927_REV2`도 같은 80회·7,200행에 기초합니다. 다른 원고 버전에서는 표 번호가 달라질 수 있으므로 제목과 내용으로도 확인하십시오.

아래의 `data/db/*.csv.gz`는 [압축 해제 절차](reproduction.md) 후 `build/db/csv/`에서 읽을 수 있습니다. `results/published/`는 이번 공개본에서 실제로 재실행한 결과입니다.

| 논문 위치 / 주장 | 원자료·구현 | 처리 코드 | 읽을 결과와 한계 |
|---|---|---|---|
| 표 1: A/B/C 조건 | [노드 설정](../src/harness/config/node_config.yaml), payload·intervention DB | [reaggregate.py](../analysis/reaggregate.py) | [routing.csv](../results/reference/routing.csv); 적용 행 수와 턴, 물리 노드 교차배정 아님 |
| 표 2: 지표의 의미 | [metrics.py](../src/harness/metrics.py), 응답·metric DB | [replay_metrics.py](../analysis/replay_metrics.py) | [지표 산식](metrics.md), [전수 대조 요약](../results/published/metric_replay_summary.json); 정확성 척도로 확대하지 않음 |
| 표 3: Run B 주요 대비 | turn_node_logs, metric_logs, experiment_runs | [reaggregate.py](../analysis/reaggregate.py) | [main_contrasts.csv](../results/reference/main_contrasts.csv); CDS 부호 반전, 서로 다른 대비 분모 주의 |
| 표 4: 8·20·25턴 대비 | 같은 Run B DB, 개입 턴 90쌍 | [reaggregate.py](../analysis/reaggregate.py) | [trigger_contrasts.csv](../results/reference/trigger_contrasts.csv); 30회 평균이며 독립 사례 효과 아님 |
| IV.1: 응답 99.07% 일치 | response_text, response_hash | [trace_paths.py](../analysis/trace_paths.py) | [path_trace_summary.json](../results/published/path_trace_summary.json), [response_reproducibility.csv](../results/reference/response_reproducibility.csv); 행 단위 최빈 일치율 |
| IV.1·부록 2: Run B 6회차 A 분기 | 30회 실행 JSONL, payload DB | [trace_paths.py](../analysis/trace_paths.py) | [90개 턴·노드 대조](../results/published/run_b_repetition6_trace.csv), [비최빈 25행](../results/published/run_b_nonmodal_responses.csv); 최초 원인·이력의 독립 효과 미식별 |
| IV.3: 25턴 질문·응답 인용 | [Run B 시나리오](../src/jump/agent/scenario/lacp_run_b_scenario_v1.json), response_text | [reaggregate.py](../analysis/reaggregate.py) | [응답별 빈도·구성요소](../results/reference/turn25_responses_and_components.csv), [SCI 계산](../results/published/sci_turn25_explained.json); 사후 선택 설명 사례 |
| IV.3: 8·20턴 문구의 실행 간 차이 | sc_policy_payload·trigger reason | [trace_paths.py](../analysis/trace_paths.py) | [실제 문구 예시](../results/published/run_b_policy_examples.json); 발동 사유 차이와 정책 확인요건 차이를 구분 |
| IV.4·부록 1: CF-C/E 실제 확인요건 | 채택 각 5회 로그, 정책 렌더러 | [trace_paths.py](../analysis/trace_paths.py) | [CF-C/E 비교](../results/published/cf_c_e_policy_comparison.csv), [CF-C 문구](../results/published/cf_c_policy_block.txt), [CF-E 문구](../results/published/cf_e_policy_block.txt) |
| 표 A1: CF 조건·배정 | counterfactual config, payload DB | [reaggregate.py](../analysis/reaggregate.py) | [routing.csv](../results/reference/routing.csv), [cf_contrasts.csv](../results/reference/cf_contrasts.csv); 조건별 이력 및 CF-F 언어 지시 차이 |
| 부록 2: 입력 재구성 | 145개 검색 문맥, 시나리오, 정책, 이력 | [replay_execution.py](../analysis/replay_execution.py) | [7,200행 실행 요약](../results/published/execution_chain_summary.json); 실제 HTTP 원본 회수가 아님 |
| 부록 2: 동결 임계값·민감도 | CR2 로그, theta_config | [replay_execution.py](../analysis/replay_execution.py) | [보정값](../results/published/calibration_and_max_rule.csv), [민감도](../results/published/trigger_sensitivity_all_decisions.csv); 저장 이력을 고정한 사후 배정 비교 |
| 부록 2: CDS 참조와 재계산 | 원천 행렬, 참조, 9월 27일 모델 재계산 기록 | [rebuild_reference.py](../analysis/rebuild_reference.py) | [참조·점수 대조](../results/published/reference_and_cds_evidence.json); 기본 재현은 새 응답 임베딩 추론 아님 |
| 표 5: 관측과 운영 기능 연결 | 위의 기술 관측 및 논문 이론 | 원고의 논증 | 정책설계 해석이며 실험 집계표로 자동 도출되는 인과적 결론 아님 |
| 표 6·7·8: 운영 대안·권한·도입 단계 | 원고의 문헌·제도적 논의 | 원고의 논증 | 대안의 실측 순위, 조직 성과 또는 시민 효과를 검증한 자료 없음 |

## 분석 대상 실행을 직접 확인하기

[실행 목록](../results/published/accepted_runs.csv)은 최종 DB의 formal+accepted 80회입니다. [전체 실행 상태별 집계](../results/published/run_inclusion_summary.csv)와 함께 확인하면 제외된 실행이 분모에서 빠지는 이유를 검토할 수 있습니다.

원자료의 기본키는 `experiment_runs.id → turn_node_logs.experiment_run_id`, 응답별 상세는 `turn_node_logs.id → *_logs.turn_node_log_id`입니다. [데이터 사전](data-dictionary.md)에 관계와 주의사항을 정리했습니다.
