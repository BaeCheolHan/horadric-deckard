# [12] 인덱서 최종 설계 점검표 v1

[scope][indexer][final-check]
**목표**: 구현 직전 설계 모순/누락을 최종 제거한다.

---

## A. 의미론/계약 (P0)
- [x] `doc_id = root_id/rel_path` 형식 고정 (root_id 생성 규칙과 일치)
- [x] `return None`은 hard exclude (인덱스에 없음)
- [x] `parse_status=skipped` → meta row 유지 (body_text 비움)
- [x] `max_file_bytes=0` → 무제한
- [x] `include_ext empty` → 필터 미적용
- [x] `parse_reason=excluded`는 soft exclude(allow_metadata_only_ok=true)에서만 사용
- [x] content empty & non-binary → `parse_status=skipped`, `parse_reason=no_parse`
- [x] loader 실패 → `parse_status=failed`, `parse_reason=error`

---

## B. 경로/스코프 (P0)
- [x] root boundary는 Collector에서 제외 처리(roots 밖은 FileItem 미생성)
- [x] root_ids 교집합이 비면 ERR_ROOT_OUT_OF_SCOPE
- [x] legacy path는 read/search만 허용
- [x] rel_path 정규화 규칙(absolute→root-relative) 고정

---

## C. 파서 선택/폴백 (P1)
- [x] category 우선: language > heuristic
- [x] priority 높은 순, 동점은 등록 순
- [x] can_handle는 경량 체크만
- [x] language 실패 → 동일 category 다음 parser → heuristic 폴백
- [x] heuristic 실패 → parse_status=failed, meta 유지

---

## D. Validator (P0)
- [x] 필수 필드 누락 검출
- [x] enum 값 검증
- [x] parse_status=ok이면 body_text 또는 symbols 존재
- [x] preview 길이 상한 준수

---

## E. Sink/Index 동기화 (P1)
- [x] parse_status=skipped/failed는 meta만 기록
- [x] delete는 doc_id 기준 단일 규칙
- [x] engine index와 SQLite 메타 동기 갱신

---

## F. 롤백/플래그 (P1)
- [x] pipeline on/off 플래그
- [x] 레거시 파서 강제 플래그
- [x] 문제 시 즉시 기존 경로 복귀 가능

---

## 완료 기준
- 위 체크 전부 true
- 계약 테스트(P0) 통과

---

## 링크
- SSOT: `plan-20260203-search-engine-devready.md`
- 인터페이스: `plan-20260203-indexer-interface.md`
- 구조: `plan-20260203-indexer-architecture.md`
- 테스트: `plan-20260203-indexer-tests.md`
