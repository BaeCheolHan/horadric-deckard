# codex-forge 분석 메모 (2026-01-31)

## 범위
- 대상: `codex-forge` 레포 + 워크스페이스 `.codex` 산출물(규칙/도구)
- 목적: Codex 룰의 현실성/실용성 평가, local-search 성능/구조 점검
- 근거 파일:
  - `codex-forge/README.md`
  - `codex-forge/docs/_meta/PROJECT_OVERVIEW.md`
  - `codex-forge/docs/codex-forge/plan/plan-local-search-improvements-20260130.md`
  - `codex-forge/docs/codex-forge/plan/plan-local-search-scale.md`
  - `.codex/rules/00-core.md`
  - `.codex/tools/local-search/README.md`
  - `.codex/tools/local-search/app/db.py`
  - `.codex/tools/local-search/mcp/server.py`

---

## 1) Codex 룰의 현실성/실용성

### 강점 (현장 적용 가능성이 높음)
- **안전/정확성 우선순위**와 **증거 기반 완료 규칙**이 명확해 “추측 완료”를 구조적으로 막음.
- **3단계 승인 게이트**( /code → repo 지정 → 스케일 고지 )는 MSA/멀티레포 환경에서 실수 범위를 줄이는 데 실용적.
- **Local Search 우선 원칙**은 토큰/탐색 비용을 명시적으로 줄이는 실행 가이드로 현실적.
- **스케일 규칙(S0~S3 + 하드캡)**이 과도한 변경을 방지하고, 작업 범위를 명확히 만드는 장치로 유효.

### 현실적 부담/마찰 지점
- **기본 Plan-only + 승인 3단계**는 소규모 수정에도 커뮤니케이션 비용이 큼.
  - 팀/리뷰 중심 환경에서는 유효하지만, 단독 개발자나 빠른 반복에는 체감 비용이 높을 수 있음.
- **문서 저장 의무(분석/설계)**는 조직 관점에서는 실용적이나, 작은 탐색성 요청에서도 “문서 경로 강제”가 부담.
- **기본 응답 8줄 제한**은 요약에 강점이 있으나, 복합 이슈 설명 시 정보 손실 가능.
- **SAFE Run 정책**이 안정성에는 좋지만, 진단/벤치 수행 시 재확인 루프가 잦아질 수 있음.

### 요약 판단
- MSA/팀 협업 기준으로는 **현실성 높음**, 개인/속도 우선 환경에서는 **운영 부담**이 생길 수 있음.
- 룰 자체는 일관되고 실용적이지만, “빠른 반복” 모드에 대한 명시적 경감 규정이 부족함.

---

## 2) local-search 성능/구조 분석

### 현재 구조 요약
- **SQLite + FTS5** 기반 인덱싱/검색 (FTS 실패 시 LIKE 폴백).
- **옵션 기반 필터**(file_types, path_pattern, exclude_patterns, recency_boost, regex)
- **MCP 서버**에서 `total_mode`를 규모에 따라 `exact/approx`로 결정.

### 성능상 유리한 점
- FTS 도입으로 **본문 검색 성능** 확보.
- `file_types`/`path_pattern`은 SQL WHERE로 1차 필터링.
- **repo_stats TTL 캐시**로 status 비용 완화.

### 성능/정확성 리스크
1) **total_mode가 “approx”여도 실제 COUNT 쿼리를 수행**
   - `db.py`에서 total을 항상 COUNT(*)로 계산 → 대규모 환경에서 병목 가능.
2) **exclude_patterns는 Python에서 후처리**
   - 정확성은 유지되나, 데이터가 큰 경우 `fetch_limit`가 커지고 검색 비용이 증가.
3) **pagination fetch_limit가 offset에 비례**
   - `fetch_limit = (offset + limit) * 2` → 큰 offset 요청 시 비용 급증.
4) **정렬 기준 일관성 문제 가능**
   - SQL 단계 정렬 + Python 리랭킹 혼합으로 “페이지 이동 시 결과 흔들림” 가능성 존재.

### 성능 개선 메모 (현 구조 기준)
- **approx 모드일 때 COUNT 생략** (estimated count 또는 샘플링 도입) 필요.
- **exclude_patterns의 SQL 1차 필터 도입**을 검토 (false-positive 허용 후 Python 확정).
- **offset 기반 대량 fetch 제한** (max fetch cap + “deep pagination 경고”).
- “정렬 기준 고정 + 결정적 pagination”을 server/db에서 일관되게 정의.

---

## 3) 추가 확인이 필요한 항목
- 실제 워크스페이스에서 **대규모 인덱싱 시간/쿼리 p95** 측정값
- repo 파티셔닝(옵션 A/B) 필요 여부 판단을 위한 **파일 수/레포 수 분포**
- FTS bm25 score 해석과 Python 리랭킹 간 **순위 역전 영향**

---

## 4) 제안되는 다음 액션 (선택)
1) T-06 성능 측정 리포트 수행 (대규모 레포 환경 데이터 확보)
2) total_mode=approx 시 COUNT 생략/샘플링 설계 확정
3) exclude_patterns 1차 SQL 필터 적용 실험
4) deep pagination 경고/제한 정책 정의

