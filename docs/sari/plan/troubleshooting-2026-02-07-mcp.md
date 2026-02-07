# Sari MCP 트러블슈팅 기록 (2026-02-07)

## 목적
- 최근 발생한 `Gemini/Codex MCP 연결 불안정`, `핸드셰이크 실패`, `status Not connected` 이슈를 재현 가능한 형태로 정리한다.
- 동일 증상 재발 시 즉시 점검 가능한 체크리스트를 남긴다.

## 기간 및 범위
- 기간: 2026-02-06 ~ 2026-02-07
- 범위: `sari` MCP stdio 연결, 프로토콜 협상, transport 포맷, `search_symbols` 도구 안정성

## 주요 증상
- Codex: `handshaking with MCP server failed: connection closed: initialize response`
- Gemini: 간헐적으로 `status` 호출 시 `Not connected`
- 일부 세션에서 MCP 프로세스는 시작되지만 초기화 응답이 도달하지 않음

## 근본 원인
1. 프로토콜 버전 협상 누락
- Codex 클라이언트가 `protocolVersion=2025-06-18`으로 `initialize` 전송
- 서버 지원 버전에 `2025-06-18`이 없어 초기화 에러 경로 발생

2. JSONL/Content-Length transport 모드 불일치
- 일부 클라이언트는 JSONL 형태로 initialize를 보냄
- 서버는 `--format json`이어도 실제 `McpTransport`에 JSONL 허용 플래그를 반영하지 못함

3. `search_symbols` 배선 결함 및 인자 제약
- 레지스트리에서 `search_symbols` 실행 시 logger 인자 누락 가능
- 쿼리/필터 인자가 제한적이라 실제 분석 워크플로우에서 활용도가 낮음

## 적용한 수정
1. MCP 프로토콜 호환 확장
- 파일: `sari/mcp/server.py`
- 변경: `SUPPORTED_VERSIONS`에 `2025-06-18` 추가

2. JSON 모드 transport 실반영
- 파일: `sari/mcp/server.py`
- 변경:
- `SARI_FORMAT=json`일 때 `McpTransport(..., allow_jsonl=True)`로 생성
- JSON 모드 기본 출력 프레이밍을 `jsonl`로 설정

3. `search_symbols` 안정성/기능 강화
- 파일: `sari/mcp/tools/registry.py`
- 변경: 레지스트리 핸들러에서 `ctx.logger` 전달
- 파일: `sari/mcp/tools/search_symbols.py`
- 변경:
- 빈 `query` 시 `INVALID_ARGS` 에러 명시 반환
- `limit` 범위 보정(1~200)
- `root_ids` 필터 처리(허용 루트 교집합)
- 신규 필터 인자 처리: `repo`, `kinds`, `path_prefix`, `match_mode`, `include_qualname`, `case_sensitive`
- 파일: `sari/core/db/main.py`
- 변경: `search_symbols()` SQL 필터/매칭 옵션 확장 반영

## 테스트/검증 결과
- `tests/test_server.py` + `tests/test_stability.py`: 통과
- `tests/test_mcp_tools_full.py` 내 `search_symbols` 관련 테스트: 통과
- `codex exec` 런타임 검증: `mcp: sari ready` 확인

## 운영 표준 설정 (권장)
### Codex MCP
- `command`: `/Users/baecheolhan/.local/bin/sari`
- `args`: `--transport stdio --format json`
- `env`:
- `SARI_WORKSPACE_ROOT=/Users/baecheolhan/Documents/repositories`
- `SARI_STANDALONE_ONLY=1`
- `SARI_LOG_LEVEL=INFO`

### Gemini MCP
- `command`: `/Users/baecheolhan/.local/bin/sari`
- `args`: `--transport stdio --format json`
- `env`:
- `SARI_WORKSPACE_ROOT=/Users/baecheolhan/Documents/repositories`
- `SARI_STANDALONE_ONLY=1`
- `SARI_LOG_LEVEL=INFO`

