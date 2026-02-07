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

처음 사용하는 분도 바로 따라할 수 있도록 순서대로 정리했습니다.

### 사전 준비
- Python `3.9+`
- 패키지 관리자 하나: `uv`(권장) 또는 `pip`
- 인덱싱할 프로젝트의 절대 경로

Python 버전 확인:
```bash
python3 --version
```

### 5분 빠른 시작 (권장)
1. Sari 설치
```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y --update
```

2. 프로젝트 루트로 이동
```bash
cd /absolute/path/to/your/project
```

3. 현재 워크스페이스 기준으로 데몬 + HTTP 실행
```bash
sari daemon start -d
```

4. 상태 점검
```bash
sari status
sari doctor
```

5. MCP 클라이언트에 연결
아래 **클라이언트 연동** 섹션을 따라 설정하세요.

### 다른 설치 방법
`uv`:
```bash
uv tool install sari
uv tool install "sari[full]"   # 선택 기능 포함
uv x sari status               # 설치 없이 실행
```

`pip`:
```bash
pip install sari
pip install "sari[full]"       # 선택 기능 포함
```

### PyPI 배포본 강제 재설치 (릴리스 검증)
로컬 소스 간섭 없이 패키징된 배포본(예: MCP 연결 수정 릴리스)을 검증할 때 사용합니다.

```bash
# 1) 기존 tool 환경 제거
uv tool uninstall sari

# 2) PyPI 최신 버전 강제 재설치 (로컬 설정/소스 및 캐시 무시)
uv tool install --reinstall --refresh --no-cache --no-config --no-sources "sari[full]"

# 또는 특정 버전 고정 설치(예시)
uv tool install --reinstall --refresh --no-cache --no-config --no-sources "sari[full]==0.3.16"

# 3) 설치된 도구 버전 확인
uv tool list
```

선택: 핀할 버전을 정하기 전에 PyPI 배포 버전 목록을 확인합니다.
```bash
python3 -m pip index versions sari
```

### 실행 모드 선택 가이드
- `stdio` 모드:
대부분 MCP 클라이언트에서 기본으로 가장 무난합니다.
- `HTTP` 모드:
stdio 연결이 불안정한 환경에서 권장합니다.

HTTP 직접 실행:
```bash
SARI_WORKSPACE_ROOT=/absolute/path/to/project \
sari --transport http --http-api-port 47777 --http-daemon
```

HTTP MCP 엔드포인트:
```text
http://127.0.0.1:47777/mcp
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

아래 옵션 중 하나를 선택하세요.

### 옵션 A: 자동 설정 쓰기 (권장)
자동으로 설정 파일을 작성하고 싶을 때 사용합니다.
```bash
# 현재 워크스페이스의 로컬 설정 파일을 갱신합니다:
#   .codex/config.toml, .gemini/config.toml
sari --cmd install --host codex
sari --cmd install --host gemini
sari --cmd install --host claude
sari --cmd install --host cursor
```

미리보기만 하려면:
```bash
sari --cmd install --host codex --print
```

### 옵션 B: stdio 수동 설정
설정을 직접 관리하고 싶을 때 사용합니다.

Codex / Gemini (`.codex/config.toml` 또는 `.gemini/config.toml`):
```toml
[mcp_servers.sari]
command = "/absolute/path/to/sari"
args = ["--transport", "stdio", "--format", "json"]
env = { SARI_WORKSPACE_ROOT = "/absolute/path/to/project", SARI_CONFIG = "/absolute/path/to/project/.sari/mcp-config.json" }
startup_timeout_sec = 60
```

Gemini 구버전 설정 (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "sari": {
      "command": "/absolute/path/to/sari",
      "args": ["--transport", "stdio", "--format", "json"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/project",
        "SARI_CONFIG": "/absolute/path/to/project/.sari/mcp-config.json"
      }
    }
  }
}
```
`command`는 PATH/환경 드리프트를 피하기 위해 절대 경로 사용을 권장합니다.

Claude Desktop / Cursor (JSON):
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "json"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/project",
        "SARI_CONFIG": "/absolute/path/to/project/.sari/mcp-config.json",
        "SARI_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### 옵션 C: HTTP 엔드포인트 모드
