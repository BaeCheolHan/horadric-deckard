# Local Search

> 오프라인 코드 인덱싱 및 검색 도구

**Requirements**: Python 3.9+

## v2.5.0 변경사항 (DB 격리 + Pagination)

### DB 격리 (Critical)
- **전역 DB 사용 중단**: `~/.cache/local-search/` 대신 각 워크스페이스 내부 `.codex/tools/local-search/data/index.db` 사용.
- 워크스페이스 간 데이터 오염 및 충돌 원천 차단.

### `search` 도구 개선 (Pagination)
- `offset`: 검색 결과 페이지네이션 지원.
- `has_more`: 추가 결과 존재 여부 표시.
- `repo_summary`: 리포지토리별 매칭 통계 제공.

### 새 도구: `list_files`
인덱싱된 파일 목록 조회 (디버깅용)

```json
// 전체 인덱스 조회
{}

// 특정 repo의 파일 목록
{"repo": "my-service"}

// Python 파일만
{"file_types": ["py"]}

// 숨김 디렉토리(.codex) 포함
{"include_hidden": true}

// 페이지네이션
{"limit": 50, "offset": 100}
```

### `repo_candidates` 개선
- 각 후보에 **선택 이유(reason)** 추가
- `hint` 필드로 다음 액션 안내

### `include_hidden` 옵션
- `list_files`에서 숨김 디렉토리 포함 여부 명시
- 기본값: `false` (`.codex` 등 제외)

---

## v2.3.1 변경사항 (검색 기능 강화)

### 새 검색 옵션
| 옵션 | 타입 | 설명 |
|------|------|------|
| `file_types` | array | 파일 확장자 필터 (예: `["py", "ts"]`) |
| `path_pattern` | string | 경로 glob 패턴 (예: `src/**/*.ts`) |
| `exclude_patterns` | array | 제외 패턴 (예: `["node_modules", "test"]`) |
| `recency_boost` | boolean | 최근 수정 파일 우선순위 |
| `use_regex` | boolean | 정규식 검색 모드 |
| `case_sensitive` | boolean | 대소문자 구분 (정규식 모드) |
| `context_lines` | integer | snippet 라인 수 (기본: 5) |

### 검색 결과 개선
- 매칭 라인 하이라이트 (`>>>키워드<<<`)
- 파일 메타데이터 포함 (mtime, size, file_type)
- match_count (매칭 횟수)

### 사용 예시

```json
// TypeScript 파일에서 "handlePayment" 검색
{"query": "handlePayment", "file_types": ["ts"]}

// src/ 폴더에서 최근 수정된 파일 우선
{"query": "auth", "path_pattern": "src/**/*", "recency_boost": true}

// 정규식으로 함수 정의 검색
{"query": "function\\s+\\w+Auth", "use_regex": true}

// node_modules 제외하고 검색
{"query": "TODO", "exclude_patterns": ["node_modules", "build"]}
```

---

## v2.3.0 변경사항

- 경로 구조 변경: `tools/local-search/` → `.codex/tools/deckard/`
- 모든 경로 참조 v2.3.0 구조에 맞게 업데이트

## v2.2.1 변경사항

- 초기 인덱싱 타임아웃 환경변수 지원 (`LOCAL_SEARCH_INIT_TIMEOUT`)
- 문서 일관성 수정

## v2.2.0 변경사항

**MCP 통합**: codex-cli가 local-search를 MCP 서버로 자동 관리합니다.

### MCP 모드 (권장)
- `.codex/config.toml`의 `[mcp_servers.local-search]` 설정
- codex 실행 시 자동 시작
- 별도 서버 관리 불필요

### 폴백: HTTP 서버 수동 시작
MCP 연결 실패 시 HTTP 서버를 수동으로 시작할 수 있습니다:
```bash
# 1. HTTP 서버 시작 (백그라운드)
cd ~/Documents/repositories  # workspace root
python3 .codex/tools/local-search/app/main.py &

# 2. 상태 확인 (권장 - 포트 자동 감지)
python3 .codex/tools/local-search/scripts/query.py status

# 3. 직접 curl (config.json의 server_port 기준, 기본값 47777)
curl http://127.0.0.1:47777/status
# 포트를 변경했다면 status 출력의 port 값을 사용
```

