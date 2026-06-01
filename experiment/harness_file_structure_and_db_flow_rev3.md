# LACP Harness 파일 구조 및 DB 적재 실행 순서

## 1. Harness 중심 파일 구조

```text
New project/
├─ runtime_impl/
│  ├─ agent/
│  │  ├─ run_scenario.py
│  │  ├─ scenario_loader.py
│  │  └─ scenario_sender.py
│  └─ harness/
│     ├─ harness_server.py
│     ├─ experiment_runner.py
│     ├─ node_client.py
│     ├─ prompt_builder.py
│     ├─ trigger_controller.py
│     ├─ sc_policy.py
│     ├─ rag_client.py
│     ├─ metrics.py
│     ├─ quality_gate.py
│     ├─ logger.py
│     ├─ config_utils.py
│     ├─ HARNESS_POLICY.md
│     ├─ run_unit_tests_no_pytest.py
│     ├─ requirements.txt
│     ├─ config/
│     │  ├─ node_config.yaml
│     │  ├─ sc_policy.yaml
│     │  └─ theta_config.json
│     └─ tests/
│        ├─ test_metrics_lms.py
│        ├─ test_metrics_ma.py
│        ├─ test_prompt_builder.py
│        ├─ test_quality_gate.py
│        ├─ test_sc_policy.py
│        └─ test_trigger_controller.py
├─ dblog_schema/
│  ├─ lacp_db_schema.sql
│  ├─ 20260523_add_quality_gate_fields.sql
│  ├─ 20260525_add_eligibility_separation_fields.sql
│  ├─ apply_lacp_schema.sh
│  ├─ check_quality_indexes.sql
│  ├─ check_quality_schema.sql
│  └─ verify_lacp_schema.sql
├─ verify_remote/
│  ├─ harness_orchestration_smoke.py
│  ├─ smoke_db_writer.py
│  ├─ check_db_driver.py
│  ├─ check_harness_formal_nodeclient.py
│  ├─ check_lms_fields.py
│  ├─ check_nothink_openai_quality.py
│  ├─ check_db_writer_smoke.sql
│  ├─ check_tr_preflight_cr_smoke.sql
│  ├─ check_tr_preflight_lms_formal.sql
│  ├─ check_tr_preflight_lms128_formal.sql
│  └─ check_tr_preflight_runb_smoke_ragok_001.sql
└─ scripts/
   ├─ run_ingest.py
   ├─ 01_pdf_extract.py
   ├─ 02_canonicalize_md.py
   ├─ 03_semantic_verify_report.py
   ├─ 04_chunk_table_aware.py
   ├─ 05_embed_chunks.py
   ├─ 06_manifest_snapshot.py
   ├─ 07_sync_logs_to_dblog.py
   ├─ 08_ingest_chromadb.py
   ├─ 09_validate_retrieval.py
   ├─ 10_prompt_size_test.py
   ├─ ingest_config.py
   └─ README.md
```

위 트리는 런타임 Harness 경로를 중심으로 정리한 것이다. `__pycache__`, 대화 export, 생성된 JSONL 결과물은 실행 산출물이므로 제외했다.

## 2. 각 영역의 역할

`runtime_impl/agent`는 시나리오 송신자이다. 이 계층은 기존 시나리오 JSON을 읽고, 각 turn의 시민 발화를 Harness의 `/turn` 엔드포인트로 전달한다. RAG 검색, SC-Protocol 판단, 프롬프트 조립, 추론노드 호출, 지표 계산, DB 기록을 수행하지 않는다.

`runtime_impl/harness`는 실험 제어의 중심이다. Harness는 turn payload를 받은 뒤 intervention 여부를 결정하고, A/B/C 추론노드별 프롬프트를 조립하며, 세 추론노드에 병렬 요청을 보내고, 응답 품질과 지표를 계산한 다음 JSONL 및 MariaDB dblog에 기록한다.

`dblog_schema`는 dblog 노드의 MariaDB 스키마와 검증 SQL이다. Harness 런타임이 적재하는 주요 테이블은 `turn_node_logs`, `intervention_logs`, `metric_logs`이다.

