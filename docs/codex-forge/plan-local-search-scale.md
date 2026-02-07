# Local Search 대규모 레포 환경 개선 계획

> **작성일**: 2026-01-30
> **목표**: 레포 수(30+)와 레포 크기 증가 시에도 검색 정확도/속도/안정성을 유지한다.

## 1. 문제 정의
- 레포 수와 파일 수가 커질수록 **인덱싱 시간**, **DB 크기**, **검색 지연**이 증가.
- `total/has_more`가 후처리 필터와 분리되어 **정확도가 떨어짐**.
- 페이지네이션이 **결정적 정렬을 보장하지 않아** 중복/누락 위험.

## 2. 개선 목표
1) **SQL 레벨 필터링 강화**로 후처리 비용 축소
2) **결정적 정렬/페이지네이션 안정화**
3) **인덱스/캐시 전략 도입**으로 대규모 환경 성능 확보
4) **통계/상태 비용 분리**로 status 응답 지연 최소화

## 3. 개선 전략 (우선순위)

### 3.1 쿼리/필터링 최적화 (P1)
- file_types/path_pattern/exclude_patterns 중 **SQL로 옮길 수 있는 필터는 최대한 WHERE로 이동**.
- path_pattern은 glob 대신 **전처리된 prefix/suffix**로 변환해 SQL LIKE로 1차 축소.
- exclude_patterns는 공통 prefix가 있는 경우 SQL NOT LIKE로 1차 배제 후, Python에서 정밀 필터.
  - **전환 기준**: false-positive가 허용 가능한 1차 필터만 SQL에 적용하고, 최종 정확성은 Python에서 보장.
  - **변환 규칙(초안)**:
    - `src/**/test*.py` → `path LIKE 'src/%test%.py'`
    - `**/docs/*.md` → `path LIKE '%/docs/%.md'`
  - **정확도 보장**: SQL 필터는 축소만 수행, 최종 포함 여부는 기존 파이썬 필터로 확정.

### 3.2 정렬/페이지네이션 안정화 (P1)
- **정렬 기준 고정**: `score DESC, path ASC, mtime DESC` 등으로 tie-breaker 명시.
  - FTS: `score DESC, path ASC, mtime DESC`
  - LIKE/Regex: `score DESC, path ASC, mtime DESC`
- **total 정책 명시**:
  - **정확 total 모드**: 필터 적용 후 total 계산(쿼리 2회 or `COUNT(*) OVER()`).
  - **근사 total 모드**: 대규모 환경에선 `approx_total`로 명시(정확도 플래그 제공).
- **has_more/next_offset**: **정확 total**일 때만 신뢰, 근사 모드에서는 `approx_has_more`로 분리.

### 3.3 인덱스 전략 개선 (P2)
- repo별 인덱스 또는 **repo 범위 파티셔닝** 고려.
- 레포가 많은 경우 **repo 단위 캐시**(최근 검색/최근 repo) 적용.
- FTS 테이블에 **repo 컬럼 인덱스** 또는 접근 최적화 확인.
  - **적용 기준(초안)**:
    - 레포 ≥ 30 또는 파일 ≥ 100k → repo 파티셔닝/캐시 검토 시작
    - 레포 ≥ 60 또는 파일 ≥ 300k → 파티셔닝 적용 우선 검토

### 3.4 상태/통계 비용 분리 (P2)
- `status` 기본 응답은 경량 유지.
- `details=1`에서만 `repo_stats` 계산.
- `repo_stats`는 **TTL 캐시**(예: 30~60초)로 재계산 비용 제한.
  - **무효화 기준(초안)**: 인덱서 스캔 완료 시 캐시 갱신, TTL 만료 시 재계산.

## 4. 구현 범위/스케일 산정
- **대상 repo**: `codex-forge`
- **변경 파일(예상 3~5)**:
  - `.codex/tools/local-search/app/db.py`
  - `.codex/tools/local-search/mcp/server.py`
  - (선택) `.codex/tools/local-search/app/indexer.py`
  - (선택) `.codex/tools/local-search/README.md`
- **예상 규모**: S1~S2 (쿼리/스키마 변경 규모에 따라 변동)
- **변경 유형**: DB 쿼리/정렬/응답 스키마/캐시 로직

## 5. API/응답 영향 (요약)
- `search` 응답의 `total/has_more/next_offset` 정확성 향상.
- `status`의 `repo_stats`는 옵션화 + 캐시.
- 경고/힌트는 규모 기준으로 제공(대량 결과일 때만).

## 6. 테스트 시나리오
1) **대규모 스캔**: 30+ 레포, 100k 파일 환경에서 인덱싱 시간 측정.
2) **정렬 안정성**: 동일 쿼리 페이지 이동 시 중복/누락 여부 확인.
3) **필터 정확성**: file_types/path_pattern/exclude_patterns 적용 시 total/has_more 일치 확인.
4) **status 비용**: details=0과 details=1 응답 시간 비교.
5) **회귀 테스트**: 기존 소규모 워크스페이스에서 성능/정확성 유지 확인.

