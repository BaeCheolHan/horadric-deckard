# [13] 인덱서 계약 테스트 스켈레톤 v1

[scope][indexer][tests]
**목표**: 구현 전 계약 테스트 최소 세트를 스켈레톤으로 고정한다.

---

## P0 계약 테스트 (필수)

### CT1 include_ext empty
입력: include_ext=[]
기대: 모든 확장자 허용
테스트 위치: `tests/test_contracts.py` (indexer include_ext)

### CT2 max_file_bytes=0
입력: max_file_bytes=0
기대: size 제한 없음
테스트 위치: `tests/test_contracts.py` (max_file_bytes)

### CT3 hard exclude
입력: is_excluded=true
기대: ParseResult 생성 없음, Sink upsert 없음
테스트 위치: `tests/test_contracts.py` (exclude hard)

### CT4 skipped meta 유지
입력: parse_status=skipped
기대: meta row 유지, body_text 비움
테스트 위치: `tests/test_contracts.py` (skipped meta)

### CT5 doc_id 형식
입력: root_id, rel_path
기대: doc_id = root_id/rel_path
테스트 위치: `tests/test_contracts.py` (doc_id)

### CT6 content empty non-binary
입력: content="", is_binary=false
기대: parse_status=skipped, parse_reason=no_parse
테스트 위치: `tests/test_contracts.py` (empty content)

---

## P1 폴백 테스트 (필수)

### CT7 parser 선택
입력: language/heuristic 동시 가능
기대: language 우선
테스트 위치: `tests/test_engine_registry.py` (parser selection)

### CT8 폴백
입력: language 실패
기대: 다음 language → heuristic
테스트 위치: `tests/test_engine_registry.py` (fallback chain)

---

## P2 품질/성능 테스트 (권장)

### CT9 large file sampling
입력: size > parse_limit_bytes
기대: sampled=true, content=sample
테스트 위치: `tests/test_engine_runtime.py` (sampling policy)

### CT10 batch commit
입력: commit_batch_size=500
기대: batch size 준수
테스트 위치: `tests/test_engine_runtime.py` (batch/commit)
