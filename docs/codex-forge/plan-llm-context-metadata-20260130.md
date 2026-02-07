# LLM 판단 메타 강화 계획 (2026-01-30)

## 배경
- local-search 결과는 있지만, LLM이 “왜 이런 결과인지/얼마나 믿을 수 있는지” 판단할 메타가 부족함.
- 0결과/스코프/필터 혼동이 반복됨.

## 목표
- 결과에 “판단 근거 메타”를 충분히 포함하여 LLM이 올바른 다음 행동을 선택하도록 한다.
- 0결과 시 재시도 가이드가 즉시 제공되도록 한다.

## 비목표
- 검색 랭킹/스코어링 알고리즘 변경
- 인덱싱 범위 정책 변경

## 개선 항목
1) **검색 응답 메타 확장**
   - `repo`, `file_types`, `path_pattern`, `exclude_patterns`, `use_regex`, `case_sensitive` 에코
   - `total_mode`(exact/approx), `total_scanned`, `index_ready`, `last_scan_ts` 제공
2) **0결과 힌트 강화**
   - 필터 제거/완화 안내(특히 file_types/path_pattern/exclude)
   - regex 모드 전환 안내
   - repo 스코프 재확인 안내
3) **인덱스 범위 가시화**
   - include_ext/include_files/exclude_dirs/exclude_globs 및 숨김 디렉토리 포함 여부 노출
4) **repo 후보 정보 강화**
   - top_candidate_repos + repo별 파일 수/우선순위 표기

## 구현 범위(가이드)
- `.codex/tools/local-search/mcp/server.py` (응답 메타 구성)
- `.codex/tools/local-search/app/db.py` (status/통계 제공 확장)
- `.codex/tools/local-search/README.md`, `docs/_shared/local-search/README.md` (문서 반영)

## 스케일/예상 변경
- S1 예상 (코드 2~3파일 + 문서 1~2파일)
- LOC 대략 100~250

## 테스트 시나리오
- 0결과에서 힌트가 즉시 제공되는지 확인
- 스코프/필터 에코가 응답에 포함되는지 확인
- index_ready/last_scan_ts가 status와 일치하는지 확인

## 리스크/대응
- 메타 과다로 응답이 커짐 → 기본/상세 모드 분리 고려
- 메타 불일치 시 혼란 → 단일 소스(status) 기반으로만 출력

## 롤백
- 응답 메타 항목 추가를 되돌림
- 문서 변경만 되돌림 가능

---

## 다음 세션 이어서 할 일
- 목표 범위 확정: “문서만” vs “코드+문서”
- 메타 항목 우선순위 정리(필수/선택)
- 기존 status 응답 필드 점검 및 정합성 확인
- 테스트 케이스 추가 여부 결정
