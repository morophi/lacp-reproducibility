# 실제 입력·응답·통제문구 대조

## Run B 6회차

대상 실행은 `run_b_neo_excute_#6_20260626T095614KST`이며 DB 실행 ID는 37입니다. 대조 실행은 `run_b_neo_excute_#1_20260625T174811KST`입니다. 전체 30회를 먼저 최빈 해시와 비교한 뒤 차이가 집중된 실행을 대조합니다.

- 2,700행 중 최빈 응답과 다른 25행은 모두 6회차 A의 6–30턴입니다.
- A의 전체 응답열은 29회가 같고 1회가 다릅니다. B와 C의 각 전체 응답열은 30회가 같습니다.
- 6턴 A는 기록된 입력 해시가 같은 상태에서 응답이 다릅니다.
- 7–30턴 A는 응답뿐 아니라 입력 해시도 다릅니다.
- 검색 청크 ID·순서와 RAG 문맥 문자 수는 비교 실행 간 같습니다.
- 최근 3턴 이력을 사용하므로 6턴 응답 자체가 30턴까지 직접 남아 있었다는 뜻은 아닙니다.

[턴·노드별 입력/응답/문구 대조 CSV](../results/published/run_b_repetition6_trace.csv)와 [비최빈 응답 목록](../results/published/run_b_nonmodal_responses.csv)을 제공합니다.

| RBC 적용 턴 | 일반 실행 문구 길이 | 6회차 문구 길이 | 차이 |
|---|---:|---:|---|
| 8 | 652 | 614 | 발동 사유 문자열 |
| 20 | 650 | 613 | 발동 사유 문자열 |
| 25 | 614 | 614 | 같은 문구·해시 |

8·20턴의 차이는 발동 사유이며 확인요건·책임경계와 근거 청크 설정은 같습니다. [실제 문구와 payload](../results/published/run_b_policy_examples.json)에서 확인할 수 있습니다. 최초 응답 차이의 연산 원인이나 이력의 독립적 인과효과는 식별하지 않았습니다.

## CF-C와 CF-E

| 항목 | CF-C | CF-E |
|---|---|---|
| 채택 실행 / A 적용 행 | 5 / 150 | 5 / 150 |
| 근거 충분성 표시 | insufficient | sufficient |
| 확인 항목 | policy_basis, applicant_facts, no_final_determination | applicant_facts, local_procedure, benefit_history |
| 근거 청크 | 0 | 3 |
| 통제문구 길이 | 457 | 643 |

[CF-C 원문](../results/published/cf_c_policy_block.txt), [CF-E 원문](../results/published/cf_e_policy_block.txt), [비교표](../results/published/cf_c_e_policy_comparison.csv)를 제공합니다. 충분성 표시는 반환 청크 수에서 만들어지며 내용 적합성을 평가하지 않습니다. 이 비교에서는 자료와 실제 통제 내용이 함께 달라집니다.

## 모든 적용 문구와 입력 해시

[applied_policy_blocks.jsonl](../results/published/applied_policy_blocks.jsonl)은 저장된 정책 payload를 당시 정책 렌더러로 재구성한 문구입니다. 문구 해시는 로그의 `sc_block_hash`와 대조했습니다. 원문 HTTP 요청을 회수한 파일은 아닙니다.

입력 전체 재구성은 [replay_execution.py](../analysis/replay_execution.py)가 시나리오, 검색 문맥, 시스템 프롬프트 버전과 경로별 최근 이력을 합쳐 수행합니다. 최종 점검은 [execution_chain_summary.json](../results/published/execution_chain_summary.json)을 보십시오.
