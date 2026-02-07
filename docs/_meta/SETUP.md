# SETUP (v2.5.0)

> 이 문서는 포인터가 아니라 **정본**이다. 이 zip만으로 설치(1회)·적용(repo별)·진단(status)·업데이트까지 끝낸다.
>
> **v2.5.0 핵심 변경**: Multi-CLI 지원 (Codex/Gemini) 및 버전 정합성 통일.

---

## 1. 설치 (1회만)

### 방법 A: 원커맨드 설치 (권장)

```bash
# 압축 해제 후 (로컬 패키지 사용)
cd codex-rules-v2.5.0-workspace-msa
./install.sh ~/Documents/repositories  # 또는 ~/documents/repositories

# 셸 설정 적용
source ~/.zshrc  # 또는 ~/.bash_profile
```

```bash
# 경로 미지정 시: 현재 디렉토리를 workspace로 사용하고 git에서 최신 소스를 내려받음
cd ~/Documents/repositories
./install.sh
```

```bash
# install.sh만 내려받아 실행
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/codex-forge/main/install.sh | \
  bash -s -- ~/Documents/repositories
```

```bash
# (선택) 설치 소스 오버라이드
CODEX_RULES_REPO_URL="https://github.com/BaeCheolHan/codex-forge.git" \
CODEX_RULES_REF="main" \
./install.sh
```

> 설치 중 기존 rules 덮어쓰기 여부를 묻습니다. "no"를 선택하면 rules만 유지되고 나머지는 적용됩니다.  
> `.codex/config.toml`은 덮어쓰지 않으며, 필요한 MCP 설정만 병합됩니다.

### 방법 B: 수동 설치

```bash
# 1. workspace 생성
mkdir -p ~/Documents/repositories
cd ~/Documents/repositories

# 2. .codex-root 마커 생성
touch .codex-root

# 3. 룰셋 압축 해제
unzip /path/to/codex-rules-v2.5.0-workspace-msa.zip -d /tmp
# 주의: zip은 codex-rules-v2.5.0-workspace-msa/ 폴더를 생성함

# 4. 파일 복사 (폴더 내용물을 workspace root로)
cp -r /tmp/codex-rules-v2.5.0-workspace-msa/* .
cp -r /tmp/codex-rules-v2.5.0-workspace-msa/.codex .
cp /tmp/codex-rules-v2.5.0-workspace-msa/.codex-root .

# 5. 환경변수 설정
echo 'export CODEX_HOME="$HOME/Documents/repositories/.codex"' >> ~/.zshrc
source ~/.zshrc

# 6. codex-cli 실행 (프로젝트 신뢰 확인)
codex "안녕"
```

---

## 2. 적용 (repo별)

개별 repo에서 특별한 설정은 필요 없습니다. workspace root에서 실행하면 됩니다.

```bash
cd ~/Documents/repositories
codex "payment-service에서 결제 로직 찾아줘"
```

MCP 도구 확인:
```bash
# TUI에서
/mcp

# local-search 도구가 등록되어 있어야 함:
# - search
# - status
# - repo_candidates
```

---

## 3. 진단 (status/self-check)

### 필수 파일 확인
```bash
cd ~/Documents/repositories
ls .codex-root .codex/AGENTS.md .codex/rules/00-core.md
# 3개 파일 모두 존재해야 함
```

### MCP 서버 테스트
```bash
# 직접 테스트
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python3 .codex/tools/local-search/mcp/server.py

# 예상 출력: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25",...}}
```

### 폴백 (MCP 실패 시)
```bash
# 수동 HTTP 서버 시작 (MCP 대신 HTTP 모드)
cd ~/Documents/repositories
python3 .codex/tools/local-search/app/main.py &

# 1. 상태 확인 (호스트/포트 자동 감지)
python3 .codex/tools/local-search/scripts/query.py status

# 2. 직접 curl (config.json의 server_port 기준, 기본값 47777)
curl http://127.0.0.1:47777/status
# 포트를 변경했다면 status 출력의 port 값을 사용
```

---

## 4. 업데이트

```bash
# 1. 백업
cd ~/Documents/repositories
mv .codex .codex-backup-$(date +%Y%m%d)

# 2. 새 버전 설치
cd /path/to/new/version
./install.sh ~/Documents/repositories --backup

# 3. 사용자 설정 복원 (필요시)
# install.sh가 .codex/config.toml 자동 보존
```

---

## 5. 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| MCP 도구 안 보임 | 프로젝트 미신뢰 | codex 실행 후 신뢰 확인 |
| local-search 오류 | Python 없음 | Python 3.8+ 설치 |
| 검색 결과 0건 | 인덱스 미생성 | 잠시 대기 (초기 스캔) |
| config.toml 오류 | 형식 오류 | TOML 문법 확인 |

---

## 6. 버전 확인

```bash
head -1 ~/Documents/repositories/.codex/AGENTS.md
# 예상: # Codex Rules v2.5.0
```