`verify_remote`는 원격 배포 및 스모크 검증용 파일 묶음이다. 현재 런타임 모듈과 같은 경로에 놓이는 검증 스크립트, DB writer smoke, TR/LMS/quality 확인 SQL이 들어 있다.

`scripts`는 RAG 코퍼스 ingest 파이프라인이다. 원천 PDF를 canonical markdown, chunk, embedding, ChromaDB collection으로 만드는 사전 준비 영역이며, Harness 런타임에서 추론노드 응답을 DB로 적재하는 직접 경로는 아니다. 다만 Harness의 `rag_client.py`가 조회하는 ChromaDB collection을 공급한다.

## 3. 실행 순서: 시나리오에서 dblog 적재까지

### 3.1 dblog 스키마 사전 준비

1. dblog 노드에서 `dblog_schema/lacp_db_schema.sql`을 적용한다.
2. 이 SQL은 `lacp_db` 데이터베이스와 주요 테이블을 만든다.
3. `turn_node_logs`는 각 run, turn, node의 응답 텍스트, prompt hash, RAG/SC 적용 여부, quality gate, metrics JSON을 저장한다.
4. `intervention_logs`는 각 node에 어떤 intervention이 들어갔는지를 별도 정규화 테이블로 저장한다.
5. `metric_logs`는 LMS, CDS, MA, SRR, SCI 등 지표를 node-turn 단위로 저장한다.
6. `20260523_add_quality_gate_fields.sql`은 quality gate와 logprob audit 필드를 보강한다.
7. `20260525_add_eligibility_separation_fields.sql`은 `history_eligible`, `history_exclusion_reason`, `metric_trigger_eligibility` 필드를 추가한다. 이 migration은 새 Harness logger가 MariaDB에 eligibility separation 필드를 쓰기 전에 dblog 노드에 반드시 적용되어야 한다.

### 3.2 Harness 서버 기동

1. `runtime_impl/harness/harness_server.py`를 실행한다.
2. `parse_args()`가 config 경로를 받는다. 기본값은 `/home/morophi/harness/config/node_config.yaml`, `/home/morophi/harness/config/sc_policy.yaml`, `/home/morophi/harness/config/theta_config.json`이다.
3. `create_app()`이 `ExperimentRunner`를 생성하고 aiohttp 애플리케이션에 저장한다.
4. `POST /turn` 라우트가 등록된다.
5. agent가 `/turn`으로 JSON payload를 보내면 `handle_turn()`이 payload를 읽고 `ExperimentRunner.handle_turn()`으로 넘긴다.

### 3.3 Harness 초기화

`runtime_impl/harness/experiment_runner.py`의 `ExperimentRunner.__init__()`에서 다음 객체들이 초기화된다.

1. `config_utils.load_config()`가 `node_config.yaml`을 읽는다.
2. `SCPolicyEngine`이 `sc_policy.yaml`과 `theta_config.json`을 읽어 SC 정책과 threshold를 준비한다.
3. `NodeClient`가 A/B/C 추론노드 URL과 모델 설정을 준비한다.
4. `MetricComputer`가 LMS, CDS, MA 계산 설정을 준비한다.
5. `TriggerController`가 이전 turn의 지표를 기반으로 intervention trigger를 평가할 준비를 한다.
6. `build_logger()`가 JSONL fallback logger와 MariaDB logger를 구성한다.
7. run별 node history와 직전 metrics 저장소가 메모리에 준비된다.

### 3.4 Agent가 turn payload 송신

1. `runtime_impl/agent/run_scenario.py`가 CLI entrypoint이다.
2. `scenario_loader.py`의 `load_scenario()`가 시나리오 JSON을 읽고 `scenario_id`, `scenario_hash`, `turn_no`, `utterance`를 정규화한다.
3. `scenario_sender.py`의 `send_scenario()`가 각 turn을 순서대로 처리한다.
4. `_turn_payload()`가 다음 정보를 담은 JSON을 만든다.
   - `run_id`
   - `scenario_id`
   - `scenario_hash`
   - `condition`
   - `run_mode`
   - `turn_no`
   - `utterance`
   - `source_file`
   - `sender_node=agent`
