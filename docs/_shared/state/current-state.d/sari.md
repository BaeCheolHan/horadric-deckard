# sari current-state

**신규 발견**: 검색 엔진 레지스트리/인터페이스를 추가하고 SQLite 엔진을 어댑터로 연결함
**영향**: 엔진 분리 토대 확보, 기존 검색 동작은 유지
**다음 액션**: 신규 엔진 추가 시 EngineRegistry에 등록

**신규 발견**: HTTP 검색에서 total_mode/root_ids 입력을 수용하고 status에 실제 바인딩 포트 노출
**영향**: 포트 충돌 시 실제 포트를 클라이언트가 확인 가능, root_ids 범위 제어 가능
**다음 액션**: HTTP 검색 root_ids 파라미터 문서화

**신규 발견**: legacy 경로 읽기/검색 허용을 위해 DB에 legacy 경로 감지 경로를 추가함
**영향**: 과거 DB 사용 시 read/search가 정상 동작
**다음 액션**: legacy 경로 혼재 시 동작 범위 점검

**신규 발견**: Codex MCP initialize에서 rootUri/workspaceFolders가 null로 전달됨 (로그 확인)
**영향**: MCP가 설치 경로를 workspace_root로 잡아 indexed_files=0 발생
**다음 액션**: proxy startup 로그로 CWD/argv/env 전달 여부 확인

**신규 발견**: 개선안 문서에 구현 스케일(S1/S2) 산정과 P1 상세 계획, 프레이밍 테스트 시나리오를 정리함
**영향**: 구현 범위/위험/검증 기준이 명확해져 우선순위 결정이 쉬워짐
**다음 액션**: P1 항목의 실제 변경 파일/LOC를 확정하고 실행 승인 여부 결정

**신규 발견**: install.py에 데몬 프로세스 탐지/종료와 config.toml 혼용 경고를 추가함
**영향**: 설치본/레포 혼용으로 인한 MCP 프로토콜 불일치 재발 방지
**다음 액션**: 설치 후 안내 문구가 실제 config 상태를 정확히 경고하는지 확인

**신규 발견**: install.py를 fresh clone 방식으로 변경하고 .git을 제거해 macOS provenance/권한 이슈를 회피함
**영향**: 설치 경로 업데이트는 항상 재클론으로 수행되며 git pull 기반 업데이트는 불가
**다음 액션**: 재설치 시 기존 설치 경로 제거가 허용되는지 사용자 안내 필요

**신규 발견**: install.py가 Codex project config를 자동 수정해 배포 경로로 통일하도록 개선됨
**영향**: 설치 후 혼용 경고/수동 설정 단계가 줄어 안정성이 향상됨
**다음 액션**: 설치 경로 삭제/재클론이 허용되는 환경인지 확인 필요

**신규 발견**: bootstrap.sh에 self-install/update 로직을 추가해 설치본으로 자동 전환되도록 함
**영향**: repo bootstrap 호출 시 설치본 동기화가 자동 수행되어 1단계 사용성이 개선됨
**다음 액션**: config에 bootstrap 경로를 어떤 기준으로 안내할지 문구 정리 필요

**신규 발견**: bootstrap.sh가 설치본 VERSION과 repo tag를 비교해 필요 시 재설치하도록 개선됨
**영향**: config가 repo bootstrap을 가리켜도 설치본이 자동 동기화되어 1단계 사용이 가능해짐
**다음 액션**: Claude Desktop 안내 문구가 repo/bootstrap 통일 정책과 충돌하지 않는지 확인

**신규 발견**: bootstrap.sh에 uninstall 명령과 README에 경로/삭제 가이드를 추가함
**영향**: 설치본 경로와 제거 방법이 명확해져 운영 편의성이 개선됨
**다음 액션**: uninstall이 project config를 CWD 기준으로 제거하는 점을 문서로 확인

