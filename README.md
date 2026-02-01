# 🧙‍♂️ Horadric Deckard

> **"Stay awhile and listen..."** — to your codebase.

**Horadric Deckard**는 LLM(Large Language Models)을 위해 설계된 **초고속 오프라인 코드 검색 엔진**입니다.
Model Context Protocol (MCP)를 완벽하게 지원하여, Claude Desktop, Cursor, Gemini 등의 AI 에이전트에게 **전체 코드베이스에 대한 문맥(Context)**을 즉시 제공합니다.

## 🌟 Why Deckard?

LLM은 코드를 이해하는 능력은 뛰어나지만, 수만 라인의 프로젝트 전체를 한 번에 볼 수는 없습니다.
Deckard는 이 문제를 해결합니다:

- **⚡ 초고속 인덱싱**: SQLite + FTS5 기반의 강력한 로컬 검색으로 수천 개의 파일을 순식간에 인덱싱합니다.
- **🧠 스마트 컨텍스트**: 단순 키워드 검색을 넘어, 코드 구조(함수, 클래스)와 연관성을 고려하여 가장 관련성 높은 코드를 LLM에게 전달합니다.
- **🔒 완벽한 보안**: 모든 데이터는 **로컬(Local)**에만 저장됩니다. 코드가 외부 서버로 전송되지 않습니다.
- **🔌 MCP Native**: 차세대 표준인 **Model Context Protocol**을 지원하여, 도구 하나로 모든 AI 에이전트와 연동됩니다.
- **👻 Daemon Mode**: 백그라운드에서 실행되며 파일 변경사항을 실시간으로 감지하고 인덱스를 최신 상태로 유지합니다.

---

## 🚀 시작하기 (Getting Started)

터미널에 아래 명령어 한 줄만 입력하세요. 다운로드부터 설정까지 자동으로 완료됩니다.
기본 설치 경로는 `~/.local/share/horadric-deckard` 입니다.

```bash
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/horadric-deckard/main/install.py | python3
```

> **수동 설치**: [릴리즈 페이지](https://github.com/BaeCheolHan/horadric-deckard/releases)에서 코드를 다운로드한 뒤 `python3 install.py`를 실행하셔도 됩니다.
> 또는 아래처럼 파일로 받아 실행할 수 있습니다.
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/horadric-deckard/main/install.py -o install.py
> python3 install.py
> ```

---

## 🎮 사용법 (Usage)

### Claude Desktop
설정 파일(`claude_desktop_config.json` 등)에 아래 내용을 추가합니다.
경로의 `YOUR_USERNAME`을 실제 사용자명으로 변경해주세요.

```json
{
  "mcpServers": {
    "deckard": {
      "command": "/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh",
      "args": [],
      "env": {}
    }
  }
}
```

### Cursor (AI Editor)
1. `Cmd + Shift + J` (또는 설정) > **MCP** 패널 이동
2. **Add New MCP Server** 클릭
    - **Name**: `deckard`
    - **Type**: `stdio`
    - **Command**: `/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh` (절대 경로 입력)

### Codex / Gemini CLI
`~/.codex/config.toml` 또는 프로젝트 루트의 `.codex/config.toml`
(또는 `.gemini/config.toml`)에 아래 내용을 추가하세요.

```toml
[mcp_servers.deckard]
command = "/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh"
# args = []  # 필요한 경우 추가
```

workspace 루트를 고정하고 싶다면 args로 전달할 수 있습니다:

```toml
[mcp_servers.deckard]
command = "/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh"
args = ["--workspace-root", "/Users/YOUR_USERNAME/Documents/repositories"]
```

> 참고: 일부 클라이언트는 MCP initialize에 rootUri/workspaceFolders를 전달하지 않을 수 있습니다.
> 이 경우 Deckard는 현재 작업 디렉토리의 `.codex-root`를 기준으로 workspace를 추론합니다.

### 초기화 (권장)
워크스페이스에 `.codex-root`와 Deckard 설정을 생성합니다.

```bash
/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh init
```

이미 설정이 있다면 덮어쓰지 않습니다. 덮어쓰려면:

```bash
/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh init --force
```

> 기본 동작: 워크스페이스 설정이 없으면 설치 디렉토리의 기본 config를 사용합니다.

설정 후 아래 명령으로 등록 여부를 확인할 수 있습니다:

```bash
codex mcp list
```

### 기타 MCP 지원 CLI
대부분의 MCP 지원 CLI는 환경변수나 설정 파일(`~/.config/...`)을 통해 MCP 서버를 등록할 수 있습니다.
일반적으로 아래와 같은 커맨드 라인 인수를 지원합니다:

```bash
# 실행 시 MCP 서버 지정
claude-code --mcp-server="deckard:/Users/YOUR_USERNAME/.local/share/horadric-deckard/bootstrap.sh"
```

---

### 🔥 활용 예시
이제 AI에게 이렇게 물어보세요:
> "이 프로젝트에서 `User` 클래스가 정의된 파일을 찾아서 인증 로직을 설명해줘."

Deckard가 백그라운드에서 프로젝트를 스캔하고 정확한 파일을 찾아 전달합니다.

### CLI 도구

터미널에서 직접 데몬을 제어할 수도 있습니다.

```bash
# 데몬 백그라운드 실행
~/.local/share/horadric-deckard/bootstrap.sh daemon start -d

# 데몬 상태 확인
~/.local/share/horadric-deckard/bootstrap.sh daemon status

# 데몬 중지
~/.local/share/horadric-deckard/bootstrap.sh daemon stop

# HTTP 검색 (디버깅용)
~/.local/share/horadric-deckard/bootstrap.sh search "AuthService" --limit 10
```

---

## 🏗 기술 스택 (Under the Hood)

- **Language**: Python 3.9+ (Zero Dependency - 표준 라이브러리만 사용)
- **Database**: SQLite (WAL Mode) + FTS5 (Full Text Search)
- **Protocol**: Model Context Protocol (MCP) over Stdio/TCP
- **Architecture**:
    - **Daemon**: 중앙 인덱싱 서버 (Multi-workspace 지원)
    - **Proxy**: 클라이언트와 데몬 간의 경량 연결 통로

---

## 📜 라이선스 (License)

이 프로젝트는 [MIT License](LICENSE)를 따릅니다. 누구나 자유롭게 사용하고 기여할 수 있습니다.
