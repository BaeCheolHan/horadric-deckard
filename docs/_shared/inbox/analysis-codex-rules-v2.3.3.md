# 분석 요약: codex-rules-v2.3.3-workspace-msa (PROD-00001)

- 일자: 2026-01-30
- 범위: `codex-rules-v2.3.3-workspace-msa/` 패키지 구조/룰/도구/문서 정합성 1차 분석
- 목적: Codex용 룰/툴 제작을 위한 기준선 확보 및 이슈 목록화

## 1. 패키지 구성 요약
- 루트: `.codex/`, `docs/`, `.codex-root`, `install.sh`, `uninstall.sh`, `gitignore.sample`, `README.md`
- 진입점: `.codex/AGENTS.md`
- 핵심 규칙: `.codex/rules/00-core.md` (단일 정본)
- 시나리오: `.codex/scenarios/` (S0/S1/S2/Hotfix)
- 로컬서치 도구: `.codex/tools/sari/` (MCP + HTTP 폴백)
- 문서 메타: `docs/_meta/` (SETUP/CHANGELOG/RELEASE/SELF_REVIEW/VERSIONING)
- 지식/상태: `docs/_shared/` (lessons/debt/state/glossary 등)

## 2. 룰/운영 핵심
- 우선순위: P0(안전) > P1(정확성) > P2(범위/비용) > P3(속도) > P4(문서)
- 스케일: S0~S3 + 하드캡(30 files/3000 LOC)
- 3단계 승인: `/code` → repo 지정 → 스케일 고지/확인
- 증거 규칙: Change는 경로+diff, Run은 명령+출력
- Local Search 우선: 파일 탐색 전 MCP search 필수

## 3. 도구 요약 (sari)
- MCP 도구: search/status/repo_candidates
- 검색 옵션 확장: file_types, path_pattern, exclude_patterns, recency_boost, use_regex
- 인덱싱 제외: `.codex/`, `docs/`, `.git`, `node_modules` 등
- 설정: `.codex/config.toml`, `.codex/tools/sari/config/config.json`

## 4. 설치/운영 동선
- 설치: `install.sh` (config.toml 백업/복원, MCP 서버 테스트 포함)
- 제거: `uninstall.sh` (관련 파일/캐시 제거)
- 온보딩: `.codex/quick-start.md`, `docs/_meta/SETUP.md`

## 5. 정합성/버전 이슈 (조치 완료)
- `docs/_meta/CHANGELOG.md` 최신 항목 v2.3.3 추가
- `docs/_meta/SELF_REVIEW.md` 헤더 v2.3.3 및 v2.3.3 리뷰 섹션 추가
- `docs/_meta/RELEASE_CHECKLIST.md` 헤더/예시/경로 v2.3.3 정합화
- `.codex/system-prompt.txt` v2.3.3 표기 반영
- `docs/_meta/VERSIONING.md` 버전 표기 위치 리스트 재정리

## 6. sari 문서/코드 정합성 2차 리뷰
- README 옵션(file_types/path_pattern/exclude_patterns/recency_boost/use_regex/case_sensitive/context_lines) ↔ MCP 스키마/DB SearchOptions 일치
- `context_lines` → `snippet_lines` 매핑 구현 확인
- 인덱싱 제외 디렉토리/파일 설명 ↔ `config.json` 값 정합
- 추가 이슈 없음 (수동 점검)

## 7. 다음 액션 제안
- 릴리스 체크리스트 실행(선택)
- zip 재패키징 및 설치 테스트(선택)

## 7. 참고 경로
- 패키지 루트: `codex-rules-v2.3.3-workspace-msa/`
- 핵심 룰: `codex-rules-v2.3.3-workspace-msa/.codex/rules/00-core.md`
- 설치 문서: `codex-rules-v2.3.3-workspace-msa/docs/_meta/SETUP.md`
- 도구 문서: `codex-rules-v2.3.3-workspace-msa/.codex/tools/sari/README.md`