클라이언트가 MCP URL 입력 방식을 사용할 때 권장합니다.

1. 백그라운드 HTTP 실행:
```bash
SARI_WORKSPACE_ROOT=/absolute/path/to/project \
sari --transport http --http-api-port 47777 --http-daemon
```

2. 클라이언트 MCP URL 지정:
```text
http://127.0.0.1:47777/mcp
```

### 연결 확인 체크리스트
설정을 적용한 뒤:
1. MCP 클라이언트를 재시작합니다.
2. 아래 명령을 실행합니다.
```bash
sari status
```
3. 다음 항목이 모두 정상인지 확인합니다.
- daemon running
- HTTP running
- 클라이언트 로그에 연결 오류 없음

---

## ⚙️ 설정 레퍼런스 (Configuration)

이 섹션은 코드에 실제 구현된 환경 변수만 정리합니다.

설정 방법:
- MCP 클라이언트: MCP 서버 `env` 블록에 추가
- 셸: `SARI_ENGINE_MODE=sqlite sari status`처럼 명령 앞에 붙여 실행

### 코어
| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_WORKSPACE_ROOT` | 워크스페이스 루트 강제 지정. 생략 시 현재 경로 기준 자동 감지. | 자동 감지 |
| `SARI_CONFIG` | 설정 파일 경로 오버라이드. | `~/.config/sari/config.json` |
| `SARI_FORMAT` | 출력 형식(`pack`/`json`). | `pack` |
| `SARI_STRICT_PROTOCOL` | `1`이면 미지원 프로토콜 버전을 자동 폴백하지 않고 에러로 처리. | `0` |
| `SARI_RESPONSE_COMPACT` | 응답 압축 출력(토큰 절감). | `1` |
| `SARI_LOG_LEVEL` | 로그 레벨. | `INFO` |

### 데몬 / HTTP
| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_DAEMON_HOST` | 데몬 바인드 호스트. | `127.0.0.1` |
| `SARI_DAEMON_PORT` | 데몬 TCP 포트. | `47779` |
| `SARI_HTTP_API_HOST` | HTTP API 호스트(상태 조회 라우팅 포함). | `127.0.0.1` |
| `SARI_HTTP_API_PORT` | HTTP API 포트. | `47777` |
| `SARI_HTTP_DAEMON` | `--transport http` 실행 시 백그라운드 모드 사용. | `0` |
| `SARI_ALLOW_NON_LOOPBACK` | HTTP 모드에서 비-루프백 바인드 허용. | `0` |

### 검색 / 인덱싱
| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_ENGINE_MODE` | `embedded` 또는 `sqlite`. | `embedded` |
| `SARI_ENGINE_AUTO_INSTALL` | 임베디드 엔진 미설치 시 자동 설치. | `1` |
| `SARI_ENGINE_TOKENIZER` | `auto`/`cjk`/`latin`. | `auto` |
| `SARI_ENGINE_INDEX_MEM_MB` | 임베디드 인덱싱 메모리 예산. | `128` |
| `SARI_ENGINE_MAX_DOC_BYTES` | 문서당 최대 인덱싱 바이트. | `4194304` |
| `SARI_ENGINE_PREVIEW_BYTES` | 문서 프리뷰 바이트. | `8192` |
| `SARI_MAX_DEPTH` | 최대 스캔 깊이. | `30` |
| `SARI_MAX_PARSE_BYTES` | 파싱 최대 파일 크기. | `16777216` |
| `SARI_MAX_AST_BYTES` | AST 파싱 최대 파일 크기. | `8388608` |
| `SARI_INDEX_WORKERS` | 인덱서 워커 수. | `6` |
| `SARI_INDEX_MEM_MB` | 인덱싱 메모리 제한. | `4096` |
| `SARI_COALESCE_SHARDS` | 코얼레싱 락 샤드 수. | `16` |
| `SARI_PARSE_TIMEOUT_SECONDS` | 파일별 파싱 타임아웃(`0` 비활성). | `0` |
| `SARI_GIT_CHECKOUT_DEBOUNCE` | Git 이벤트 후 디바운스 시간. | `3.0` |
| `SARI_MANUAL_ONLY` | `1`로 설정하면 자동 프로파일 감지를 끕니다. | `0` |
| `SARI_KEEP_NESTED_ROOTS` | 중첩 워크스페이스를 유지합니다(권장하지 않음). | `0` |

### 유지보수 / 고급
| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_DRYRUN_LINT` | `dry-run-diff`에서 문법 검사 활성화. | `0` |
| `SARI_MCP_DEBUG_LOG` | MCP 디버그 트래픽 로그(`mcp_debug.log`) 활성화(마스킹 적용). | `0` |
| `SARI_ALLOW_LEGACY` | 레거시 fallback(비네임스페이스 env / legacy root-id) 옵트인. | `0` |
| `SARI_STORAGE_TTL_DAYS_SNIPPETS` | 스니펫 TTL(일). | `30` |
| `SARI_STORAGE_TTL_DAYS_FAILED_TASKS` | 실패 작업 TTL(일). | `7` |
| `SARI_STORAGE_TTL_DAYS_CONTEXTS` | 컨텍스트 TTL(일). | `30` |
| `SARI_CALLGRAPH_PLUGIN` | 사용자 콜그래프 플러그인 모듈 경로. | - |
| `SARI_PERSIST_ROOTS` | 해석된 루트를 config에 저장. | `0` |

