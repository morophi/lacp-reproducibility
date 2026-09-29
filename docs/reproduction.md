# 독자용 재현 절차

## 1. 기본 재현: 저장된 실험 자료에서 표·산식·입력 확인

검증 환경은 Python 3.12.14, NumPy 2.3.5, pandas 2.2.3입니다. Python 3.12 가상환경에 [requirements-analysis.txt](../requirements-analysis.txt)를 설치한 뒤 저장소 루트에서 실행합니다.

```bash
python analysis/reproduce.py
```

실행 위치가 달라도 프로그램 자체 위치에서 저장소 루트를 찾습니다. 분석용 의존성 설치 이후에는 네트워크를 사용하지 않습니다. DB·실험 서비스에 연결하거나 기존 실험을 재실행하지 않습니다.

| 순서 | 프로그램 | 수행 내용 |
|---|---|---|
| 1 | `prepare_data.py` | 원자료 공개 파일·내용 해시 검증, CSV/JSONL 압축 해제 |
| 2 | `reaggregate.py` | 채택 실행 필터, 주요·턴별·CF 대비, 반복성, 실제 배정 집계 |
| 3 | `replay_metrics.py` | MA/SRR/SCI 원문 재계산, LMS 저장 배열 대조 |
| 4 | `replay_execution.py` | 로그/DB 대조, 정책문구·입력 해시, 트리거, 임계값·민감도 |
| 5 | `rebuild_reference.py` | 12,240개 임베딩에서 참조 생성, 보관된 CDS 재계산 결과 대조 |
| 6 | `trace_paths.py` | Run B 6회차와 CF-C/E의 실제 실행 경로 대조 |
| 7 | `verify_results.py` | 주요 기준표 7개 및 전수 검증 통과 여부 확인 |

완료 후 `results/reproduced/verification.json`의 `status`가 `PASS`여야 합니다. 수치 비교는 절대오차 10⁻¹²를 사용하며 결과표 비교에는 같은 크기의 상대오차도 적용합니다. 실패를 무시한 상태에서 재현 완료로 판단하지 마십시오.

이번 공개본의 실행 결과는 [results/published](../results/published)에 보존합니다. 사용자가 재실행하는 `results/reproduced/`는 별도 폴더이며 Git에서 제외됩니다. 입력과 결과를 바꾸지 않은 분석은 같은 과학적 수치를 제공해야 하지만 환경 식별자 같은 메타데이터까지 동일할 필요는 없습니다.

`src/harness/run_unit_tests_no_pytest.py`는 별도의 옛 운영 테스트이며 현재 동결 설정에서 5개가 실패합니다. [상세 상태](archived-tests.md)를 참고하고 기본 재현 명령의 통과와 혼동하지 마십시오.

## 2. 큰 파일을 읽는 방법

CSV와 JSONL은 Git 파일 제한을 피하고 중복 텍스트를 효율적으로 저장하기 위해 gzip 압축했습니다. 일반 Git clone에 포함되며 Git LFS 인증이나 별도의 유료 다운로드는 필요하지 않습니다.

```python
import pandas as pd
runs = pd.read_csv('data/db/experiment_runs.csv.gz', keep_default_na=False)
accepted = runs[(runs.run_mode == 'formal') & (runs.acceptance_status == 'accepted')]
print(accepted.groupby('stage').size())
```

DB와 로그의 운영 주소는 역할 이름으로 치환되었습니다. `provenance/artifacts.json`의 원본 해시와 공개 내용 해시가 다를 수 있으며 정상입니다. 공개 원자료의 해시 검증은 `published_content_sha256`, 압축 파일 자체는 `stored_sha256`를 사용합니다.

## 3. CDS 응답 임베딩을 새로 실행하는 별도 단계

기본 재현은 원천 행렬에서 **참조 벡터를 새로 생성**하지만, 응답 399개에 대한 임베딩은 **9월 27일 재실행 기록을 대조**합니다. 응답 임베딩까지 재실행하려면 보관 기록과 일치하는 모델 파일을 별도로 확보해야 합니다.

- 모델: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 당시 재검증에 사용한 캐시 snapshot: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- 파일별 SHA-256: [cds_remote_replay.json](../evidence/audit_20260927/cds_remote_replay.json)의 `cached_model_files`
- 9월 27일 관측 환경: Python 3.11.2, torch 2.11.0+cpu, NumPy 2.4.4, sentence-transformers 5.4.1

위 모델 라이브러리 환경을 별도로 준비하고 모델 디렉터리를 지정합니다. 프로그램은 모델 파일 해시를 확인하고 오프라인 CPU 실행만 사용합니다.

```bash
python analysis/prepare_data.py
python analysis/replay_cds.py --model-path /absolute/path/to/model-snapshot
```

이 별도 프로그램은 새 공개본 준비 중 로컬 Mac에서 모델을 내려받아 실행하지 않았습니다. 기존 노드의 9월 27일 점수 기록과 기본 재현의 대조는 검증했습니다. 다른 플랫폼·라이브러리에서 10⁻¹² 오차 기준이 유지된다고 사전에 보장하지 않습니다. 당시 생성 모델 digest 문제와 이 **임베딩 모델**의 보관 파일 식별을 구분하십시오.

## 4. 실제 LLM 응답을 다시 생성하는 재실험

`src/`의 운영 코드는 원 실험 구현을 공개하기 위한 것입니다. 독자용 기본 명령은 운영 런처를 실행하지 않습니다. 새로운 생성 실험은 다음 항목을 별도로 준비해야 합니다.

1. A/B/C 추론 서비스와 당시 모델 가중치·런타임을 식별합니다. 현재 자료에는 당시 생성 모델 digest가 없으므로 같은 alias만으로 동일 가중치를 보장할 수 없습니다.
2. 본인의 환경에 맞춰 예시 호스트·경로·DB 자격 증명을 설정합니다. 운영 코드에는 `/home/lacp` 등 치환된 경로가 남아 있습니다.
3. `src/dblog/schema_final.sql`의 구조를 검토하여 별도 실험 DB를 준비합니다. 기존 DB 자료를 새 응답으로 덮어쓰지 않습니다.
4. `data/rag/`의 동결 자료와 `src/rag/` 코드를 이용해 검색 환경을 준비합니다. 제공 적재 코드의 기본값은 다른 코퍼스를 가리킬 수 있으므로 동결 collection·버전을 명시합니다.
5. `src/harness/historical/prompt_builder_pre_cf_f.py`에 있는 이전 공통 템플릿과 현행 CF-F 템플릿 차이를 조건에 맞게 반영합니다. 현재 파일 하나를 모든 조건에 적용하면 원 입력이 달라집니다.
6. 새 실행 ID와 별도 출력 경로를 사용하고, seed/temperature 외 하드웨어·라이브러리·모델 파일 해시를 기록합니다.

오프라인 결과 재현의 성공을 새 LLM 생성의 동일성 보장으로 해석하지 않습니다. 위 목록은 미확보 환경을 만들어 냈다는 선언이 아닙니다.
