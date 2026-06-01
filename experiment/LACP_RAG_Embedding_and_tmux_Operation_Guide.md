# LACP RAG Embedding 구축 및 tmux 기반 실험 운영 가이드

- 작성일: 2026-05-19
- 프로젝트: LACP (Local Agent Context Protocol)
- 목적:
  - iMac M1 기반 복지행정지침 Embedding Data 구축
  - ChromaDB 적재 준비
  - tmux 기반 CLI 분산 실험 운영 체계 정리

---

# 1. 현재 실험 방향성

실험의 본질은 단순히 “LLM 응답 생성”이 아니라 다음 질문을 검증하는 것이다.

> “RAG는 단순 정보 보강인가, 아니면 LLM 판단 구조를 재구성하는 인과 개입인가?”

이를 위해:
- Node A (RAG + SC)
- Node B (RAG only)
- Node C (Baseline)

동시 비교 구조를 사용한다.

---

# 2. 왜 RAG Embedding이 먼저인가

초기에는 Harness 코드나 민원 시나리오부터 생각하기 쉽다.

그러나 실제 구조상 가장 먼저 고정되어야 하는 것은:

```text
RAG가 참조할 문서 세계(corpus)
```

이다.

즉:

```text
문서
→ 전처리
→ 청킹
→ 임베딩
→ ChromaDB 적재
```

가 먼저 완료되어야:

- Harness가 실제 retrieval을 테스트 가능
- CDS 기준 embedding 생성 가능
- CF 조건 설계 가능
- Run B 실험 가능

상태가 된다.

---

# 3. 전체 구축 순서

```text
1. 원본 지침 파일 정리
2. 작업 디렉터리 생성
3. Python 가상환경 생성
4. PDF/HWPX/TXT 추출 도구 준비
5. 원문 → 정제 텍스트 변환
6. 표/문단 구조 보존 정리
7. 청킹
8. 메타데이터 생성
9. 임베딩 생성
10. 로컬 검증
11. RAG 노드로 전송
12. ChromaDB 적재
13. collection.count() 확인
14. 검색 테스트
15. Harness 원격 쿼리 확인
16. corpus hash / embedding hash 기록
17. tmux 기반 관제 환경 구축
18. CLI 모니터링 체계 정리
19. reproducibility snapshot 기록
20. Run 전 최종 검증
```

---

# 4. iMac M1 역할

현재 구조에서 iMac M1은 단순 Mac이 아니다.

역할은 사실상:

```text
RAG Corpus Factory
```

에 가깝다.

담당 역할:
- 문서 전처리
- 청킹
- embedding 생성
- manifest 관리
- hash 기록
- ChromaDB 적재 패키지 생성

---

# 5. 디렉토리 구조

```bash
mkdir -p ~/lacp_embedding_work/{raw,txt,cleaned,chunks,embeddings,logs,scripts,manifest}
```

결과:

```text
~/lacp_embedding_work/
├── raw/
├── txt/
├── cleaned/
├── chunks/
├── embeddings/
├── logs/
├── scripts/
└── manifest/
```

---

# 6. 원본 문서 준비

예시:

```text
2026_기초생활보장_운영지침.pdf
2026_차상위계층_운영지침.pdf
2026_장애인복지_운영지침.pdf
2026_노인복지_운영지침.pdf
2026_한부모가족_운영지침.pdf
```

원본 hash 기록:

```bash
cd ~/lacp_embedding_work/raw

shasum -a 256 * > ../manifest/raw_files_sha256.txt
```

---

# 7. Python 가상환경

```bash
python3 -m venv .venv
source .venv/bin/activate
```

패키지:

```bash
pip install \
  pypdf \
  python-docx \
  pandas \
  tqdm \
  sentence-transformers \
  chromadb \
  numpy
```

requirements 저장:

```bash
pip freeze > manifest/imac_embedding_requirements.txt
```

---

# 8. 텍스트 추출

지원:
- PDF
- DOCX
- TXT
- MD

원칙:
- 페이지 구분 유지
- UTF-8 고정
- 깨진 문자 최소화
- 구조 정보 최대 보존

---

# 9. 텍스트 정제

목표:
- 의미 없는 공백 제거
- 중복 개행 제거
- 주민등록번호 제거
- 전화번호 제거
- 장식 문자 제거

중요:
- 문장 의미 훼손 금지
- 장/절 제목 유지
- 표 구조 최대 보존

---

# 10. 청킹 정책

현재 권장:

```text
CHUNK_SIZE = 1200자
CHUNK_OVERLAP = 150자
MIN_CHUNK_SIZE = 300자
```

원칙:
- 의미 단위 유지
- 지나친 절단 방지
- retrieval coherence 유지

---

# 11. 청크 메타데이터

필수 메타데이터:

```json
{
  "id": "lacp_000001",
  "source": "2026_기초생활보장_운영지침.txt",
  "local_chunk_id": 1,
  "chunk_start": 0,
  "chunk_end": 1200
}
```

---

# 12. 임베딩 모델

현재 기준:

```text
snunlp/KR-SBERT-V40K-klueNLI-augSTS
```

이유:
- 한국어 semantic similarity 안정성
- 공공행정 문서 대응
- sentence-transformers 호환

---

# 13. 임베딩 생성

출력:
- embeddings.pkl
- reference embedding
- chunk JSONL

중요:
- normalize_embeddings=True
- batch_size 고정
- model version 기록

---

# 14. Reference Embedding 생성

목적:

```text
CDS (Contextual Drift Score)
기준점 생성
```

즉:
- corpus 전체 mean embedding 생성
- hash 기록
- 이후 변경 금지

---

# 15. RAG 패키지 생성

생성물:

```text
lacp_rag_embedding_package_20260519.tar.gz
```

