# 데이터 사전과 관계

현재 DB는 MariaDB의 `lacp_db_final`이며 6개 기본 테이블을 읽기 전용 일관 스냅샷으로 수집했습니다. 뷰의 중복 데이터와 운영 자격 증명은 공개 패키지에 포함하지 않습니다. 전체 컬럼 목록은 [db_columns.csv](../provenance/db_columns.csv), 타입·키·제약은 [schema_final.sql](../src/dblog/schema_final.sql)에 있습니다.

| 테이블 | 행 수 | 기본 역할 / 연결 |
|---|---:|---|
| experiment_runs | 96 | 실행 ID, 조건, 단계, 최종 채택 상태, 설정·시나리오 해시 |
| turn_node_logs | 8,568 | 실행·턴·노드별 응답 원문, 응답 해시, 모델 alias·생성 옵션 |
| metric_logs | 8,568 | 응답별 LMS/CDS/MA/SRR/SCI와 구성요소·품질 상태 |
| payload_audit_logs | 8,568 | 입력·payload 해시, 문맥·통제문구 길이, 이력 범위 |
| intervention_logs | 8,568 | RAG/RBC 적용 여부, 사유·임계값·정책 payload |
| rag_retrieval_logs | 3,382 | 검색을 기록한 응답의 질의 해시, 청크 ID·순서·길이·방법 |

## 조인과 필터

```text
experiment_runs.id
  └─ turn_node_logs.experiment_run_id
       └─ turn_node_logs.id
            ├─ metric_logs.turn_node_log_id
            ├─ payload_audit_logs.turn_node_log_id
            ├─ intervention_logs.turn_node_log_id
            └─ rag_retrieval_logs.turn_node_log_id
```

실험의 유일한 응답 키는 `(experiment_run_id, turn_no, node)`입니다. `run_id`는 사람이 읽을 수 있는 실행명이며 `#`가 포함된 이름도 있습니다. 파일명을 터미널에서 사용할 때 따옴표로 감싸십시오.

- `formal + accepted`가 논문 분석 기준입니다. `analysis_eligible` 등 응답별 품질 필드와 서로 다른 의미입니다.
- `physical_node_url`은 공개본에서 역할 호스트로 치환했습니다. A/B/C의 역할·연결 구조는 유지합니다.
- `prompt_hash`는 메시지 배열, `payload_hash`는 노드 식별과 메시지의 정규화 해시입니다. HTTP 요청 전체·모델 내부 상태·하드웨어 상태를 포괄하지 않습니다.
- `response_hash`는 응답 텍스트의 SHA-256입니다. 내용 정확성·품질 판단을 뜻하지 않습니다.
- `metric_status`, `metrics_json`, `threshold_snapshot`, `sc_decision_payload` 등은 JSON을 담은 CSV 문자열입니다. 일반 텍스트 분리 대신 CSV와 JSON 파서를 순서대로 사용하십시오.
- 빈 문자열은 원 추출기에서 NULL 및 빈 값 표현에 사용했습니다. pandas 기본 NA 변환으로 식별자를 바꾸지 않도록 `keep_default_na=False`를 사용합니다.
- bit/bool 필드는 테이블·JSONL마다 `0/1` 또는 `true/false`일 수 있습니다. 분석 코드의 변환 규칙을 사용합니다.
- `rag_retrieval_logs`에 모든 응답 행이 있는 것은 아닙니다. 무검색 조건을 inner join으로 누락시키지 않도록 주의합니다.

## 검색 자료

`data/rag/chunks.jsonl.gz`는 text, chunk ID, 원문 파일명·페이지·해시 등을 포함합니다. `embedding_metadata.jsonl.gz`와 `embeddings.npy`는 행 순서를 유지한 원천 임베딩입니다. `retrieved_documents.json`은 실제 분석 입력에 사용된 145개 청크의 Chroma 문맥과 메타데이터입니다.

원 PDF 자체는 포함하지 않았습니다. 청크의 `metadata.source_file`, `source_sha256`, `page/page_range`가 출처 추적의 기준이며, 공개 청크에 자동으로 새로운 포괄 재배포 라이선스를 부여하지 않습니다. [권리 안내](../RIGHTS.md)를 확인하십시오.
