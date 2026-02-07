# local-search 개선 플랜 (v2.5.1, 2026-01-30)

## 배경
- status/검색 메타의 정확도 표기(approx/exact)와 실제 계산 방식 간 괴리 가능성
- 대규모 워크스페이스에서 COUNT 비용 부담 가능
- 신규 테스트가 OS별 파일 잠금 이슈 가능

## 목표
- total/approx 정확도 표기와 실제 계산 비용을 일치시킨다.
- 대규모 스케일에서 검색 메타 계산 비용을 줄인다.
- 테스트의 OS 호환성을 확보한다.

## 비목표
- 랭킹 알고리즘 변경
- 인덱싱 범위 정책 변경

## 개선 항목
1) **total_mode 의미 정합성**
   - `approx`일 때 COUNT 생략 or 샘플 기반 추정
   - 응답에 `total_mode`/`approx_total`/`is_exact_total` 일관 표기
2) **대규모 스케일 성능**
   - COUNT 조건부 실행(스케일 기준)
   - repo_stats 캐시 TTL 정책 및 무효화 타이밍 명확화
3) **테스트 안정화**
   - `NamedTemporaryFile` → `TemporaryDirectory` 기반 DB 파일 생성
   - Windows 잠금 이슈 회피

## 구현 범위(가이드)
- 코드: `.codex/tools/local-search/app/db.py`, `.codex/tools/local-search/mcp/server.py`
- 테스트: `tests/test_search_v2.py`
- 문서: `.codex/tools/local-search/README.md` 또는 `docs/_shared/local-search/README.md`

## 스케일/예상 변경
- S1 예상 (코드 2~3파일 + 테스트 1파일)
- LOC 대략 80~200

## 테스트 시나리오
- total_mode=approx일 때 COUNT 없이도 정상 응답(경고/메타 포함)
- total_mode=exact일 때 COUNT가 정확히 반영됨
- Windows/WSL 환경에서 test_search_v2 실행 성공

## 리스크/대응
- approx 계산이 사용자 혼란 유발 가능 → 응답에 명확한 경고 포함
- 캐시 TTL로 인한 stale 값 → rescan 후 캐시 무효화 확인

## 롤백
- 기존 total 계산 로직 복원
- 테스트 변경만 되돌림 가능