5. `_post_json()`이 Harness의 `http://<harness>:9000/turn`으로 payload를 POST한다.
6. agent는 Harness가 `ok: true`와 `nodes_completed`를 반환할 때까지 해당 turn을 완료로 보지 않는다.

### 3.5 Harness가 turn payload 검증 및 intervention 계획 수립

1. `ExperimentRunner.handle_turn()`이 payload를 받는다.
2. `_validate_turn_payload()`가 `run_id`, `scenario_id`, `turn_no`, `utterance` 필수 필드와 condition을 검증한다.
3. `_histories_for_run()`이 run별 A/B/C 독립 대화 history를 가져오거나 새로 만든다.
4. `last_metrics`에서 이전 turn의 node metrics를 가져온다.
5. `_prepare_interventions()`가 condition과 run mode에 따라 intervention 계획을 만든다.

Run B의 일반 흐름은 다음과 같다.

1. `trigger_controller.evaluate_shared_trigger()`가 이전 turn의 A/B 지표를 평가한다.
2. Node C는 trigger source가 아니며 intervention 대상도 아니다.
3. trigger가 켜지면 `rag_client.retrieve()`가 RAG 노드의 ChromaDB collection에서 top-k chunk를 조회한다.
4. `SCPolicyEngine.build_policy_block()`은 Node A에만 들어갈 SC-Protocol policy block을 만든다.
5. 결과 plan은 다음 역할 분리를 강제한다.
   - Node A: RAG + SC 가능
   - Node B: RAG만 가능
   - Node C: RAG와 SC 모두 금지

### 3.6 Node별 프롬프트 조립

1. `prompt_builder.build_messages()`가 A/B/C 각각의 chat messages를 만든다.
2. 모든 node에는 공통 base system prompt와 해당 node의 독립 history, 현재 user utterance가 들어간다.
3. Node A에는 plan에 따라 SC policy block과 RAG context가 들어갈 수 있다.
4. Node B에는 RAG context만 들어갈 수 있다.
5. Node C에 RAG chunk가 들어오거나 B/C에 SC block이 들어오면 `build_messages()`가 예외를 발생시켜 실험 조건 위반을 차단한다.
6. 각 node payload에 대해 `prompt_hash`, `rag_injected`, `sc_policy_applied`, `rag_chunk_ids`, `policy_hash` metadata가 생성된다.

### 3.7 A/B/C 추론노드 병렬 호출

1. `ExperimentRunner.handle_turn()`은 `asyncio.gather()`로 `node_client.chat("A")`, `chat("B")`, `chat("C")`를 동시에 호출한다.
2. `node_client.py`는 run mode에 따라 endpoint를 고른다.
   - smoke: Ollama native `/api/chat`
   - formal: OpenAI-compatible `/v1/chat/completions`
3. `node_config.yaml` 기준 추론노드 URL은 다음과 같다.
   - A: `10.1.1.10`
   - B: `10.1.1.20`
   - C: `10.1.1.30`
4. 모델 설정은 `qwen3-nothink`, temperature `0.0`, seed `42`, `num_predict=512`, `think=false`, formal mode에서 `logprobs=true`, `top_logprobs=5`이다.
5. 각 응답에서 `text_raw`, 정제된 `text`, `elapsed_ms`, endpoint mode, raw response, logprobs, thinking tag 상태가 추출된다.
6. 빈 `<think></think>` shell은 제거하고, 해당 prefix token 위치는 LMS 계산에서 제외한다.
7. non-empty thinking content가 있으면 `failed_TR=true`로 표시된다.

### 3.8 품질 게이트 및 지표 계산