## 재발 시 즉시 점검 체크리스트
1. 설치 버전 확인
- `sari --version`

2. MCP 연결 상태 확인
- Codex: `codex mcp get sari`
- 실행 중 로그: `codex exec "Reply exactly MCP_OK" ...`에서 `mcp: sari ready` 확인

3. 잔존 프로세스/포트 확인
- `lsof -nP -iTCP:47777 -sTCP:LISTEN`
- `lsof -nP -iTCP:47779 -sTCP:LISTEN`

4. 설정 불일치 확인
- `command`가 절대경로(`/Users/baecheolhan/.local/bin/sari`)인지 점검
- `args`가 `--transport stdio --format json`인지 점검
- workspace root가 의도 경로와 일치하는지 점검

5. 디버그 로그 확인 (필요 시)
- `~/.local/share/sari/mcp_debug.log`

## 교훈
- stdio MCP는 클라이언트별 프레이밍(JSONL/Content-Length) 차이를 흡수해야 안정적이다.
- 테스트는 모킹만으로 충분하지 않으며, 실제 핸드셰이크 런타임 검증을 최소 1개 포함해야 한다.
- 도구 사용성(`search_symbols`)은 기능 정확도와 입력 스키마 정합성이 함께 확보되어야 한다.

## 추가 이슈 (2026-02-07, 좀비 프로세스)
### 증상
- `ps`에서 `<defunct>` 상태 프로세스가 간헐적으로 관측됨
- 부모가 `sari --format pack` 또는 daemon helper 프로세스인 경우가 있음

### 원인
1. spawn 후 reap 누락
- 백그라운드 시작 경로에서 `subprocess.Popen(...)`만 호출하고 `wait()`를 수행하지 않아, 자식이 빠르게 종료될 때 좀비가 남을 수 있었음

2. stop 로직 적용 범위 제한
- `daemon stop`은 registry에 기록된 daemon/http PID 중심으로 정리하며, 모든 helper 자식 프로세스를 직접 수거하는 구조는 아님

### 조치
- `sari/sari/main.py`
  - `_spawn_http_daemon()`에서 spawn한 자식을 daemon thread에서 `wait()`하도록 수정
- `sari/sari/mcp/cli.py`
  - `cmd_daemon_start(-d)` 경로에서 spawn한 daemon 자식을 daemon thread에서 `wait()`하도록 수정
- `sari/sari/mcp/proxy.py`
  - `start_daemon_if_needed()` 경로에서 spawn한 helper 자식을 daemon thread에서 `wait()`하도록 수정

### 검증
- 테스트: `python3 -m pytest -q sari/tests/test_daemon_cli_integration.py sari/tests/test_daemon.py` 통과
- 런타임 점검: `ps -axo stat,pid,ppid,command | rg '(^| )Z'` 결과 없음

### 릴리즈 태그 정정
- 이번 조치 기준 버전은 `v0.3.31`
- 기존 잘못 생성된 `v1.2.10` 태그는 사용하지 않음

## 추가 이슈 (2026-02-07, Gemini 프로젝트 로컬 설정)
### 증상
- 동일 머신/동일 바이너리인데 경로별 상태가 달랐음
- `/Users/baecheolhan`에서 `gemini mcp list`는 `sari Connected`
- `/Users/baecheolhan/Documents/repositories`에서만 `sari Disconnected`

### 원인
1. 프로젝트 로컬 `.gemini` 설정의 stderr 리다이렉션 경로 권한 오류
- 기존 로컬 설정은 `bash -lc ... 2>>/Users/baecheolhan/Library/Logs/sari/mcp-stderr.log` 형태였음
- 해당 리다이렉션이 `Operation not permitted`로 실패하면서 `sari` 프로세스 자체가 기동되지 않음

