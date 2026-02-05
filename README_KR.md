# Sari (사리) - 로컬 코드 검색 에이전트

**Sari**는 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)를 구현한 고성능 **로컬 코드 검색 에이전트**입니다. AI 어시스턴트(Claude, Cursor, Codex 등)가 코드를 외부 서버로 전송하지 않고도 대규모 코드베이스를 효율적으로 탐색하고 이해할 수 있도록 돕습니다.

[English README](README.md)

> **핵심 기능:**
> - ⚡ **빠른 인덱싱:** SQLite FTS5 + AST 기반 심볼 추출
> - 🔍 **스마트 검색:** 하이브리드 랭킹 (키워드 + 심볼 구조)
> - 🧠 **코드 인텔리전스:** 콜 그래프, 스니펫 관리, 도메인 컨텍스트 아카이빙
> - 🔒 **로컬 보안:** 모든 데이터는 사용자 로컬 머신에만 저장됩니다.

---

## 🚀 설치 및 설정 가이드

Sari는 **설치와 실행을 분리**하는 방식이 안정적입니다.
1) 먼저 설치를 완료하고,
2) MCP 설정에는 실행 명령만 추가합니다.

### 0. 설치 (공통)

#### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

#### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y --update
```

### 1. Codex (CLI / App, HTTP MCP)

Codex는 HTTP 기반 MCP를 사용합니다. Sari를 HTTP 모드로 실행한 뒤 URL을 설정하세요.

**실행:**
```bash
sari --transport http --http-api-port 47777

# 백그라운드로 실행
sari --transport http --http-api-port 47777 --http-daemon
```

**설정 파일:** `.codex/config.toml` 또는 `~/.codex/config.toml`

```toml
[mcp_servers.sari]
url = "http://127.0.0.1:47777/mcp"
enabled = true
```

### 2. Cursor / Claude Desktop (stdio)

Cursor와 Claude Desktop은 JSON 형식의 설정을 사용합니다.

**설정 파일 위치:**
- **Cursor:** `Connect to MCP Server` 메뉴 또는 설정 파일
- **Claude Desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

#### 🍎 macOS / Linux

```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/Users/username/projects/my-app",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

#### 🪟 Windows (PowerShell)

```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "C:\\Projects\\MyApp",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### 3. Gemini CLI (stdio)

Gemini CLI는 `settings.json`의 MCP 서버 설정을 읽습니다. Gemini 설정에 Sari 항목을 추가한 뒤 CLI를 재시작하세요.

**설정 파일 위치:**
- **macOS/Linux:** `~/.gemini/settings.json`
- **Windows:** `%USERPROFILE%\\.gemini\\settings.json`

```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/path/to/your/project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### 4. Claude Code (CLI)

Anthropic의 새로운 CLI 도구인 Claude Code를 사용하는 경우, `config.toml` 설정 방식을 따르거나 별도의 MCP 플러그인 설정을 확인해야 합니다. 일반적으로 위 Codex 예시와 유사한 TOML 형식이나 JSON 형식을 지원할 것으로 예상됩니다. (Claude Code의 공식 MCP 지원 문서 참조 필요)

### 5. 수동 설치 (Pip)

Python 환경에서 직접 패키지를 관리하고 싶다면 `pip`로 설치할 수 있습니다.

```bash
# PyPI에서 설치
pip install sari

# MCP 서버 실행 (Stdio 모드)
sari --transport stdio --format pack
```

---

## ⚙️ 설정 레퍼런스 (Configuration)

설정값은 성격에 따라 **설치 시점(Installation)**과 **실행 시점(Runtime)**으로 나뉩니다.

### A. 설치 및 부트스트랩 (Installation & Bootstrapping)
설치 스크립트(`install.py`, `bootstrap.sh`)가 실행될 때 적용되는 설정입니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `XDG_DATA_HOME` | 설치 경로를 변경합니다. 설정 시 `$XDG_DATA_HOME/sari`에 설치됩니다. | `~/.local/share` |
| `SARI_SKIP_INSTALL` | `1`로 설정 시 **부트스트랩 사용 시** `pip install` 자동 업데이트를 건너뜁니다. 개발 환경이나 오프라인에서 유용합니다. | `0` |
| `SARI_NO_INTERACTIVE` | `1`로 설정 시 설치 스크립트의 대화형 질문을 끄고 기본값(Yes)으로 진행합니다. | `0` |

### B. 시스템 및 런타임 (System & Runtime)
MCP 서버가 실행되는 동안 동작을 제어하는 설정입니다. `env` 섹션에 추가하세요.