1. `quality_gate.check_output_quality()`가 node별 응답을 검사한다.
2. 빈 응답, non-empty thinking content, 언어 오염, 정책 anchor 실패, truncation risk 등이 있으면 `generation_quality_ready=false`, `analysis_eligible=false`, `exclude_from_causal_trigger=true`가 된다.
3. 실패 응답도 버리지 않고 관측값으로 저장한다. 단, 이후 causal trigger에는 쓰지 않도록 exclusion flag를 기록한다.
4. 단, `analysis_eligible=false` 또는 `exclude_from_causal_trigger=true`가 곧바로 `history_eligible=false`를 의미하지는 않는다. `history_eligible`은 hard history exclusion reason에 따라 별도로 판단한다.
5. `metrics.MetricComputer.compute_node_metrics()`가 node별 지표를 계산한다.
6. LMS는 OpenAI-compatible logprobs 또는 legacy token candidate 분포가 있을 때만 계산한다. 텍스트 휴리스틱 대체 계산은 하지 않는다.
7. MA는 응답 문장 분류 기반으로 `ma_assert`, `ma_epist`, `ma_hedge`, `sent_count`를 계산한다.
8. CDS가 활성화되어 있으면 reference embedding과 응답 embedding의 cosine distance를 계산한다.
9. `compute_cross_node_metrics()`가 Node C를 기준으로 A/B의 `lms_delta`를 계산한다.
10. 계산된 metrics는 `last_metrics[run_id][node]`에 저장되어 다음 turn trigger 판단에 사용된다.

### 3.9 History 갱신 및 DB row 생성

1. 각 node 응답 처리 루프에서 `_append_history()`가 해당 node의 독립 history에 user utterance와 assistant response를 추가한다.
2. `_log_row()`가 DB/JSONL 적재용 row를 만든다.
3. row에는 다음 범주가 포함된다.
   - run/scenario 식별자: `run_id`, `scenario_id`, `scenario_hash`, `condition`, `run_mode`, `turn_no`, `node`
   - 입력/출력 해시: `utterance_hash`, `response_hash`, `response_text_raw_hash`, `prompt_hash`
   - intervention 정보: `rag_injected`, `sc_policy_applied`, `sc_policy_id`, `policy_hash`, `trigger_mode`, `trigger_reasons`, `trigger_source_nodes`, `rag_chunk_ids`
   - 모델 정보: `model_name`, `temperature`, `seed`, `thinking_disabled_requested`, `endpoint_mode`
   - TR/logprob audit: `thinking_tag_present`, `empty_thinking_shell`, `thinking_content_present`, `cleaning_applied`, `failed_TR`, `raw_logprobs_len`, `clean_logprobs_len`, `excluded_token_positions`
   - quality gate: `generation_quality_ready`, `analysis_eligible`, `exclude_from_causal_trigger`, `usable_as_quality_outcome`, `quality_gate`
   - metrics: `metrics`, `metric_status`

### 3.10 Logger가 JSONL과 dblog MariaDB에 기록

1. `logger.build_logger()`는 `node_config.yaml`의 `logging` 설정을 읽는다.
2. `JSONLLogger`는 항상 활성화된다. 기본 fallback 경로는 `/home/morophi/harness/logs/runs`이다.
3. DB logging이 활성화되어 있고 PyMySQL 사용 가능하면 `MariaDBLogger`가 구성된다.
4. `CompositeLogger.log_turn()`은 먼저 JSONL에 row를 append한다.
5. 그 다음 DB logger가 있으면 MariaDB에 연결한다.
6. DB 접속 대상은 `node_config.yaml` 기준 dblog 노드 `10.1.1.130:3306`, database `lacp_db`, user `morophi`이다.
7. `MariaDBLogger.log_turn()`은 하나의 transaction에서 세 upsert를 수행한다.
   - `_upsert_turn_node()` -> `turn_node_logs`
   - `_upsert_intervention()` -> `intervention_logs`
   - `_upsert_metric()` -> `metric_logs`
8. 세 upsert가 모두 성공하면 `commit()`한다.
9. 하나라도 실패하면 `rollback()`하고 예외를 올린다.
10. JSONL은 DB 쓰기보다 먼저 남기므로 DB 장애가 있더라도 Harness 로컬 실행 증거는 보존된다.

## 4. 데이터 흐름 요약

```text
scenario JSON
  -> agent/run_scenario.py
  -> agent/scenario_loader.py
  -> agent/scenario_sender.py
  -> HTTP POST /turn
  -> harness/harness_server.py
  -> harness/experiment_runner.py
  -> trigger_controller.py + sc_policy.py
  -> rag_client.py, if trigger requires RAG
  -> prompt_builder.py
  -> node_client.py
  -> inference nodes A/B/C
  -> node_client.py response cleaning/logprob extraction
  -> quality_gate.py
  -> metrics.py
  -> experiment_runner.py _log_row()
  -> logger.py CompositeLogger
  -> JSONL fallback
  -> MariaDB dblog node
     ├─ turn_node_logs
     ├─ intervention_logs
     └─ metric_logs
```