2. 로컬 설정의 환경 변수 불일치
- 전역 설정에는 `SARI_DEV_JSONL=1`이 있었지만, 로컬 `.gemini/settings.json`/`.gemini/config.toml`에는 누락되어 있었음
- Gemini가 로컬 설정을 우선 적용할 때 transport 호환성이 떨어져 연결 실패를 유발

### 조치
- 리다이렉션 래퍼 제거: `bash -lc ... 2>>...` 제거 후 `sari` 직접 실행으로 통일
- 로컬/전역 설정 정합화: `SARI_DEV_JSONL=1`을 프로젝트 로컬 설정에도 추가
- 적용 파일:
  - `.gemini/settings.json`
  - `.gemini/config.toml`

### 검증
- 2026-02-07 09:46 (KST): `/Users/baecheolhan/Documents/repositories`에서 `gemini mcp list` 실행 시 `sari Connected` 확인
- 동일 시점에 `fetch/time/sqlite/playwright`는 별도 의존성 이슈로 `Disconnected`였으나, `sari` 단독 연결은 정상

### 후속 조치 (v0.3.34)
- `SARI_DEV_JSONL` 의존 제거: JSONL fallback 허용을 기본값으로 승격
- 설정 단순화: Gemini/Codex 설정에서 `SARI_DEV_JSONL` 제거 가능
- 변경 파일:
  - `sari/sari/mcp/transport.py`
  - `sari/sari/mcp/proxy.py`
  - `sari/tests/test_stability.py`
  - `sari/tests/test_core_hardened.py`

### 왜 "기존 프로세스 종료 로직"이 누락될 수 있었는가
- 과거에는 `daemon.pid`와 `server.json`을 함께 참조해 상태 불일치가 발생할 수 있었음
- 현재는 `server.json`을 단일 소스(SSOT)로 사용하고, dead daemon 엔트리는 registry pruning으로 정리함
- 따라서 운영 점검도 pid 파일이 아니라 registry 기반 상태/endpoint를 기준으로 수행해야 함

### 좀비 여부 점검 결과
- 2026-02-07 09:44 (KST) 기준 `ps`에서 `STAT=Z`(zombie) 프로세스는 확인되지 않음
- 대신 `python -m sari.mcp.daemon` 형태의 orphan daemon 1개가 추가로 관측됨(좀비가 아닌 살아있는 잔존 프로세스)

## Sari MCP 도구 전체 목록 및 상세 설명
아래 표는 현재 `sari/mcp/tools/registry.py` 기준 등록 도구 23개의 실무 사용 가이드를 정리한 것이다.