#### 1. 코어 설정 (Core)
기본적인 동작을 위한 필수 설정입니다. (이전 버전 호환성을 위해 `SARI_` 접두어도 지원하지만, `SARI_`를 권장합니다.)

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_WORKSPACE_ROOT` | **(필수 권장)** 프로젝트 최상위 루트 경로. 생략 시 자동 감지하지만 명시하는 것이 좋습니다. | 자동 감지 |
| `SARI_ROOTS_JSON` | 여러 개의 루트를 등록할 때 사용합니다. JSON 배열 문자열 예: `["/path/a", "/path/b"]` | - |
| `SARI_DB_PATH` | SQLite 인덱스 DB 파일의 경로를 직접 지정합니다. | `~/.local/share/sari/data/<hash>/index.db` |
| `SARI_CONFIG` | 특정 설정 파일을 로드합니다. | `~/.config/sari/config.json` |
| `SARI_RESPONSE_COMPACT` | 응답 JSON을 압축하여 LLM 토큰을 절약합니다. 디버깅 때는 `0`으로 끄세요. | `1` (켜짐) |
| `SARI_FORMAT` | CLI 도구 출력 형식. `pack`(텍스트) 또는 `json`. | `pack` |

#### 2. 검색 엔진 (Search Engine)
검색 품질과 백엔드 동작을 튜닝합니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_ENGINE_MODE` | 검색 백엔드. `embedded`(Tantivy)가 빠르고 정확합니다. `sqlite`(FTS5)는 호환성 모드입니다. | `embedded` |
| `SARI_ENGINE_TOKENIZER` | 토크나이저 전략. `auto`(감지), `cjk`(한중일 최적화), `latin`(표준). | `auto` |
| `SARI_ENGINE_AUTO_INSTALL` | 엔진 바이너리(Tantivy)가 없으면 자동으로 설치합니다. | `1` (켜짐) |
| `SARI_ENGINE_SUGGEST_FILES`| 상태 체크 시 Tantivy 엔진 업그레이드를 제안하는 파일 수 임계값. | `10000` |
| `SARI_LINDERA_DICT_PATH` | CJK 토큰화를 위한 커스텀 Lindera 사전 경로 (고급). | - |

#### 3. 인덱싱 및 성능 (Indexing & Performance)
리소스 사용량과 동시성을 제어합니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_COALESCE_SHARDS` | 인덱싱 동시성 제어. 대규모 리포지토리(파일 10만 개 이상)에서는 늘리는 것이 좋습니다. | `16` |
| `SARI_PARSE_TIMEOUT_SECONDS`| 파일당 파싱 제한 시간(초). `0`은 무제한. 파서 멈춤을 방지합니다. | `0` |
| `SARI_PARSE_TIMEOUT_WORKERS`| 타임아웃 파싱을 위한 워커 스레드 수. | `2` |
| `SARI_MAX_PARSE_BYTES` | 파싱을 시도할 최대 파일 크기(바이트). 더 큰 파일은 건너뛰거나 샘플링합니다. | `16MB` |
| `SARI_MAX_AST_BYTES` | AST 추출을 시도할 최대 파일 크기(바이트). | `8MB` |
| `SARI_GIT_CHECKOUT_DEBOUNCE`| Git 체크아웃 후 대량 인덱싱 시작 전 대기 시간(초). | `3.0` |
| `SARI_FOLLOW_SYMLINKS` | 파일 스캔 시 심볼릭 링크를 따라갑니다. **주의:** 순환 링크가 있으면 무한 루프 위험이 있습니다. | `0` (꺼짐) |
| `SARI_READ_MAX_BYTES` | `read_file` 도구가 반환하는 최대 바이트 수. 컨텍스트 초과 방지. | `1MB` |

#### 4. 네트워크 및 보안 (Network & Security)
데몬 연결 설정입니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_DAEMON_HOST` | 백그라운드 데몬 호스트 주소. | `127.0.0.1` |
| `SARI_DAEMON_PORT` | 데몬 TCP 포트. | `47779` |
| `SARI_HTTP_API_PORT` | HTTP API 서버 포트 (선택 사항). | `47777` |
| `SARI_ALLOW_NON_LOOPBACK` | 로컬호스트가 아닌 IP 접속 허용. **보안 위험:** 신뢰할 수 있는 네트워크에서만 켜세요. | `0` (꺼짐) |

#### 5. 고급 / 디버그 (Advanced / Debug)
개발자용 디버깅 옵션입니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_LOG_LEVEL` | 로깅 레벨 (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |
| `SARI_DRYRUN_LINT` | `dry-run-diff` 도구 실행 시 구문 오류 검사(Linting)를 포함할지 여부. | `0` (꺼짐) |
| `SARI_PERSIST_ROOTS` | `1`로 설정 시, 감지된 루트를 `config.json`에 영구 저장합니다. | `0` (꺼짐) |
| `SARI_LOG_LEVEL` | 로그 레벨 설정 (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |

---

## 🩺 문제 해결 (Troubleshooting)

### 상태 확인
설치된 Sari 데몬이 정상 작동 중인지 확인하려면 다음 명령어를 터미널에서 실행하세요.

```bash
sari doctor --auto-fix
```

### 제거 (Uninstall)
Sari, 인덱스 데이터, 기본 설정을 제거합니다:
Sari와 모든 인덱싱 데이터를 삭제하려면:

```bash
# macOS/Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall

# Windows
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - --uninstall
```

워크스페이스 로컬 캐시까지 제거하려면 워크스페이스 루트를 함께 넘겨주세요:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --workspace-root /path/to/project
```

언인스톨은 홈 디렉터리에서 `.codex/tools/sari` 캐시도 찾아 제거합니다(최선 노력).

`SARI_CONFIG` 또는 `SARI_CONFIG`로 커스텀 설정 경로를 사용 중이고 해당 파일도 제거하려면 다음 옵션을 사용하세요:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --force-config
```