## 5. 실행 흐름에서 중요한 불변 조건

1. Agent는 발화 공급자일 뿐이며, RAG/SC/metrics/DB writer 역할을 갖지 않는다.
2. Harness만 추론노드 A/B/C를 호출한다.
3. Node A는 RAG와 SC-Protocol을 받을 수 있다.
4. Node B는 RAG만 받을 수 있고 SC-Protocol은 받을 수 없다.
5. Node C는 baseline이며 RAG와 SC-Protocol을 모두 받을 수 없다.
6. Node C는 trigger source가 아니다.
7. formal mode에서는 non-empty thinking content가 있으면 `failed_TR`로 처리된다.
8. 품질 실패 응답은 삭제하지 않고 DB에 저장하되, causal trigger 재사용에서 제외한다.
9. DB 적재 전 JSONL fallback을 먼저 기록한다.
10. dblog 적재는 Harness가 직접 수행하며, 다른 node 로그를 Harness가 relay하지 않는다.

## 5.1 Eligibility Separation Policy

Harness 정책은 `analysis_eligible`, `exclude_from_causal_trigger`,
`history_eligible`을 분리한다.

`analysis_eligible=false`는 causal/statistical analysis 제외를 뜻하며,
자동으로 다음 turn의 conversation history 제외를 뜻하지 않는다.

`exclude_from_causal_trigger=true`는 해당 row의 metrics가 다음 intervention
trigger 판단에 쓰이지 않는다는 뜻이다.

`history_eligible=false`는 해당 node response가 다음 turn prompt context에
반영되지 않는다는 뜻이다. 현재 hard history exclusion reason은
`infrastructure_invalid`, `empty_response`, `thinking_content_present`,
formal mode의 `truncation_risk`, `language_contamination`,
`intervention_contamination`이다.

Metric-level trigger eligibility도 분리한다. Missing logprobs는 LMS 또는
LMS-delta 기반 trigger eligibility를 false로 만들 수 있지만, CDS/MA 기반
trigger eligibility는 각 metric availability와 trigger policy에 따라 별도로
판단한다.

## 6. 검증 파일의 위치와 용도

`verify_remote/harness_orchestration_smoke.py`는 초기 원격 스모크 테스트용 단일 파일이다. 이 파일은 A/B/C Ollama API 확인, RAG 조회, 동시 추론 호출, JSONL 로그 생성까지 수행한다. 현재 modular runtime에서는 `runtime_impl/harness`의 모듈들이 그 역할을 분리해서 담당한다.

`verify_remote/smoke_db_writer.py`는 실제 DB writer 경로를 검증하기 위해 `logger.build_logger()`를 사용해 synthetic row를 `turn_node_logs`, `intervention_logs`, `metric_logs`에 적재한다.

`verify_remote/check_harness_formal_nodeclient.py`는 formal endpoint, logprobs, thinking tag cleaning, LMS 가능 여부를 확인한다.

`verify_remote/*.sql` 파일들은 DB에 들어간 결과가 실험 조건을 지키는지 확인한다. 예를 들어 Node C에 RAG가 들어가지 않았는지, B에 SC가 들어가지 않았는지, TR/logprob 필드가 채워지는지 확인하는 용도이다.
---

# Rev3 Addendum: Rev8 Turn Barrier and Thermal Event Logging

> Paper alignment: `experiment/lacp_ijibc_rev8.docx`
> Guideline alignment: `experiment/lacp_experiment_guideline_rev5.5.md`
> Revision date: 2026-05-26

## A. Turn-Level Barrier in Harness Execution

Harness is the correct control point for both experimental synchronization and
thermal safeguard enforcement. Agent supplies the scenario utterance; Harness
owns node dispatch, response completion, metric computation, and DB/JSONL
persistence.

Mandatory execution order:

