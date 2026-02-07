# [11] 인덱서 구현 순서표 v1

[scope][indexer][impl-order]
**목표**: 구현을 “작업 순서”로 고정해 리스크를 줄이고, 단계별 검증 포인트를 명확히 한다.

---

## 1) 준비 단계 (No-code)
1. **Policy 스키마 확정**
   - include_ext/include_files/exclude_dirs/exclude_globs/max_file_bytes/parse_limit/ast_limit
   - allow_metadata_only_ok, decode_policy
2. **doc_id/root_id 규칙 확정**
   - doc_id = `root_id/rel_path`
   - root_id 생성 규칙 = WorkspaceManager.root_id
3. **ParseStatus/Reason enum 고정**
   - parse_status: ok|skipped|failed
   - parse_reason: none|binary|minified|too_large|excluded|error|no_parse
   - ast_status: ok|skipped|failed
   - ast_reason: none|no_parse|too_large|excluded|error

---

## 2) 인터페이스 단계 (Core types)
1. `ParseContext`, `ParseResult`, `ValidationResult` 타입 정의
2. `Parser` 인터페이스 및 `ParserRegistry` 구현
3. `Collector`, `Loader`, `Validator`, `Sink` 인터페이스 정의

검증 포인트:
- 타입 간 필수 필드 누락 없음
- can_handle, priority, category 규칙 문서와 일치

---

## 3) Orchestrator 단계
1. Pipeline Orchestrator 구현
2. root boundary/soft exclude/hard exclude 처리
3. empty/binary/too_large/no_parse 처리 규칙 반영

검증 포인트:
- parse_status=skipped → meta 유지
- return None은 hard exclude
- content empty → no_parse

---

## 4) Adapter/Wrapper 단계
1. 기존 Indexer 내부 로직을 `Parser` wrapper로 래핑
2. 기존 ParserFactory → ParserRegistry 어댑터
3. SQLite sink, Engine sink 어댑터 구현

검증 포인트:
- 기존 결과와 동등한 parse_status/ast_status
- 기존 스펙과 응답 포맷 유지

---

## 5) Validator 단계
1. ValidationResult 규칙 구현
2. 실패 시 Orchestrator가 parse_status=failed 전환

검증 포인트:
- 필수 필드/형식 검증 통과/실패 정확

---

## 6) 통합 단계 (Indexer 교체)
1. Indexer에서 pipeline 호출로 교체
2. dual-write/engine 동기 갱신 연결

검증 포인트:
- 경로 검색/본문 검색 동작 유지
- root boundary 위반 시 ERR_ROOT_OUT_OF_SCOPE

---

## 7) 롤백/플래그 단계
1. 레거시 파서 강제 플래그
2. pipeline on/off 플래그

검증 포인트:
- 플래그로 즉시 롤백 가능

---

## 8) 문서/테스트 단계
1. 테스트 스위트 갱신
2. 문서 체크리스트 업데이트

---

## 완료 기준 (DoD)
- 계약 테스트 전부 통과
- 인덱서 파이프라인 옵션 플래그 정상 동작
- parse/ast status 의미론 유지