**신규 발견**: Sari 레포지토리의 핵심 아키텍처(하이브리드 검색, 델타 인덱싱, MCP 도구 구조)를 분석함
**영향**: 프로젝트 구조와 주요 기능 구현 방식을 파악하여 향후 유지보수 및 확장 기반 마련
**다음 액션**: 분석 보고서(docs/sari/api/analysis.md) 기반으로 구체적인 개선 사항 도출

**신규 발견**: `sari/main.py`(CLI/MCP 진입), `sari/core/main.py`(HTTP+인덱서), `sari/mcp/{server,daemon,proxy}.py`(MCP 경로) 중심의 런타임 흐름을 정리함
**영향**: 데몬/프록시/서버 연결 구조와 인덱싱 파이프라인의 역할 분리가 명확해짐
**다음 액션**: `docs/sari/plan/plan-20260206-01.md` 기반으로 운영 시나리오 점검

**신규 발견**: MCP 서버 `transport` 초기화 누락, Tantivy `id/doc_id` 키 불일치, SQLite FTS row 매핑 불일치를 수정하고 회귀 테스트를 추가함
**영향**: MCP stdio 런루프 크래시와 검색 인덱스 반영/FTS fallback 오류 재발 위험이 낮아짐
**다음 액션**: `sari/mcp/test_server.py` 레거시 테스트를 현재 패키지 경로 기준으로 정비

**신규 발견**: `pyproject.toml`의 `tantivy` 의존성을 `==0.20.0`으로 고정하고, 런타임/의존성 드리프트 게이트 테스트(`tests/test_runtime_gates.py`)를 추가함
**영향**: 버전 드리프트로 인한 엔진 초기화 회귀를 CI 단계에서 조기 탐지 가능
**다음 액션**: 배포 파이프라인에 `tests/test_runtime_gates.py`를 필수 게이트로 포함

**신규 발견**: MCP 서버 응답 쓰기 구간에 `_stdout_lock` 직렬화를 적용하고 병렬 쓰기 race 회귀 테스트를 추가함
**영향**: 동시 요청 처리 시 Content-Length 프레임 섞임으로 인한 프로토콜 오류 위험이 낮아짐
**다음 액션**: stdio 기반 클라이언트 연동 스모크에서 병렬 요청 시나리오를 주기적으로 점검

**신규 발견**: `gate` 마커를 도입하고 CI 워크플로우(`ci-gates.yml`, release validate)에 `pytest -m gate` 필수 단계를 추가함
**영향**: 치명 런타임 경로(초기화/동시성/의존성)가 커버리지 수치와 무관하게 배포 전 차단됨
**다음 액션**: 신규 버그 수정 시 관련 테스트를 `@pytest.mark.gate`로 승격하는 규칙을 유지

**신규 발견**: 데몬 포워딩을 요청당 신규 소켓 생성에서 재사용 연결(락 기반)으로 개선하고 shutdown에서 transport/logger/daemon 소켓 정리를 보강함
**영향**: 다건 요청 시 핸드셰이크 오버헤드가 줄고, 종료 시 리소스 누수 위험이 낮아짐
**다음 액션**: daemon 재연결 실패/복구 시나리오를 장기 부하 테스트에 포함

**신규 발견**: `WorkspaceManager.normalize_path`/`_normalize_path`의 루트 문자열 보존과 `_util`의 traversal 차단 검증을 추가함
**영향**: `subpath of ''` 계열 경로 판별 오류와 workspace 외부 접근 가능성을 줄임
**다음 액션**: 파일 접근 계층(read_file/search_symbol)에서 보안 경계 검증 로그를 통합

**신규 발견**: Mock 의존을 줄이기 위해 실제 framed I/O 기반 통합 게이트(`tests/test_mcp_integration_gate.py`)와 로컬 강제 스크립트(`scripts/verify-gates.sh`)를 추가함
**영향**: CI 이전 로컬 단계에서도 치명 런타임 회귀를 차단하고, 모킹으로 가려지던 결함 탐지력이 개선됨
**다음 액션**: 신규 서버/통신 기능 추가 시 통합 게이트 케이스를 먼저 작성하도록 규칙화