> **참고**: HTTP 서버(`app/main.py`)와 MCP 서버(`mcp/server.py`)는 별개입니다.
> MCP 서버는 STDIO 프로토콜을 사용하고, HTTP 서버는 REST API를 사용합니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LOCAL_SEARCH_INIT_TIMEOUT` | 5 | MCP 초기화 시 인덱싱 대기 시간 (초). 0=대기 안함 |
| `LOCAL_SEARCH_WORKSPACE_ROOT` | - | 워크스페이스 루트 경로 |
| `LOCAL_SEARCH_DB_PATH` | - | **(v2.5.0 디버그 전용)** 명시적으로 설정 시 DB 경로 오버라이드. 비어있으면 워크스페이스 로컬 경로 사용 |

### Multi-Workspace 지원 (v2.5.0)

각 워크스페이스는 독립적인 DB를 사용합니다:
```
{workspace}/.codex/tools/local-search/data/index.db
```

여러 워크스페이스에서 동시에 CLI를 실행해도 DB 충돌이 발생하지 않습니다.

## 인덱싱 정책 (v2.3.3+)

### 기본 제외 디렉토리
| 디렉토리 | 제외 이유 |
|----------|-----------|
| `.codex` | 룰셋/도구 코드 (코드 검색 오염 방지) |
| `.git`, `node_modules`, `__pycache__` | 런타임/버전관리 |
| `.venv`, `target`, `build`, `dist` | 빌드 산출물 |

### 기본 제외 파일
| 패턴 | 제외 이유 |
|------|-----------|
| `.env`, `.env.*` | 시크릿/환경설정 |
| `*.pem`, `*.key`, `*.crt` | 인증서/키 |
| `*credentials*`, `*secrets*` | 민감 정보 |

### docs/ 제외가 필요한 경우
`config.json`의 `exclude_dirs`에 `"docs"` 추가:
```json
"exclude_dirs": [".codex", ".git", "node_modules", ...]
```

### workspace root 파일
- 루트 파일은 `__root__` repo로 인덱싱됨

## 디렉토리 구조

```
.codex/tools/local-search/
├── app/                # 코어 모듈
│   ├── config.py       # 설정 로더
│   ├── db.py           # SQLite/FTS5 DB (v2.3.1 확장)
│   ├── indexer.py      # 파일 인덱서
│   ├── http_server.py  # HTTP 서버 (폴백)
│   └── main.py         # HTTP 서버 진입점
├── mcp/                # MCP 서버
│   ├── server.py       # STDIO MCP 서버 (v2.3.1)
│   └── test_server.py  # 단위 테스트
├── config/
│   └── config.json     # 설정 파일
└── scripts/
    └── query.py        # CLI 클라이언트
```

## 설정 (config.json)

```json
{
  "workspace_root": "~/Documents/repositories",
  "db_path": "~/.cache/local-search/index.sqlite3",
  "server_port": 47777,
  "include_ext": [".py", ".js", ".ts", ...],
  "exclude_dirs": [".git", "node_modules", ...]
}
```

> v2.3.3+: 기본 캐시 경로는 `~/.cache/local-search/`이며, 레거시 `~/.cache/codex-local-search/`는 자동 마이그레이션됨.

## MCP 도구

| 도구 | 설명 |
|------|------|
| search | 키워드/정규식으로 파일/코드 검색 (v2.3.1 확장) |
| status | 인덱스 상태 확인 |
| repo_candidates | 관련 repo 후보 찾기 (v2.5.0: 선택 이유 추가) |
| list_files | 인덱싱된 파일 목록 조회 (v2.5.0 신규) |

## 테스트

```bash
# 단위 테스트
python3 .codex/tools/local-search/mcp/test_server.py

# MCP 프로토콜 테스트
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python3 .codex/tools/local-search/mcp/server.py
```
