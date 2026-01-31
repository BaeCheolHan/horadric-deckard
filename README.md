# Local Search (v1.1.0)

> 오프라인 코드 인덱싱 및 검색 도구

**Requirements**: Python 3.9+

## v1.1.0 변경사항 (Multi-Workspace Daemon)

### Multi-Workspace Daemon 도입 (Critical)
다중 클라이언트 접속을 지원하는 데몬 아키텍처가 도입되었습니다.
- **Daemon**: 백그라운드에서 하나의 인스턴스로 실행 (기본 포트: 47779).
- **Proxy**: 각 CLI는 프록시를 통해 데몬에 접속.
- **공유 인덱싱**: 동일 워크스페이스에 여러 CLI가 접속해도 인덱서/DB를 공유하여 리소스를 절약하고 락 충돌을 방지합니다.

데몬은 필요 시 자동으로 시작되며, 각 워크스페이스는 독립적인 DB를 유지합니다:
```
{workspace}/.codex/tools/deckard/data/index.db
```

### v1.1.0 주요 개선
- **동시성 해결**: 여러 CLI(Codex, Gemini) 동시 실행 시 부트스트랩 락/DB 충돌 해결.
- **리소스 최적화**: 중복 인덱싱 방지 및 메모리 절약.
- **자동 복구**: 데몬 프로세스 자동 관리.

---

## 이전 변경사항 (History)

### v0.0.9 (DB 격리 + Pagination)
- **DB 격리**: 워크스페이스별 독립 DB 사용.
- **Pagination**: `search` 도구에 `offset`, `limit` 지원.
- **New Tools**: `list_files`, `repo_candidates` 개선.

### v0.0.5 (검색 기능 강화)
- **Options**: `file_types`, `path_pattern`, `exclude_patterns`, `recency_boost`, `use_regex`.
- **Snippet**: 매칭 라인 하이라이트 및 메타데이터 포함.

---

## MCP 통합

Codex/Gemini CLI는 Deckard를 MCP 서버로 자동 관리합니다.

### MCP 모드 (권장)
- `.codex/config.toml`의 `[mcp_servers.deckard]` 설정
- codex 실행 시 자동 시작 (Daemon/Proxy 아키텍처)
- 별도 서버 관리 불필요

### 폴백: HTTP 서버 수동 시작
MCP 연결 실패 시 HTTP 서버를 수동으로 시작할 수 있습니다:
```bash
# 1. HTTP 서버 시작 (백그라운드)
cd {workspace_root}
python3 .codex/tools/deckard/app/main.py &

# 2. 상태 확인
python3 .codex/tools/deckard/scripts/query.py status
```

> **참고**: HTTP 서버(`app/main.py`)와 MCP 데몬은 별개입니다.
> MCP 데몬은 다중 워크스페이스를 지원하며 프록시를 통해 연결됩니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DECKARD_DAEMON_PORT` | 47779 | 데몬 리슨 포트 |
| `DECKARD_DAEMON_HOST` | 127.0.0.1 | 데몬 리슨 호스트 |
| `LOCAL_SEARCH_INIT_TIMEOUT` | 5 | MCP 초기화 시 인덱싱 대기 시간 (초) |
| `LOCAL_SEARCH_WORKSPACE_ROOT` | - | 워크스페이스 루트 경로 (자동 감지됨) |
| `LOCAL_SEARCH_DB_PATH` | - | **(디버그 전용)** DB 경로 오버라이드 |

## 인덱싱 정책

### 기본 제외 디렉토리
- `.codex`: 룰셋/도구 코드
- `.git`, `node_modules`, `__pycache__`: 런타임/버전관리
- `.venv`, `target`, `build`, `dist`: 빌드 산출물

### 기본 제외 파일
- `.env`, `*.pem`, `*.key`, `*credentials*`: 민감 정보

## 디렉토리 구조

```
.codex/tools/deckard/
├── app/                # 코어 모듈
│   ├── config.py       # 설정 로더
│   ├── db.py           # SQLite/FTS5 DB
│   ├── indexer.py      # 파일 인덱서
│   └── main.py         # HTTP 서버 진입점
├── mcp/                # MCP 서버 (Daemon/Proxy)
│   ├── daemon.py       # 멀티 워크스페이스 데몬
│   ├── proxy.py        # STDIO 프록시 (진입점)
│   ├── registry.py     # 인스턴스 관리
│   ├── session.py      # 클라이언트 세션
│   └── server.py       # MCP 서버 로직
├── config/
│   └── config.json     # 설정 파일
└── scripts/
    └── query.py        # CLI 클라이언트
```

## MCP 도구

| 도구 | 설명 |
|------|------|
| search | 키워드/정규식으로 파일/코드 검색 (Pagination 지원) |
| status | 인덱스 상태 확인 |
| repo_candidates | 관련 repo 후보 찾기 |
| list_files | 인덱싱된 파일 목록 조회 (디버깅용) |

## 테스트

```bash
# 단위 테스트
python3 .codex/tools/deckard/mcp/test_daemon.py

# MCP 프로토콜 테스트 (Proxy 경유)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"rootUri":"file:///tmp/test"}}' | \
    python3 .codex/tools/deckard/mcp/proxy.py
```
