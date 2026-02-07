# [01] MASTER INSTRUCTION v6 (압축)
[scope][design][ux]
**신규 발견**: 범위=단일 엔트리포인트/SSOT roots/leader-follower/3단계 수집/검색엔진 분리(embedded) 포함
**영향**: Non-Goals에서 “검색 엔진 교체”는 제거(엔진 분리는 범위)
**다음 액션**: 상세는 `plan-20260203-search-engine-devready.md`, `plan-20260203-search-engine-spec.md`, `plan-20260203-search-engine-separation.md`, `plan-20260203-search-engine-review.md` 참조
[contract][cli][transport]
**신규 발견**: `sari` 무인자= MCP stdio, PACK1 기본, `--cmd`는 CLI 경로
**영향**: `--transport http` 미지원 시 `ERR_MCP_HTTP_UNSUPPORTED` 반환
**다음 액션**: HTTP API 포트는 auto(실패 시 port=0 재시도) 전략 유지
[config][roots][security]
**신규 발견**: SSOT config + roots union, legacy 1회 이전, marker 제거, root boundary 강제
**영향**: roots는 config/env/rootUri+cwd fallback로 결정, 범위 밖 접근은 ERR_ROOT_OUT_OF_SCOPE
**다음 액션**: root 정책과 경로 표준은 단일 SSOT로 고정
[indexer][data][policy]
**신규 발견**: leader/follower 락 + PACK1 단일 레코드 에러 + 3단계 수집/size profile 확정
**영향**: follower/off 모드 인덱싱 트리거 차단, parse/ast 상한 정책 고정
**다음 액션**: 체크리스트는 `.codex/rules/03-gate.md` 준수

[decisions][net][port]
**신규 발견**: auto 포트 실패 시 즉시 port=0 재시도(B 고정)
**영향**: 포트 스캔 제거로 경쟁 조건 안정/구현 단순화
**다음 액션**: 문구 고정(“auto: 지정 포트 실패 시 즉시 port=0으로 재시도”)

[decisions][size][profile]
**신규 발견**: size profile 확정=DECKARD_SIZE_PROFILE=default|heavy (explicit override 우선)
**영향**: parse/ast 상한 프리셋 표준화
**다음 액션**: default(16MiB/8MiB), heavy(40MiB/40MiB), DECKARD_MAX_* 우선

[decisions][indexer][errors]
**신규 발견**: follower/off 모드 rescan/index_file 에러는 PACK1 단일 레코드로 통일
**영향**: 클라이언트 파서 단순화
**다음 액션**: ERR_INDEXER_FOLLOWER / ERR_INDEXER_DISABLED + mode 필드 포함

[decisions][config][migrate]
**신규 발견**: SSOT 경로 1회 자동 이전(legacy→SSOT 복사 + .bak + 로그)
**영향**: UX 단순화, 예측 가능
**다음 액션**: legacy 후보 2개만 허용(기존 경로 + 이전 SSOT 1개)

[decisions][roots][marker]
**신규 발견**: .codex-root marker 탐지/생성 모두 제거
**영향**: roots는 config/env 입력만으로 결정
**다음 액션**: init 단계 marker 생성 제거

[decisions][entrypoint]
**신규 발견**: 단일 엔트리포인트=console script sari, python -m sari 지원
**영향**: 설치 경로/venv 이슈에 대한 탈출구 확보
**다음 액션**: README/문서에 동시 명시

[decisions][config][auto-install]
**신규 발견**: MCP 설정은 수동 등록, 실행 시 네트워크 설치(B) 허용
**영향**: install.py가 설정 파일 자동 수정 금지
**다음 액션**: 설정 블록 예시를 README/문서에 고정

[checklist][prep]
**신규 발견**: 작업 준비 체크리스트
**영향**: 착수 전 요건 누락 방지
**다음 액션**:
- [ ] SSOT/Spec/Decisions/Review 동기화
- [x] PACK1 에러 포맷 통일(leader/follower/off)
- [x] size profile/env 우선순위 명시
- [x] root boundary 적용 범위 확정
- [x] entrypoint/transport 동작 문서화

[checklist][impl]
**신규 발견**: 구현 진행 체크리스트(SSOT 기준)
**영향**: 구현 누락 방지 및 진행률 가시화
**다음 액션**:
- [x] 엔진 인터페이스/Registry 추가 및 기본 엔진 분기(embedded/sqlite)
- [x] embedded 엔진 스켈레톤(install/status/rebuild) + index_version 기록
- [x] SearchRequest 매핑(root_ids/total_mode) + 엔진 메타 응답
- [x] tool registry + ToolContext 도입
- [x] indexer 엔진 인덱스 동기 갱신(path_text/body_text)
- [x] 엔진 메모리/threads 클램프 적용 및 노출
- [ ] 컷오버/validate 절차(verify) 구현 강화
- [ ] 95% coverage 테스트 스위트 재작성
- [ ] 메모리/누수 테스트 설계 및 추가
- [ ] 엔진 패키지명/버전 핀 정책 반영(`sari-search`, major/minor 동일)
- [ ] tokenizer 사전 배포 정책 반영(번들, 누락 시 latin fallback)
- [ ] ERR_ENGINE_* 메시지 템플릿 반영
- [ ] 인덱서 구현 순서표 반영 (`plan-20260203-indexer-impl-order.md`)
- [ ] 인덱서 최종 설계 점검표 완료 (`plan-20260203-indexer-final-checklist.md`)
- [ ] 인덱서 계약 테스트 스켈레톤 반영 (`plan-20260203-indexer-contract-tests.md`)
- [x] PyPI 표준 패키징(pyproject/entrypoints) 설계 및 문서화
- [x] 계약 테스트 우선순위/범위 정의(검색/상태/마이그레이션/필터 의미론)
- [ ] 인덱서 아키텍처 개선 설계(파이프라인 분리/Parser 인터페이스/Policy)
