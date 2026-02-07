# local-search 분리 및 npm 패키징 진행상황 (2026-01-31)

## 대상/범위
- 대상: `codex-forge` 문서 보강
- 범위: 계획 문서 보완(스케일/스펙/테스트/리스크), 실행 준비 전 단계

## 이번 세션 진행
- 계획 문서 보강: `plan-local-search-separation-20260131.md`
- npx/postinstall 동작 제약(옵트인/백업/충돌 처리)과 실행 경로 규칙 명시
- Python 런타임/의존성(`requirements.txt`) 명시 필요성 추가
- 체크리스트를 실행 가능한 작업 항목으로 세분화
- Serena MCP 표기 통일, `<org>` 플레이스홀더로 정리

## 결정사항
- 자동 설정 수정은 기본 OFF, `AI_LOCAL_SEARCH_CONFIG_WRITE=1`일 때만 수행
- 서브모듈 마이그레이션은 삭제 대신 백업 이동
- MCP 설정 섹션의 응답은 “결과(설정 반영 후 기대 상태)”로 표기

## 미완료/다음 단계
- 마이그레이션 가이드 초안 작성
- postinstall 상세 사양서(충돌/백업/옵트인) 분리 문서화
- Python 의존성 설치/검증 흐름 확정(install.sh 또는 README에 명시)

## 리스크/오픈 이슈
- npx 캐시 설치 시점과 postinstall 실행 타이밍 혼란 가능
- Python 런타임 미설치 환경에서의 실패 메시지/가이드 정책 필요
- 기존 MCP 설정 충돌 시 우선순위/병합 규칙 확정 필요

## 참고 문서
- `docs/codex-forge/plan/plan-local-search-separation-20260131.md`
