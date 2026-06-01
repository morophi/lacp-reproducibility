# LACP 실험 조건 명세 v2

**실험명:** LACP 복지 민원 상담 30턴 시나리오 평가  
**기준 입력:** `lacp_scenario_base_v2.jsonl`  
**시스템 프롬프트:** `lacp_system_prompt.txt` (Harness prompt*builder에서 별도 주입)  
**발화 출처:** 민원노드*발화\_30선\_v2.md (raw_query_pool_v3 기반)  
**작성일:** 2026-05-25  
**버전:** v1 → v2 (피어 리뷰 반영)

---

## v1 → v2 변경 이력

| 항목                              | 판단    | 변경 내용                                                                         |
| --------------------------------- | ------- | --------------------------------------------------------------------------------- |
| turn 0 system prompt 분리         | ✅ 수용 | JSONL에서 제거 → `lacp_system_prompt.txt`로 분리. Harness prompt_builder에서 주입 |
| live 재조정 (turn 4·17·25)        | ✅ 수용 | 1 → 2. "처음 알아보는 건데요" / "제가 ~ 중인데요" / "어려운 상황인데" 맥락 존재   |
| 복합 가구 상담 시나리오 설명 추가 | ✅ 수용 | 섹션 3 신설                                                                       |
| JSONL schema 명시                 | ✅ 수용 | 섹션 4 신설                                                                       |
| scenario_hash 포함/제외 기준      | ⏳ 보류 | Harness 구현 스펙 미확정 — TBD 앵커만 설정 (섹션 5)                               |

---

## 1. 고정 조건 (모든 단계 공통 불변)

| 항목                 | 값                                   | 비고                                           |
| -------------------- | ------------------------------------ | ---------------------------------------------- |
| 시나리오 입력 파일   | `lacp_scenario_base_v2.jsonl`        | 수정 금지                                      |
| 시스템 프롬프트 파일 | `lacp_system_prompt.txt`             | Harness prompt_builder에서 주입, 수정 금지     |
| 발화 순서            | turn 1~30 순차 진행                  | S1(1~6)→S2(7~12)→S3(13~18)→S4(19~24)→S5(25~30) |
| 발화 내용            | v2 확정 텍스트                       | 오탈자 수정 외 변경 금지                       |
| 메타데이터           | seg / raw_id / n_value / live / conf | 재산정 필요 시 별도 파일로 분기                |
| 제외 카테고리        | 보건의료(faq01), 인구아동(faq03)     |                                                |
| 언어                 | 한국어                               |                                                |

---

## 2. 실험 파이프라인 단계

### Phase 0 — 사전 점검 (단계 1~4)

| 단계 | 이름                        | 목적                                             | 가변 조건                      | 출력                |
| ---- | --------------------------- | ------------------------------------------------ | ------------------------------ | ------------------- |
| 1    | Rough Test Run              | 파이프라인 연결 확인, 형식 오류 탐지             | 없음 (기본 설정)               | 원시 응답 텍스트    |
| 2    | Smoke Test Run              | 최소 기능 동작 확인 (세그먼트별 대표 1턴)        | 5턴 서브셋 — turn 1·7·13·19·25 | pass/fail 판정      |
| 3    | TR Preflight Run            | 전체 30턴 형식 적합성 및 응답 완전성 사전 점검   | 없음                           | 응답 길이·형식 로그 |
| 4    | LMS / Logprob Preflight Run | 토큰 확률 분포 및 log-probability 정상 범위 확인 | logprob 출력 활성화            | logprob JSON        |

### Phase 1 — 본 실행 (단계 5~7)

| 단계 | 이름    | 목적                                        | 가변 조건           | 출력             |
| ---- | ------- | ------------------------------------------- | ------------------- | ---------------- |
| 5    | CR Run  | A/B/C 노드 간 runtime variance 및 baseline response stability 측정 | intervention 최소화 | 30턴 응답 세트 A |
| 6    | CR2 Run | RAG-off 또는 natural condition에서 LMS/CDS/MA 자연 분포 측정 및 theta calibration basis 생성 | CR Run 이후 calibration 조건 | 30턴 metric 분포 |
| 7    | Run B   | primary intervention effect 측정: RAG pure effect 및 SC differential contribution 평가 | **본실험 전 확정 필요** | Run B metric summary |

> 정합성 메모: CR은 단순 응답 일관성 재검사가 아니라 cross-node runtime/hardware variance와 baseline response stability를 측정하는 단계이다. CR2는 CR의 반복 실행이 아니라 Run B/CF 전에 theta 산정 근거가 되는 natural metric distribution을 고정하는 단계이다.

### Run B 잠금 필요 항목

Run B는 TR Preflight 및 LMS / Logprob Preflight 이후 본실험에 진입하기 전에 반드시 다음 항목을 잠근다.

| 항목 | 상태 | 메모 |
| ---- | ---- | ---- |
| condition_name | 미확정 | 기본 후보: `run_b` |
| run_mode | 미확정 | 본실험 후보: `formal` |
| RAG trigger policy | 미확정 | `theta_config.json` 및 `sc_policy.yaml` 기준 |
| Node A treatment | 미확정 | RAG + SC-Protocol |
| Node B treatment | 미확정 | RAG only |
| Node C treatment | 미확정 | baseline, RAG/SC 금지 |
| theta_config hash | 미확정 | CR2 이후 freeze |
| corpus_version / collection_name | 미확정 | RAG corpus freeze 필요 |
| top_k | 미확정 | `node_config.yaml` 또는 Run B manifest 기준 |
| scenario_hash | 미확정 | 섹션 5 기준으로 산정 |