## 6.1 결정 기준 (Policy)
### 6.1.1 정책 수치(조정안)
- **Small**: 레포 ≤ 20, 파일 ≤ 50k → 정확 total 기본
- **Medium**: 레포 21~50, 파일 50k~150k → 정확 total 조건부
- **Large**: 레포 > 50 또는 파일 > 150k → 근사 total 기본
- **파티셔닝 검토 시작**: 레포 ≥ 40 또는 파일 ≥ 200k
- **파티셔닝 적용 우선**: 레포 ≥ 80 또는 파일 ≥ 500k

### 6.1.2 total 정책
- **정확 total 사용 조건**:
  - 결과 수 추정 ≤ 20k 또는
  - 필터가 단순(file_types 단독, path_pattern 없음)일 때
- **근사 total 사용 조건**:
  - 결과 수 추정 > 20k 또는
  - 복합 필터(path_pattern + exclude_patterns 등)일 때
- **페이지네이션 안정성**: 정렬 기준이 모든 모드에서 동일해야 함 (FTS/LIKE/Regex 공통)

## 6.2 “정확 total vs 근사 total” API 응답 필드 설계
### 6.2.1 search 응답 확장
```json
{
  "total": 1234,
  "total_mode": "exact",
  "has_more": true,
  "next_offset": 10,
  "approx_total": null,
  "approx_has_more": null,
  "meta": {
    "total_source": "post_filter_count",
    "estimate_method": null
  }
}
```

### 6.2.2 근사 모드 예시
```json
{
  "total": 5000,
  "total_mode": "approx",
  "has_more": null,
  "next_offset": 10,
  "approx_total": 5000,
  "approx_has_more": true,
  "meta": {
    "total_source": "pre_filter_count",
    "estimate_method": "sampled_scan"
  }
}
```

### 6.2.3 필드 설명
- **total_mode**: `exact` | `approx`
- **total**: exact일 때 실제 값, approx일 때 추정값(=approx_total)
- **has_more**: exact일 때만 신뢰, approx일 때 null
- **approx_total/approx_has_more**: 근사 모드에서만 사용
- **meta.total_source**: `post_filter_count` | `pre_filter_count`
- **meta.estimate_method**: `sampled_scan` | `fts_count` | `like_count`

## 6.3 파티셔닝 설계안 (스키마/마이그레이션)
### 6.3.1 스키마 옵션
**옵션 A: DB 분리(권장)**  
- repo별 SQLite DB 생성 (`index-<repo>.db`)  
- 검색 시 repo 미지정이면 병렬 조회 후 상위 결과 병합  

**옵션 B: 단일 DB + 파티션 테이블**  
- `files_<repo>` 테이블로 분리(자동 생성)  
- FTS 테이블도 repo별 분리 필요  

### 6.3.1-1 옵션 비교표
| 항목 | 옵션 A: DB 분리 | 옵션 B: 단일 DB 파티션 |
|---|---|---|
| 구현 난이도 | 중 | 상 |
| 운영 복잡도 | 중 (DB 다수) | 상 (스키마/FTS 복잡) |
| 성능 격리 | 높음 | 중 |
| 롤백 용이성 | 높음 | 중 |
| repo 미지정 검색 | 병렬 병합 필요 | 단일 쿼리 가능 |

### 6.3.2 마이그레이션 전략
- **Phase 0**: 현행 DB 유지 (호환 모드)
- **Phase 1**: 새로운 인덱서가 repo별 DB 생성
- **Phase 2**: 검색 시 repo 지정 → repo DB 우선
- **Phase 3**: repo 미지정 쿼리는 병합(상위 N만)
- **Phase 4**: 충분히 안정화되면 기존 단일 DB 폐기

### 6.3.3 마이그레이션 체크포인트
- 기존 DB 읽기 유지(롤백 가능)
- repo별 DB 생성 완료 후 비교 검증(샘플 쿼리 20개)
- 성능 메트릭(쿼리 p95, 인덱싱 시간) 비교 후 전환
- 실패 시 롤백 경로 명시(단일 DB 복귀)

## 6.4 테스트 체크리스트(확장)
- **정합성**: 동일 쿼리 결과가 단일 DB vs 분리 DB에서 동일 상위 50개
- **성능**: 쿼리 p95, 인덱싱 시간, DB 크기 비교
- **회귀**: 소규모 환경에서 결과/성능 동일
- **롤백**: 분리 DB 비활성화 후 정상 동작 확인

## 6.5 작업 티켓화(초안)
1) **T-01**: [v] 정렬 기준 고정 및 pagination 안정화 (2026-01-31)
2) **T-02**: [v] total/approx total 응답 필드 도입 (2026-01-31)
3) **T-03**: [v] SQL 1차 필터링 적용(path/type/exclude) (2026-01-31)
4) **T-04**: [v] status repo_stats 캐시 + details 옵션 (2026-01-31)
5) **T-05**: 파티셔닝 옵션 A 프로토타입
6) **T-06**: 대규모 환경 성능 측정 리포트 작성

## 7. 리스크 및 완화
- SQL 필터 강화 시 **성능/정확성 트레이드오프** 발생 가능 → 단계적 적용 + 측정.
- 캐시 도입 시 **정합성 지연** 가능 → TTL 및 무효화 전략 명시.
- 스키마 변경 시 **기존 DB 마이그레이션** 필요 가능 → 마이그레이션 계획 포함.

## 8. 단계적 적용 계획
1) 정렬 고정 + total/has_more 정확화
2) SQL 필터링 1차 적용
3) status repo_stats 캐시
4) repo 파티셔닝/캐시 확장
