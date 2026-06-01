# RAG 체크리스트 준비완료

# LACP RAG Ingest Environment Preparation
# Pre-Airgap Preparation Runbook

> 목적:
> 폐쇄망 투입 전 dependency / runtime / embedding baseline을 고정하여
> reproducible RAG execution 환경을 생성한다.

---

# 0. 작업 디렉터리 생성

## 전체 작업 디렉터리 생성

```bash
mkdir -p ~/lacp_rag_ingest/{raw,work,extracted,cleaned,chunks,metadata,embeddings,logs,hash,requirements,wheelhouse}

cd ~/lacp_rag_ingest
```

## 확인

```bash
find . -maxdepth 1 -type d | sort
```

정상 예시:

```text
./chunks
./cleaned
./embeddings
./extracted
./hash
./logs
./metadata
./raw
./requirements
./wheelhouse
./work
```

---

# 1. Python Runtime 확인 및 통일

## 현재 Python 확인

```bash
python3 --version
which python3
```

---

# 2. Mac Python 3.11 설치

## Homebrew Python 3.11 설치

```bash
brew install python@3.11
```

## 확인

```bash
/opt/homebrew/bin/python3.11 --version
```

정상 기준:

```text
Python 3.11.x
```

---

# 3. Python 3.11 기반 venv 생성

```bash
cd ~/lacp_rag_ingest

/opt/homebrew/bin/python3.11 -m venv .venv

source .venv/bin/activate
```

## 확인

```bash
python --version
which python
pip --version
```

정상 기준:

```text
Python 3.11.x
.../lacp_rag_ingest/.venv/bin/python
```

---

# 4. pip 기본 도구 업데이트

```bash
python -m pip install --upgrade pip setuptools wheel
```

---

# 5. Runtime 정보 기록

## runtime 디렉터리 생성

```bash
mkdir -p logs/runtime
```

## Python 정보 저장

```bash
python --version \
    > logs/runtime/python_version.txt

which python \
    > logs/runtime/python_path.txt

pip -V \
    > logs/runtime/pip_version.txt
```

## 시스템 정보 저장

```bash
uname -a \
    > logs/runtime/uname.txt

sysctl -n machdep.cpu.brand_string \
    > logs/runtime/cpu.txt
```

---

# 6. requirements 파일 생성

## requirements 디렉터리 확인

```bash
mkdir -p requirements
```

## base_requirements.txt 생성

```bash
cat > requirements/base_requirements.txt << 'EOF'
chromadb
sentence-transformers
transformers
torch
tokenizers
numpy
pandas
pymupdf
pypdf
python-docx
unstructured
tqdm
aiohttp
sqlalchemy
EOF
```

## 확인

```bash
cat requirements/base_requirements.txt
```

---

# 7. 패키지 설치

```bash
pip install -r requirements/base_requirements.txt
```

## 설치 확인

```bash
pip list
```

---

# 8. pip freeze baseline 저장

## runtime 디렉터리 재확인

```bash
mkdir -p logs/runtime
```

## baseline 저장

```bash
pip freeze \
    > logs/runtime/pip_freeze_baseline.txt
```

## 추가 저장

```bash
pip list --format=json \
    > logs/runtime/pip_list.json
```

---

# 9. wheelhouse 생성 (폐쇄망 대비)

## wheelhouse 디렉터리 확인

```bash
mkdir -p wheelhouse
```

## wheel 다운로드

```bash
pip download \
    -r requirements/base_requirements.txt \
    -d wheelhouse/
```

## 확인

```bash
ls wheelhouse/
```

## 압축

```bash
tar -czf \
wheelhouse_py311_$(date +%Y%m%d_%H%M%S).tar.gz \
wheelhouse/
```

## 확인

```bash
ls *.tar.gz
```

---

# 10. tokenizer / embedding baseline 확인

## sentence-transformers 테스트

```bash
python - << 'EOF'
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

vec = model.encode("테스트 문장")

print(vec[:10])
print(len(vec))
EOF
```

정상 기준:

```text
숫자 벡터 출력
384 또는 모델 차원 출력
```

---

# 11. ChromaDB 동작 확인

## 임시 테스트

```bash
python - << 'EOF'
import chromadb

client = chromadb.PersistentClient(path="./test_chroma")

collection = client.get_or_create_collection("test")

collection.add(
    documents=["테스트 문서"],
    ids=["doc1"]
)

print(collection.count())
EOF
```

정상 기준:

```text
1
```

---

# 12. Corpus Hash 준비

## hash 디렉터리 확인

```bash
mkdir -p hash
```

## cleaned 디렉터리 확인

```bash
mkdir -p cleaned
```

## macOS sha256 확인

```bash
which gsha256sum
```

없으면 설치:

```bash
brew install coreutils
```

## corpus hash 생성

```bash
find cleaned/ -type f \
    -exec gsha256sum {} \; \
    | sort \
    > hash/corpus_sha256.txt
```

## 확인

```bash
cat hash/corpus_sha256.txt
```

> 주의:
> `hash/corpus_sha256.txt` 저장 시 `hash/` 디렉터리가 없으면
> `zsh: no such file or directory: hash/corpus_sha256.txt` 오류가 발생한다.
> 따라서 hash 생성 단계 직전 `mkdir -p hash cleaned`를 반드시 실행한다.

---

# 13. embedding hash 생성

## embeddings 디렉터리 확인

```bash
mkdir -p embeddings
```

## embedding hash 생성

```bash
find embeddings/ -type f \
    -exec gsha256sum {} \; \
    | sort \
    > hash/embedding_sha256.txt
```

---

# 14. 최종 baseline snapshot

```bash
tar -czf \
lacp_runtime_snapshot_$(date +%Y%m%d_%H%M%S).tar.gz \
logs/runtime \
requirements \
hash
```

---

# 15. 추론노드 Python 버전 동기화 확인

## 추론노드 Python 버전 확인

```bash
ssh morophi@10.1.1.10 "python3 --version && which python3"

ssh morophi@10.1.1.20 "python3 --version && which python3"

ssh morophi@10.1.1.30 "python3 --version && which python3"
```

## RAG 노드 확인

```bash
ssh morophi@10.1.1.120 "python3 --version && which python3"
```

## 기록

```bash
python --version \
    > logs/runtime/mac_python_version.txt

which python \
    > logs/runtime/mac_python_path.txt
```

---

# 16. 폐쇄망 투입 전 최종 점검

```text
□ Python 3.11.x 전 노드 통일
□ pip freeze baseline 저장 완료
□ wheelhouse 생성 완료
□ tokenizer 테스트 완료
□ sentence-transformers encode 정상
□ ChromaDB insert 정상
□ corpus hash 생성 완료
□ embedding hash 생성 완료
□ runtime snapshot 생성 완료
□ cleaned/hash/embeddings 디렉터리 존재 확인
```

---

# 17. 금지 사항

```text
□ Mac system python 사용 금지
□ conda/base 환경 사용 금지
□ Python 3.12+ 환경 사용 금지
□ venv 비활성 상태에서 pip install 금지
□ pip install 임의 추가 금지
□ brew upgrade 자동 실행 금지
□ 폐쇄망 투입 후 dependency 변경 금지
```

---

# 핵심 원칙

```text
Mac은 작업 편의 노드일 뿐 기준 노드가 아니다.

기준은:
- inference1
- inference2
- inference3
- RAG node

의 Python 3.11.x runtime이다.
```