---

## 🩺 문제 해결 (Troubleshooting)

### 상태 확인
현재 워크스페이스 기준 데몬/HTTP 상태를 확인합니다.

```bash
sari status
sari doctor
```

워크스페이스 정책:
- `.sari`는 워크스페이스 로컬 설정/캐시 디렉토리이며 스캔 경계가 아닙니다.
- 명시적 스캔 경계 마커는 `.sariroot`입니다.
- 중첩 워크스페이스는 기본적으로 레지스트리에서 자동 dedupe 됩니다.

내부 복구 도구:
- `scan_once` / `rescan`은 내부 복구용입니다.
- 기본 도구 목록에서는 숨김 처리되며, 진단/복구 경로에서만 사용됩니다.

`--auto-fix` 등 고급 doctor 옵션은 아래 명령으로 사용할 수 있습니다:
```bash
python3 -m sari.mcp.cli doctor --auto-fix
```

### 저장소 유지관리 (Storage Maintenance)

보조 데이터(스니펫, 에러 로그 등)의 무제한 증가를 방지하기 위해 TTL(수명 주기) 정책을 지원합니다.
설정된 TTL에 따라 데이터가 자동 정리되지만, 수동으로 정리할 수도 있습니다.

**수동 정리 (Prune):**
```bash
# 기본 설정된 TTL에 따라 모든 테이블 정리
python3 -m sari.mcp.cli prune

# 특정 테이블을 3일 기준으로 정리
python3 -m sari.mcp.cli prune --table failed_tasks --days 3
```

**TTL 설정 (환경 변수):**
- `SARI_STORAGE_TTL_DAYS_SNIPPETS` (기본값: 30일)
- `SARI_STORAGE_TTL_DAYS_FAILED_TASKS` (기본값: 7일)
- `SARI_STORAGE_TTL_DAYS_CONTEXTS` (기본값: 30일)

---

## 📂 데이터 저장 위치

기본적으로 Sari는 다음과 같은 경로에 인덱싱 데이터와 로그를 저장합니다:

- **전역 데이터베이스 (Global DB):** `~/.local/share/sari/index.db` (Linux/macOS)
- **전역 인덱스 엔진:** `~/.local/share/sari/index/global/`
- **로그 파일:**
  - macOS: `~/Library/Logs/sari/`
  - 기타: `~/.local/share/sari/logs/`

> **팁:** 워크스페이스별로 독립된 데이터베이스를 사용하고 싶다면, 프로젝트 루트에 `.sari/index.db` 파일을 생성하세요. Sari가 이를 우선적으로 감지합니다.

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

`SARI_CONFIG`로 커스텀 설정 경로를 사용 중이고 해당 파일도 제거하려면 다음 옵션을 사용하세요:

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall --force-config
```
