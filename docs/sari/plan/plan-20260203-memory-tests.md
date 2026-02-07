# [07] 메모리/누수 테스트 계획 v1

[scope][tests][perf]
**목표**: 인덱싱/검색/엔진 재빌드 반복 시 메모리 누수 징후를 조기에 탐지한다.
**원칙**: 빠른 단위 테스트 기준(수 초), 가벼운 입력으로 반복, 추정치 기반 경계값을 둔다.
**한계**: `tracemalloc`은 Python 레벨 할당만 추적하며, OS/네이티브 메모리(예: Rust/tantivy)는 부분적으로만 관측된다.

---

## 1) 테스트 종류

### A. 검색 반복(툴 레벨)
- 대상: `mcp.tools.search.execute_search`
- 방법: 같은 쿼리를 100~200회 반복
- 측정: `tracemalloc` 스냅샷 차이
- 기준: 누적 증가량 < 2MB (단위 테스트 기준)

### B. embedded 엔진 재빌드 반복
- 대상: `app.engine_runtime.EmbeddedEngine`
- 방법: `install → upsert → rebuild` 3~5회 반복
- 측정: `tracemalloc` 스냅샷 차이
- 기준: 누적 증가량 < 5MB (단위 테스트 기준)

### C. DB/인덱서 반복(확장)
- 대상: `LocalSearchDB` / `Indexer` (향후)
- 방법: 대량 upsert/scan 반복
- 측정: `tracemalloc` + GC 후 스냅샷
- 기준: 누적 증가량 < 10MB (통합 테스트 기준)

---

## 2) 리스크 및 대응
- **네이티브 메모리 누수**: `tracemalloc`으로 감지 불가
  - 대응: 별도 장시간 프로파일링(옵션) 또는 통합 환경에서 RSS 모니터링
- **플랫폼 변동성**: CI/로컬 환경에서 변동
  - 대응: 작은 반복 횟수 + 느슨한 임계값 사용

---

## 3) 구현 위치
- 테스트 파일: `tests/test_memory_leak.py`
- 유틸: `tracemalloc`, `gc`

---

## 4) TODO
- [ ] 장시간 통합 시나리오(10분 이상)용 별도 스크립트 (`scripts/memory_long_run.sh`)
- [ ] OS RSS 기반 측정(선택) — `ps`/`psutil` 기반 샘플링
