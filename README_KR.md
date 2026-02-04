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

Sari는 **MCP 설정**을 통한 자동 설치(권장)와 `pip`를 이용한 수동 설치를 모두 지원합니다.
사용하시는 도구에 맞는 설정을 적용해 주세요.

### 1. Codex (CLI / App)

Codex 환경에서는 `.codex/config.toml` (프로젝트별) 또는 `~/.codex/config.toml` (글로벌) 파일에 아래 설정을 추가합니다. 자동 업데이트와 의존성 관리가 포함된 부트스트랩 스크립트를 사용합니다.

**설정 파일:** `.codex/config.toml`

```toml
[mcp_servers.sari]
command = "bash"
args = [
  "-lc",
  # 설치 스크립트를 다운로드하고 실행한 뒤, 부트스트랩으로 서버를 시작합니다.
  "curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y; exec ~/.local/share/sari/bootstrap.sh --transport stdio"
]
env = { DECKARD_WORKSPACE_ROOT = "/path/to/your/project", DECKARD_RESPONSE_COMPACT = "1" }
```

> **참고:** `DECKARD_WORKSPACE_ROOT`는 생략 시 현재 작업 디렉토리를 자동으로 감지하지만, 명시적으로 설정하는 것이 권장됩니다.

### 2. Cursor / Claude Desktop

Cursor와 Claude Desktop은 JSON 형식의 설정을 사용합니다.

**설정 파일 위치:**
- **Cursor:** `Connect to MCP Server` 메뉴 또는 설정 파일
- **Claude Desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

#### 🍎 macOS / Linux

```json
{
  "mcpServers": {
    "sari": {
      "command": "bash",
      "args": [
        "-lc",
        "export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin && (curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y || true) && exec ~/.local/share/sari/bootstrap.sh --transport stdio"
      ],
      "env": {
        "DECKARD_WORKSPACE_ROOT": "/Users/username/projects/my-app",
        "DECKARD_RESPONSE_COMPACT": "1"
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
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - -y; & $env:LOCALAPPDATA\\sari\\bootstrap.bat --transport stdio"
      ],
      "env": {
        "DECKARD_WORKSPACE_ROOT": "C:\\Projects\\MyApp",
        "DECKARD_RESPONSE_COMPACT": "1"
      }
    }
  }
}
```

### 3. Claude Code (CLI)

Anthropic의 새로운 CLI 도구인 Claude Code를 사용하는 경우, `config.toml` 설정 방식을 따르거나 별도의 MCP 플러그인 설정을 확인해야 합니다. 일반적으로 위 Codex 예시와 유사한 TOML 형식이나 JSON 형식을 지원할 것으로 예상됩니다. (Claude Code의 공식 MCP 지원 문서 참조 필요)

### 4. 수동 설치 (Pip)

Python 환경에서 직접 패키지를 관리하고 싶다면 `pip`로 설치할 수 있습니다.

```bash
# PyPI에서 설치
pip install sari

# MCP 서버 실행 (Stdio 모드)
python3 -m sari --transport stdio
```

---

## ⚙️ 설정 레퍼런스 (Configuration)

`env` 섹션에 환경 변수를 추가하여 동작을 제어할 수 있습니다.

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `DECKARD_WORKSPACE_ROOT` | **(필수 권장)** 프로젝트 최상위 루트 경로. | 자동 감지 |
| `DECKARD_RESPONSE_COMPACT` | 응답 JSON을 압축하여 LLM 토큰을 절약합니다. 디버깅 때는 `0`으로 끄세요. | `1` (켜짐) |
| `DECKARD_DB_PATH` | SQLite 인덱스 DB 파일의 경로를 직접 지정합니다. | `~/.local/share/sari/data/...` |
| `DECKARD_ENGINE_MODE` | 검색 엔진 백엔드. `embedded`(Tantivy)가 빠르고 정확합니다. `sqlite`(FTS5)는 호환성 모드입니다. | `embedded` |
| `DECKARD_COALESCE_SHARDS` | 인덱싱 동시성 제어. 대규모 리포지토리(파일 10만 개 이상)에서는 늘리는 것이 좋습니다. | `16` |

---

## 🩺 문제 해결 (Troubleshooting)

### 상태 확인
설치된 Sari 데몬이 정상 작동 중인지 확인하려면 다음 명령어를 터미널에서 실행하세요.

```bash
# 자동 설치된 경우:
~/.local/share/sari/bootstrap.sh doctor --auto-fix

# 수동 설치된 경우:
sari doctor --auto-fix
```

### 제거 (Uninstall)
Sari와 모든 인덱싱 데이터를 삭제하려면:

```bash
# macOS/Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall

# Windows
irm https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python - --uninstall
```
