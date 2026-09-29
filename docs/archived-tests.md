# 보관된 운영 단위테스트의 상태

`src/harness/tests/`와 `run_unit_tests_no_pytest.py`는 노드에서 수집한 기존 파일입니다. 공개 준비 중 해당 러너를 Python 3.12.14에서 실행한 결과 **50개 통과, 5개 실패**였습니다. 논문 재현 결과와 구분하여 기록합니다.

| 실패 테스트 | 확인된 불일치 |
|---|---|
| `test_lms_low_confidence_triggers` | `d_lms=0.1`로 발동을 기대하지만 동결 theta_lms는 약 0.54887 |
| `test_ma_weak_assertion_triggers` | MA 발동을 기대하지만 현재 정책은 MA 트리거 비활성 |
| `test_formal_a_crosses_threshold_shared_trigger` | `d_lms=0.1`로 발동을 기대하는 같은 임계값 불일치 |
| `test_missing_lms_does_not_block_cds_trigger` | 예상 사유 문자열은 `d_cds>theta_cds`, 실제 구현은 절대차 `abs(d_cds)>theta_cds` 표기 |
| `test_legacy_rev11_mode_still_requires_explicit_fixed_rag_exposure` | 레거시 fixture에 현재 실행 경로가 요구하는 `trigger_controller`가 없어 AttributeError 발생 |

실패를 숨기기 위해 테스트나 원 실험 코드를 바꾸지 않았습니다. 옛 테스트 전체가 통과한다고 주장하지 않으며, 배포에 사용할 경우 별도의 유지보수 작업이 필요합니다. 실행 결과는 [archived_unit_tests.json](../results/published/archived_unit_tests.json)에 보존합니다.

논문 자료의 전수 검증은 `analysis/reproduce.py`가 수행합니다. 현재 데이터 7,200행의 지표·입력 및 900회 트리거를 확인하는 이 절차는 통과했습니다. [verification.json](../results/published/verification.json)을 참고하십시오.
