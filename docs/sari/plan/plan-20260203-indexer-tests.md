# [10] 인덱서 구조 테스트 케이스 v1

[scope][indexer][tests]
**목표**: 인덱서 분리 구조(Collector/Parser/Validator/Sink)의 계약을 테스트로 고정한다.

---

## 1) Validator 테스트

### V1 필수 필드 누락
- 입력: doc_id 또는 parse_status 누락
- 기대: ValidationResult.ok=false, errors에 누락 필드 기록

### V2 형식 위반
- 입력: doc_id 형식 불일치, parse_status enum 외 값
- 기대: ValidationResult.ok=false

### V3 내용 규칙 위반
- 입력: parse_status=ok인데 body_text/symbols 모두 없음
- 기대: ValidationResult.ok=false
- 예외: Policy.allow_metadata_only_ok=true면 ok 가능

### V4 skip/failed 본문 금지
- 입력: parse_status=skipped인데 body_text 존재
- 기대: ValidationResult.ok=false

### V5 metadata-only ok
- 입력: parse_status=ok, body_text/symbols 없음, allow_metadata_only_ok=true
- 기대: ValidationResult.ok=true

---

## 2) Collector 테스트

### C1 root boundary
- 입력: roots 밖 경로 포함
- 기대: FileItem 생성 안됨

### C2 include_ext empty
- 입력: include_ext=[]
- 기대: 모든 확장자 허용

### C3 include_ext match
- 입력: include_ext=[.py], file=.txt
- 기대: FileItem is_excluded=true (기본은 hard exclude)

### C4 max_file_bytes=0
- 입력: max_file_bytes=0
- 기대: size 제한 없음
 
### C5 root_uri parent/child
- 입력: root_uri가 config root의 child/parent
- 기대: policy 규칙에 따라 포함/제외 결정

### C6 repo derivation
- 입력: rel_path에 슬래시 없음
- 기대: repo=__root__

### C7 include_files override
- 입력: include_files에 명시된 경로가 exclude_globs에 걸림
- 기대: include_files 우선으로 FileItem is_excluded=false

---

## 3) Loader 테스트

### L1 decode policy strong
- 입력: UTF-8 디코딩 실패 케이스
- 기대: content="" 또는 is_binary=true

### L2 decode policy ignore
- 입력: invalid UTF-8 포함
- 기대: content는 best-effort, is_binary=false

### L3 sampled large file
- 입력: size > parse_limit_bytes, sample 허용
- 기대: sampled=true, content=sample

### L4 binary detection
- 입력: \x00 포함 데이터
- 기대: is_binary=true (Orchestrator가 skip/failed 정책 적용)

### L5 empty content (non-binary)
- 입력: content="" & is_binary=false
- 기대: parse_status=skipped, parse_reason=no_parse (meta only)

---

## 4) Parser 선택/폴백 테스트

### P1 category 우선
- language + heuristic 동시 가능 → language 선택

### P2 priority 우선
- 동일 category, priority 높은 파서 선택

### P3 can_handle=false
- 우선순위와 관계없이 skip

### P4 language 실패 폴백
- language 파서 fail → 다음 language 파서

### P5 heuristic 폴백
- language 전체 fail → heuristic 파서

### P6 heuristic 실패
- heuristic도 fail → parse_status=failed, meta 유지
 
### P7 partial success
- 일부 symbol 실패 → parse_status=ok + errors 기록(정책 의존)

---

## 5) Sink 테스트

### S1 skipped meta row 유지
- 입력: parse_status=skipped
- 기대: meta row 유지, body_text 없음

### S2 failed meta row 유지
- 입력: parse_status=failed
- 기대: meta row 유지, errors 기록

### S3 delete by doc_id
- 입력: delete(doc_id)
- 기대: 해당 doc_id 제거

---

## 6) 통합 테스트 (경량)

### I1 end-to-end 최소 시나리오
- 입력: 단일 파일 (parse ok)
- 기대: Collector→Parser→Validator→Sink 정상 흐름

### I2 parse_skip 시나리오
- 입력: 너무 큰 파일
- 기대: parse_status=skipped, meta만 저장

---

## 8) 테스트 우선순위 (P0→P2)

### P0 (계약 보장)
- Validator 필수 필드/형식 검증
- parse_status=skipped → meta 유지
- include_ext empty = no filter
- max_file_bytes=0 = 무제한
- root boundary 위반 차단

### P1 (선택 규칙/폴백)
- Parser 선택 규칙 (category/priority/can_handle)
- language→heuristic 폴백
- heuristic 실패 시 failed 처리

### P2 (성능/안정성)
- large file sampling
- loader decode 정책
- batch/commit/dedup 경로

---

## 7) Orchestrator 테스트

### O1 loader 실패
- 입력: read/parse 실패
- 기대: parse_status=failed, errors 기록

### O2 policy exclude
- 입력: is_excluded=true
- 기대: ParseResult 생성 안됨 (hard exclude)

### O3 exclude handling (delete-only)
- 입력: is_excluded=true + 기존 인덱스 존재
- 기대: Sink upsert 없음, delete만 수행
