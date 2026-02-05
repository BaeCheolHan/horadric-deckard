# Sari (사리) - 로컬 코드 검색 에이전트

**Sari**는 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)를 구현한 고성능 **로컬 코드 검색 에이전트**입니다. AI 어시스턴트(Claude, Cursor, Codex 등)가 코드를 외부 서버로 전송하지 않고도 대규모 코드베이스를 효율적으로 탐색하고 이해할 수 있도록 돕습니다.

[English README](README.md)

> **핵심 기능:**
> - ⚡ **빠른 인덱싱:** SQLite FTS5 + AST 기반 심볼 추출
> - 🔍 **스마트 검색:** 하이브리드 랭킹 (키워드 + 심볼 구조)
> - 🧠 **코드 인텔리전스:** 콜 그래프, 스니펫 관리, 도메인 컨텍스트 아카이빙
> - 🔒 **로컬 보안:** 모든 데이터는 사용자 로컬 머신에만 저장됩니다.

---

---

## 🚀 설치 및 설정 가이드

Sari는 **초경량(< 5MB)** 설계를 기본으로 합니다. 환경에 맞는 설치 방법을 선택하세요.

### 방법 1: 자동 설치 스크립트 (권장)
설치 과정에서 필요한 기능을 대화형으로 선택할 수 있습니다. 시스템에 **uv**가 설치되어 있다면 자동으로 사용하여 10배 더 빠르게 설치합니다.

#### 🍎 macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

#### 🪟 Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y --update
```

---

### 방법 2: 현대적인 CLI 설치 (uv 사용)
가장 깔끔하고 격리된 설치 방식입니다. PATH 설정이 자동으로 관리됩니다.

```bash
# 권장: 전역 도구로 설치
uv tool install sari

# 모든 고정밀 기능(한국어 검색 + Tree-sitter) 포함 설치
uv tool install "sari[full]"

# 설치 없이 즉시 실행
uv x sari status
```

---

### 방법 3: 레거시 설치 (pip 사용)
`uv`가 없는 환경에서의 표준 설치 방법입니다.

```bash
# 기본 설치
pip install sari