```text
Agent sends turn N
  -> Harness validates payload
  -> Harness prepares A/B/C intervention plans
  -> Harness dispatches A/B/C requests
  -> Harness waits for all A/B/C responses
  -> Harness computes quality and metrics
  -> Harness writes JSONL and dblog rows
  -> Harness marks turn N complete
  -> Harness may accept turn N+1
```

No inference node may advance to the next turn independently. A/B/C completion
time differences are logged as diagnostics; they do not define causal ordering.

## B. Five-Turn Cooldown Event Flow

After every five completed turns, Harness must apply a fixed cooldown barrier.

```text
if turn_no % 5 == 0:
  collect temp_before for inference1/2/3
  write cooldown_start event
  sleep 30 seconds
  collect temp_after for inference1/2/3
  write cooldown_end event
  release next turn batch
```

The cooldown event is a run-control event, not a node response row. It should be
stored in a dedicated event log when available. Until a dedicated table exists,
it may be persisted as JSONL metadata using the same run_id.

## C. Recommended Thermal Event Schema

Dedicated table name:

```text
thermal_event_logs
```

Recommended columns:

```text
id BIGINT AUTO_INCREMENT PRIMARY KEY
run_id VARCHAR(128) NOT NULL
condition_name VARCHAR(64) NULL
run_mode VARCHAR(64) NULL
event_type VARCHAR(64) NOT NULL
batch_end_turn INT NULL
cooldown_sec INT NULL
node VARCHAR(32) NULL
timestamp_utc DATETIME(6) NOT NULL
max_temp_c DOUBLE NULL
temperatures_json JSON NULL
reachable BOOLEAN NULL
source VARCHAR(64) NULL
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

Required event_type values:

```text
thermal_snapshot
cooldown_start
cooldown_end
thermal_logger_start
thermal_logger_stop
```

Minimum JSONL fallback row:

```json
{
  "event": "cooldown_start",
  "run_id": "<run_id>",
  "condition": "<condition>",
  "run_mode": "<run_mode>",
  "batch_end_turn": 5,
  "cooldown_sec": 30,
  "nodes": ["inference1", "inference2", "inference3"],
  "temp_before": {
    "inference1": {"max_temp_c": 74.0},
    "inference2": {"max_temp_c": 68.0},
    "inference3": {"max_temp_c": 74.0}
  }
}
```

Minimum cooldown_end JSONL row:

```json
{
  "event": "cooldown_end",
  "run_id": "<run_id>",
  "condition": "<condition>",
  "run_mode": "<run_mode>",
  "batch_end_turn": 5,
  "cooldown_sec": 30,
  "temp_after": {
    "inference1": {"max_temp_c": 67.5},
    "inference2": {"max_temp_c": 64.0},
    "inference3": {"max_temp_c": 67.375}
  }
}
```

## D. Relationship to Existing dblog Tables

Existing primary tables remain unchanged:

```text
turn_node_logs
intervention_logs
metric_logs
```

Thermal control rows should not be inserted as fake node responses and should
not alter metric calculations. They are operational run-control evidence linked
by run_id and batch_end_turn.

If a dedicated DB migration is deferred, JSONL fallback is acceptable for the
next rough run provided that:

```text
□ cooldown_start and cooldown_end are written with run_id.
□ temp_before and temp_after are present for inference1/2/3.
□ batch_end_turn and cooldown_sec are present.
□ thermal rows are excluded from metric completeness counts.
```

## E. Implementation Placement

Recommended implementation locations:

```text
runtime_impl/harness/experiment_runner.py
  - enforce turn-level barrier
  - trigger cooldown after turn_no % 5 == 0

runtime_impl/harness/logger.py
  - write thermal JSONL fallback rows
  - optionally write thermal_event_logs rows

runtime_impl/harness/config/node_config.yaml
  - thermal_policy.enabled
  - thermal_policy.batch_turns
  - thermal_policy.cooldown_sec
  - thermal_policy.nodes
```

Recommended config:

```yaml
thermal_policy:
  enabled: true
  scope: all_inference_nodes
  nodes: [inference1, inference2, inference3]
  batch_turns: 5
  cooldown_sec: 30
  sample_interval_sec: 1
  source_preference: hwmon
```
