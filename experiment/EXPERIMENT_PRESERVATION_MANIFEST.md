# LACP Experiment Preservation Manifest

생성일: 2026-05-26

이 폴더는 `C:\Users\morophi\OneDrive\문서\lacp\experiment` 원본 보관 폴더를 기준으로
실험 실행과 검증에 반드시 필요한 파일만 선별해 모은 보존 번들이다.

## Selection Rules

- 같은 문서 계열에 여러 버전이 있으면 가장 최신 버전 번호를 우선한다.
- 같은 파일명이 원본 보관 폴더와 현재 프로젝트 폴더에 모두 있고, 프로젝트 폴더 파일이 이후 정책 반영으로 더 최신이면 프로젝트 폴더의 최신본을 보존한다.
- 실험 입력, 실행 조건, Harness 정책, DB 적재 스키마, 검증 스크립트, 인프라 증거, 최종 논문 원고에 직접 연결되지 않는 구버전 초안은 제외한다.
- 구버전은 삭제하지 않고 원본 보관 폴더에 그대로 두며, 이 폴더에는 실행과 검증에 필요한 최신 기준본만 복사한다.

## Preserved Files

| File | Source | Preservation reason |
|---|---|---|
| `experiment_conditions_v2.md` | project latest | CR/CR2/Run B 정의와 scenario hash 정책이 최신으로 정리된 실험 조건 명세 |
| `harness_file_structure_and_db_flow_rev2.md` | project latest | Harness 실행 순서, DB 적재 흐름, eligibility separation 반영본 |
| `HARNESS_POLICY.md` | project latest | analysis/trigger/history eligibility와 smoke/formal 해석을 고정하는 Harness 정책 문서 |
| `20260525_harness_eligibility_policy_revision.md` | project latest | 정책 변경 사유와 반영 이력을 추적하기 위한 revision note |
| `lacp_scenario_base_v2.jsonl` | project latest | 30턴 user-only canonical scenario 입력 최신본 |
| `민원노드_발화_30선_v2.md` | source latest | scenario pool의 원문, 분류, 출처 설명 최신본 |
| `lacp_experiment_guideline_rev5.4.md` | project latest | 실험 실행 가이드 최신 revision; full-guideline retrieval candidate freeze gate 반영 |
| `lacp_node_checklist_v10.3.md` | source latest | 노드 준비와 검증 체크리스트 최신 revision |
| `LACP_RAG_Embedding_and_tmux_Operation_Guide.md` | source | RAG embedding 및 tmux 운영 절차 문서 |
| `RAG_체크리스트_준비완료.md` | source | RAG 준비 완료 상태 확인 문서 |
| `run_exam_test.py` | source | 실험/검증용 실행 스크립트 보존본 |
| `lacp_harness_lms_kit.tar.gz` | source | Harness/LMS 관련 압축 아티팩트 보존본 |
| `lacp_db_schema.sql` | project latest | MariaDB dblog 전체 스키마 기준본 |
| `20260525_add_eligibility_separation_fields.sql` | project latest | eligibility separation 필드 추가 migration |
| `lacp_infra_v6_final.pdf` | source latest | 인프라 구조 증거 PDF |
| `lacp_infra_v6_final_1.png` | source latest | 인프라 구조 이미지 증거 |
| `lacp_ijibc_rev7.8.docx` | project latest | 논문 원고 최신 revision; retrieval freeze gate와 body-only retrieval substrate 설명 반영 |

## Excluded Superseded Versions

- `harness_file_structure_and_db_flow.md`는 `harness_file_structure_and_db_flow_rev2.md`로 대체한다.
- `lacp_scenario_base.jsonl`은 `lacp_scenario_base_v2.jsonl`로 대체한다.
- `민원노드_발화_30선.md`는 `민원노드_발화_30선_v2.md`로 대체한다.
- `lacp_experiment_guideline_rev4.md`, `rev5.md`, `rev5.1.md`, `rev5.2.md`, `rev5.3.md`는 `rev5.4.md`로 대체한다.
- `lacp_node_checklist_v9_6.md`, `v10.md`, `v10.1.md`, `v10.2.md`는 `v10.3.md`로 대체한다.
- `lacp_ijibc_rev6.docx`부터 `rev7.7` 계열은 `lacp_ijibc_rev7.8.docx`로 대체한다.