| 도구 | 목적 | 주요 입력 | 언제 쓰면 좋은가 | 주의점 |
|---|---|---|---|---|
| `sari_guide` | 에이전트용 표준 워크플로우 안내 | 없음 | 세션 시작 직후, 도구 선택이 애매할 때 | 실제 코드 조회는 하지 않음 |
| `status` | 인덱스/엔진/루트/성능 상태 확인 | `details` | 첫 호출로 시스템 준비 상태 점검 | 연결 전 호출 시 클라이언트에서 `Not connected`가 날 수 있음 |
| `repo_candidates` | 질의와 연관된 레포 후보 제시 | `query`, `limit` | 멀티 레포 환경에서 어디부터 볼지 모를 때 | 후보 추천이므로 확정 정보가 아님 |
| `list_files` | 인덱싱된 파일 목록/요약 제공 | `repo`, `path_pattern`, `file_types`, `limit` | 구조 파악, 범위 축소 | 너무 넓은 패턴은 응답이 커질 수 있음 |
| `search` | 텍스트/패턴 기반 범용 검색 | `query`, `repo`, `file_types`, `path_pattern`, `root_ids` | 분석 시작점, 관련 파일 후보 수집 | `query` 필수. 넓은 질의는 잡음 증가 |
| `search_symbols` | 심볼 중심 탐색 | `query`, `repo`, `kinds`, `path_prefix`, `match_mode`, `root_ids` | 함수/클래스 기준으로 정확히 찾고 싶을 때 | `query` 필수. 인덱싱 품질에 따라 정밀도 차이 |
| `search_api_endpoints` | API 경로 패턴 검색 | `path` | 백엔드 엔드포인트 위치 추적 | 라우팅 규약이 비표준이면 누락 가능 |
| `grep_and_read` | 검색 + 상위 파일 즉시 읽기 | `query`, `limit`, `read_limit`, 각종 필터 | 빠른 맥락 획득, 토큰 절감 | `read_limit`가 크면 컨텍스트 과다 |
| `read_symbol` | 심볼 정의 블록 조회 | `path`, `name` | 함수/클래스 구현만 정밀 확인 | 심볼 메타가 없으면 실패 |
| `read_file` | 파일 전체 본문 조회 | `path` | 최종 확인, 전체 맥락 필요 시 | search 근거 없이 연속 호출하면 비효율 큼 |
| `get_callers` | 특정 심볼의 호출자 조회 | `name` | 영향 범위(누가 호출하는지) 파악 | 호출 그래프 데이터 품질 의존 |
| `get_implementations` | 인터페이스/추상 심볼 구현체 조회 | `name` | 구현 분기 추적 | 언어별 파서 정밀도 차이 |
| `call_graph` | 상/하위 호출 그래프 조회 | `symbol`, `depth`, `include_path`, `exclude_path` | 복잡한 흐름 분석, 리팩터 영향 분석 | 깊이를 크게 주면 응답량 급증 |
| `call_graph_health` | 콜그래프 플러그인 상태 확인 | 없음 | call_graph 결과 이상 시 진단 | 평시 상시 호출 필요 없음 |
| `index_file` | 특정 파일 즉시 재인덱싱 | `path` | 변경 직후 stale 인덱스 의심 시 | 범위를 넓게 처리하려면 `rescan`이 적합 |
| `rescan` | 비동기 전체 재스캔 트리거 | 없음 | 대규모 변경 후 백그라운드 재동기화 | 완료까지 시간 지연 가능 |
| `scan_once` | 동기 단발 스캔 | 없음 | 즉시 완료형 수동 스캔이 필요할 때 | 블로킹 호출이므로 자동 흐름에는 비권장 |
| `doctor` | 환경/포트/DB/엔진 종합 진단 | 진단 옵션들 | 장애 발생 시 1차 진단 | 진단은 복구를 대체하지 않음 |
| `save_snippet` | 코드 조각 저장 | `path`, `tag`, 라인 범위 | 근거 코드 저장, 재사용 메모리 구축 | 태그 전략 없으면 조회 어려움 |
| `get_snippet` | 저장 스니펫 조회 | `tag` 또는 `query` | 과거 근거 재사용 | 저장 품질(태그/노트)에 좌우 |
| `archive_context` | 도메인 지식/결론 저장 | `topic`, `content`, `tags` | 장기 컨텍스트 축적 | 내용 품질 관리가 중요 |
| `get_context` | 저장된 컨텍스트 조회 | `topic` 또는 `query` | 이전 분석 재활용 | 오래된 컨텍스트 검증 필요 |
| `dry_run_diff` | 변경안 diff와 경량 점검 | `path`, `content` | 실제 수정 전 위험 점검 | 최종 테스트를 대체하지 않음 |

## 실전 권장 사용 흐름
1. `status`로 상태 확인
2. `repo_candidates`/`list_files`로 범위 축소
3. `search`/`search_symbols`/`search_api_endpoints`로 위치 식별
4. `grep_and_read`/`read_symbol`로 핵심 코드 우선 확보
5. 필요 시 `read_file`로 전체 맥락 확인
6. 영향 분석은 `get_callers`/`get_implementations`/`call_graph`
7. 인덱스 의심 시 `index_file` -> `rescan` -> `doctor` 순 점검