# 모든 기능 포함 설치
pip install "sari[full]"
```

---

### 방법 4: HTTP 연결 모드 (가장 안정적)
`stdio` 방식에서 연결 끊김(`Connection closed`) 문제가 발생할 경우 HTTP 모드를 사용하세요. 로그 잡음의 영향을 받지 않아 매우 안정적입니다.

**1. 환경 변수와 함께 Sari HTTP 서버 실행:**
```bash
# 워크스페이스 경로와 로그 레벨을 한 번에 설정하여 실행
SARI_WORKSPACE_ROOT=/absolute/path/to/project \
SARI_LOG_LEVEL=INFO \
sari --transport http --http-api-port 47777 --http-daemon
```

**2. 클라이언트 설정:**

#### Gemini CLI (`~/.gemini/settings.json`)
```json
{
  "mcpServers": {
    "sari": {
      "url": "http://127.0.0.1:47777/mcp"
    }
  }
}
```

#### Codex CLI (`.codex/config.toml`)
```toml
[mcp_servers.sari]
url = "http://127.0.0.1:47777/mcp"
enabled = true
```

---

## 🏎️ 선택적 기능 (Extras 설정)

Sari는 **경량화(Low Footprint)**와 **고정밀(High Precision)** 중 하나를 선택할 수 있는 유연성을 제공합니다.

| 옵션 | 기능 | 예상 용량 | 설치 명령어 |
|-------|---------|--------------|--------------|
| **기본(Core)** | 정규표현식 파서, FTS5 검색 | < 5MB | `pip install sari` |
| **`[cjk]`** | 한국어/일본어/중국어 형태소 분석 | +50MB | `pip install "sari[cjk]"` |
| **`[treesitter]`**| 고정밀 AST 심볼 추출 | +10MB~ | `pip install "sari[treesitter]"` |
| **`[full]`** | 위의 모든 기능 + Tantivy 엔진 | +100MB+ | `pip install "sari[full]"` |

### 적용 확인 (Verification)
설치 후 아래 명령어로 기능이 활성화되었는지 확인할 수 있습니다:
```bash
sari doctor
# 'sari' 명령어를 찾을 수 없다면 아래 명령어를 사용하세요:
# python3 -m sari doctor
```

---

## 🔌 클라이언트 연동 (Client Configuration)

AI 어시스턴트 설정 파일에 아래 내용을 추가하세요.

### 1. Gemini CLI / Codex CLI
설정 파일: `~/.gemini/settings.json` (또는 `.codex/config.toml`)

```json
{
  "mcpServers": {
    "sari": {
      "command": "/Users/사용자이름/.local/bin/sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```
*주의: 시스템 PATH에 등록되지 않은 경우를 대비해 `sari` 실행 파일의 절대 경로(보통 `~/.local/bin/sari`)를 사용하는 것이 가장 안전합니다.*

### 2. Claude Desktop & Cursor
```json
{
  "mcpServers": {
    "sari": {
      "command": "/Users/사용자이름/.local/bin/sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/your/project",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

---

## ⚙️ 설정 레퍼런스 (Configuration)

설정값은 성격에 따라 **설치 시점(Installation)**과 **실행 시점(Runtime)**으로 나뉩니다.

### 환경 변수 설정 방법

- **MCP 클라이언트**: MCP 서버 설정의 `env` 블록에 추가합니다.
- **CLI**: 명령 앞에 접두어로 붙입니다. 예: `SARI_ENGINE_MODE=sqlite sari status`.
- **영구 적용**: 셸 설정 파일(예: `~/.zshrc`)에 `export` 문을 추가합니다.

```json
"env": {
  "SARI_WORKSPACE_ROOT": "/path/to/project",
  "SARI_LOG_LEVEL": "ERROR",
  "SARI_ENGINE_TOKENIZER": "cjk"
}
```

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
| `SARI_DB_PATH` | SQLite 인덱스 DB 파일의 경로를 직접 지정합니다. | `~/.local/share/sari/index.db` |
| `SARI_CONFIG` | 특정 설정 파일을 로드합니다. | `~/.config/sari/config.json` |
| `SARI_DATA_DIR` | 전역 데이터 디렉토리를 지정합니다 (DB/엔진/캐시). | `~/.local/share/sari` |
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
| `SARI_ENGINE_MEM_MB` | 임베디드 엔진 전체 메모리 예산 (MB). | `512` |
| `SARI_ENGINE_INDEX_MEM_MB` | 임베디드 엔진 인덱싱 메모리 예산 (MB). | `256` |
| `SARI_ENGINE_THREADS` | 임베디드 엔진 스레드 수. | `2` |
| `SARI_ENGINE_MAX_DOC_BYTES` | 엔진에 인덱싱할 최대 문서 크기 (바이트). | `4194304` |
| `SARI_ENGINE_PREVIEW_BYTES` | 문서당 프리뷰 바이트 수. | `8192` |

**설정 파일(`config.json`) 대응값:**
```json
{
  "engine_mode": "embedded",
  "engine_auto_install": true
}
```
`SARI_ENGINE_MODE`, `SARI_ENGINE_AUTO_INSTALL`가 런타임에서 우선 적용됩니다.

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
| `SARI_MAX_DEPTH` | 스캔할 디렉토리의 최대 깊이. 무한 루프를 방지합니다. | `30` |
| `SARI_READ_MAX_BYTES` | `read_file` 도구가 반환하는 최대 바이트 수. 컨텍스트 초과 방지. | `1MB` |
| `SARI_INDEX_MEM_MB` | 전체 인덱싱 메모리 예산 (MB). | `512` |
| `SARI_INDEX_WORKERS` | 인덱싱 워커 수를 덮어씁니다. | `2` |
| `SARI_AST_CACHE_ENTRIES` | Tree-sitter AST용 LRU 캐시 크기. | `128` |

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

### 저장소 유지관리 (Storage Maintenance)

보조 데이터(스니펫, 에러 로그 등)의 무제한 증가를 방지하기 위해 TTL(수명 주기) 정책을 지원합니다.
설정된 TTL에 따라 데이터가 자동 정리되지만, 수동으로 정리할 수도 있습니다.

**수동 정리 (Prune):**
```bash
# 기본 설정된 TTL에 따라 모든 테이블 정리
sari prune

# 특정 테이블을 3일 기준으로 정리
sari prune --table failed_tasks --days 3
```

**TTL 설정 (환경 변수):**
- `SARI_STORAGE_TTL_DAYS_SNIPPETS` (기본값: 30일)
- `SARI_STORAGE_TTL_DAYS_FAILED_TASKS` (기본값: 7일)
- `SARI_STORAGE_TTL_DAYS_CONTEXTS` (기본값: 30일)

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