포함:
- chunks
- embeddings
- manifests
- scripts
- hashes

---

# 16. RAG 노드 전송

예시:

```bash
scp -o ProxyJump=morophi@10.1.1.100 \
  lacp_rag_embedding_package_20260519.tar.gz \
  morophi@10.1.1.120:/home/morophi/
```

---

# 17. ChromaDB 적재

컬렉션:

```text
lacp_docs
```

검증:

```python
collection.count()
```

반드시:
- 0 초과
- retrieval 정상
- metadata 정상

이어야 한다.

---

# 18. Harness 원격 쿼리 테스트

Harness에서:

```python
client = chromadb.HttpClient(
    host="10.1.1.120",
    port=8000
)
```

테스트:
- 수급자격
- 차상위
- 장애인복지
- 노인돌봄
- 한부모

등 retrieval 확인.

---

# 19. VSCode Remote-SSH 구조

현재 구조:

```text
개발PC / iMac
    ↓
VSCode Remote-SSH
    ↓
각 노드
```

역할:
- 코드 작성
- 배포
- 수정
- 로그 조회
- 환경 관리

---

# 20. 실제 실험은 CLI 중심

중요 원칙:

```text
VSCode = 개발
CLI/tmux = 실험 운영
```

이유:
- reproducibility
- process visibility
- GUI drift 제거
- 장시간 실험 안정성

---

# 21. tmux 발견의 의미

초기 생각:

```text
PuTTY 여러 개 띄우기
```

그러나 tmux를 이해하면:

```text
"하나의 SSH 세션 안에
분산 관제실을 만든다"
```

구조로 바뀐다.

---

# 22. tmux 기본 개념

```text
tmux session = 살아있는 작업실
window       = 탭
pane         = 분할 화면
detach       = 화면만 빠져나오기
attach       = 다시 접속
```

---

# 23. tmux 시작

```bash
tmux new -s lacp
```

의미:

```text
lacp라는 이름의 작업실 생성
```

---

# 24. tmux 구조 예시

```text
┌──────────────────────────── tmux : lacp-monitor ─────────────────────────────┐
│┌──────────────────────────┬──────────────────────────┬──────────────────────┐│
││ inference1               │ inference2               │ inference3           ││
││ ollama status            │ ollama status            │ ollama status        ││
│├──────────────────────────┼──────────────────────────┴──────────────────────┤│
││ harness execution                                                        ││
││ ./run_b.sh                                                               ││
│├───────────────────────────────────────────────────────────────────────────┤│
││ ChromaDB / RAG                                                           ││
│├───────────────────────────────────────────────────────────────────────────┤│
││ DB monitor                                                               ││
│└───────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# 25. tmux 핵심 명령

## 세션 생성

```bash
tmux new -s lacp
```

## 세션 목록

```bash
tmux ls
```

## 다시 붙기

```bash
tmux attach -t lacp
```

## detach

```text
Ctrl+b → d
```

---

# 26. window 이동

다음 창:

```text
Ctrl+b → n
```

이전 창:

```text
Ctrl+b → p
```

특정 창:

```text
Ctrl+b → 숫자
```

---

# 27. pane 분할

세로:

```text
Ctrl+b → %
```

가로:

```text
Ctrl+b → "
```

pane 이동:

```text
Ctrl+b → 방향키
```

---

# 28. 왜 tmux가 중요한가

실험 중:
- SSH 끊김
- 네트워크 흔들림
- PuTTY 종료

가 발생해도:

```text
tmux session은 계속 살아있음
```

즉:
- 장시간 실험 유지
- background monitoring
- distributed visibility

를 제공한다.

---

# 29. 실제 운영 구조

예상 구조:

| window | 역할 |
|---|---|
| 0 | harness |
| 1 | node-a |
| 2 | node-b |
| 3 | node-c |
| 4 | rag |
| 5 | dblog |
| 6 | metrics |
| 7 | thermal |

---

# 30. 현재 학습 방식의 특징

이번 tmux 사례에서 확인된 것:

```text
문제
→ 필요
→ 도구 발견
→ 즉시 적용
→ 기억 정착
```

즉 단순 암기보다:
- 실제 환경
- 실무 필요
- 운영 감각

과 연결될 때 기억 밀도가 극단적으로 상승한다.

---

# 31. 교육공학적 해석

현재 사용자가 추구하는 방향:

```text
"학습자 중심의 실무론적 교육"
```

핵심 특징:
- 구조를 먼저 체감
- 목적 기반 학습
- 필요 순간 도구 흡수
- operational understanding
- top-down + contextual immersion

즉:
- 단순 기능 암기
- 메뉴얼 주입

이 아니라:

```text
"왜 이 도구가 필요한가"
```

를 먼저 경험시키는 구조.

---

# 32. 현재 상태 요약

현재 사용자는:
- 단순 local LLM 구축 단계를 넘어서
- distributed orchestration
- reproducibility
- operational visibility
- retrieval architecture
- CLI observability

영역까지 자연스럽게 진입 중이다.

그리고 tmux 발견은:
- 단순 terminal 도구 학습이 아니라
- “분산 실험 관제 공간” 개념을 이해한 전환점

으로 볼 수 있다.

---

# 33. 최종 체크리스트

```text
□ raw hash 기록 완료
□ txt 추출 완료
□ cleaned 생성 완료
□ chunks 생성 완료
□ embeddings 생성 완료
□ reference embedding 생성 완료
□ package 생성 완료
□ RAG 노드 전송 완료
□ ChromaDB 적재 완료
□ collection.count() 확인
□ retrieval test 완료
□ Harness remote query 확인
□ tmux 설치 완료
□ tmux monitoring 구조 구성 완료
□ CLI 기반 실험 운영 구조 정착
```