### Phase 2 — Counterfactual 점검 (단계 8~13)

| 단계 | 이름 | CF 조건 변수 | 상태   |
| ---- | ---- | ------------ | ------ |
| 8    | CF-A | **TBD**      | 미확정 |
| 9    | CF-B | **TBD**      | 미확정 |
| 10   | CF-C | **TBD**      | 미확정 |
| 11   | CF-D | **TBD**      | 미확정 |
| 12   | CF-E | **TBD**      | 미확정 |
| 13   | CF-F | **TBD**      | 미확정 |

> CF 단계 조건은 Phase 2 설계 시 `cf_conditions_v1.md`로 확장 예정.

---

## 3. 시나리오 성격 — 복합 가구 상담

본 시나리오는 단일 급여 상담이 아니라, **복합 가구 상황에서 한 민원인이 가족 구성원의 복지 수급, 본인의 소득·자활 조건, 부모 세대의 연금·장기요양 문제를 연속적으로 문의하는 multi-issue welfare consultation scenario**로 설계하였다.

### 등장 주체별 발화 분포

| 주체      | 관련 turn                                | 주요 쟁점                                                |
| --------- | ---------------------------------------- | -------------------------------------------------------- |
| 어머니    | 1·2·3·4·13·15·18·20·26·29                | 기초수급·장애수당·기초연금·활동지원·장기요양·복지카드    |
| 본인      | 5·7·8·9·10·11·12·16·17·19·21·23·25·28·30 | 긴급복지·실업급여·재산·자활·조건부수급·청년계좌·신용불량 |
| 아버지    | 22·24                                    | 교정시설 수감·부부 기초연금 감액                         |
| 가구 전체 | 6·14                                     | 자녀 소득·부양의무자 기준                                |

이 구성은 **실제 민원에서 한 가족 구성원이 여러 제도 쟁점을 한 통화에서 묻는 패턴**을 반영한다. 단일 제도 시나리오 대비 RAG multi-domain retrieval 및 대화 히스토리 맥락 유지 성능을 동시에 측정할 수 있다는 실험적 장점이 있다.

---

## 4. JSONL Schema 명세

```
scenario_format       = jsonl
encoding              = UTF-8
one_record_per_line   = true
total_lines           = 30
turn_range            = 1~30
role                  = "user" (전 레코드)
system_prompt         = excluded — lacp_system_prompt.txt로 분리 관리
```

### 레코드 스키마

```json
{
  "turn":     <int, 1~30>,
  "role":     "user",
  "content":  <string, 민원인 발화문>,
  "seg":      <"S1"|"S2"|"S3"|"S4"|"S5">,
  "raw_id":   <string, SW####|OD####|CR####>,
  "n_value":  <int, FAQ 고유 식별자>,
  "live":     <int, 1~3, 발화 생동감 점수>,
  "conf":     <int, 0~3, 갈등 잠재력 점수>
}
```

### live / conf 기준 요약

| 점수 | live 기준                       | conf 기준          |
| ---- | ------------------------------- | ------------------ |
| 0    | 사무적 질의, 감정·맥락 없음     | 불이익 구조 없음   |
| 1    | 최소 생활 맥락 포함             | 불이익 가능성 낮음 |
| 2    | 1인칭·상황 묘사 포함            | 불이익 구조 내재   |
| 3    | 구어체·감정 신호·제약 상황 복합 | 명시적 압박·갈등   |

> S4 발화는 conf ≥ 1 필수 (전 turn 충족 확인됨)

---

## 5. 미확정 항목 (TBD)

| 항목                    | 현황   | 조건                                                   |
| ----------------------- | ------ | ------------------------------------------------------ |
| scenario_hash 산정 기준 | 부분 확정 | user turn 1~30 canonical JSONL 기준. system prompt는 별도 hash로 분리 |
| system_prompt_hash 산정 | 미확정 | `lacp_system_prompt.txt` 및 Harness prompt_builder policy hash와 연결 필요 |
| Run B 가변 조건         | 미확정 | 본실험 전 잠금 필요. 섹션 2의 Run B 잠금 필요 항목 참조 |
| CF-A~F 조건 변수        | 미확정 | Phase 2 설계 시 `cf_conditions_v1.md`로 분리 작성      |

### scenario_hash / system_prompt_hash 기준

`scenario_hash`는 민원 입력 고정성을 나타내는 값으로 사용한다. 따라서 system prompt, SC policy block, RAG context, Harness base system prompt는 포함하지 않는다.

권장 기준:

```text
scenario_hash
  = canonical serialization of user turn records 1~30
  = fields: turn, role, content, seg, raw_id, n_value, live, conf
  = encoding: UTF-8
  = order: turn ascending
```

`system_prompt_hash`는 별도로 산정한다. 이렇게 분리하면 system prompt 또는 Harness prompt policy만 바뀐 경우에도 scenario 자체가 바뀐 것처럼 오인하지 않는다.

---

## 6. 파일 구성

```
lacp_scenario_base_v2.jsonl     ← 입력 픽스처 (user turn 1~30, 수정 금지)
lacp_system_prompt.txt          ← 시스템 프롬프트 (Harness prompt_builder 주입용)
experiment_conditions_v2.md     ← 본 문서
cf_conditions_v1.md             ← [미작성] CF A~F 조건 상세
```
