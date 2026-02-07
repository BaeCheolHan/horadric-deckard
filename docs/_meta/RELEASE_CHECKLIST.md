# Release Checklist v2.5.0

> **목적**: 버그 재발 방지 + 문서-코드 정합성 보장 + MCP 통합 검증

---

## 1. 버전 표기 일관성 (CRITICAL)

### 1.1. 전수 검증
```bash
# v2.5.0이어야 하는 파일들 (이전 2.3.x 잔재 확인)
grep -r "v2\.[0-3]\.[0-9]" --include="*.md" --include="*.sh" --include="*.toml" . 2>/dev/null | grep -v CHANGELOG | grep -v SELF_REVIEW

# 예상 결과: 0 matches (CHANGELOG/SELF_REVIEW의 히스토리 제외)
```

### 1.2. 필수 업데이트 위치
- [ ] `README.md` 헤더: `# Codex Rules v2.5.0`
- [ ] `.codex/AGENTS.md` 헤더: `# Codex Rules v2.5.0 (workspace-msa)`
- [ ] `.codex/system-prompt.txt` 1행: `Codex Rules v2.5.0`
- [ ] `.codex/config.toml` 주석: `v2.5.0`
- [ ] `.codex/quick-start.md` 설치 명령/zip명: `v2.5.0`
- [ ] `docs/_meta/SETUP.md` 헤더: `# SETUP (v2.5.0)`
- [ ] `docs/_meta/SELF_REVIEW.md` 헤더: `# SELF_REVIEW (v2.5.0)`
- [ ] `docs/_meta/RELEASE_CHECKLIST.md` 헤더: `Release Checklist v2.5.0`
- [ ] `docs/_meta/CHANGELOG.md` 최신 항목: `v2.5.0`
- [ ] `docs/_meta/VERSIONING.md` 현재 버전: `v2.5.0`
- [ ] `install.sh` 헤더/메시지: `v2.5.0`
- [ ] `uninstall.sh` 헤더: `v2.5.0`
- [ ] `.codex/tools/local-search/mcp/server.py` SERVER_VERSION: `"2.3.3"`
- [ ] 폴더/zip명: `codex-rules-v2.5.0-workspace-msa`

---

## 2. MCP 통합 검증 (NEW)

### 2.1. MCP 서버 시작
```bash
cd /path/to/workspace
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python3 .codex/tools/local-search/mcp/server.py

# 예상 출력:
# {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","serverInfo":{"name":"local-search","version":"2.3.3"},...}}
# 주의: version은 현재 릴리즈 버전과 일치해야 함
```

### 2.2. tools/list 확인
```bash
echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | \
    python3 .codex/tools/local-search/mcp/server.py

# 예상 출력: tools 배열에 search, status, repo_candidates 포함
```

### 2.3. 단위 테스트
```bash
python3 .codex/tools/local-search/mcp/test_server.py

# 예상: X passed, 0 failed
```

### 2.4. config.toml 검증
```bash
grep -A5 "mcp_servers.local-search" .codex/config.toml

# 예상:
# [mcp_servers.local-search]
# command = "python3"
# args = [".codex/tools/local-search/mcp/server.py"]
```

---

## 3. 설치 검증 (macOS)

### 3.1. Clean 환경 준비
```bash
TEST_ROOT="/tmp/codex-test-$(date +%s)"
mkdir -p "$TEST_ROOT"
cd "$TEST_ROOT"

# 기존 CODEX_HOME 백업
if [[ -n "$CODEX_HOME" ]]; then
    export CODEX_HOME_BACKUP="$CODEX_HOME"
    unset CODEX_HOME
fi
```

### 3.2. 압축 해제 및 설치
```bash
cp /path/to/codex-rules-v2.5.0-workspace-msa.zip .
unzip codex-rules-v2.5.0-workspace-msa.zip

cd codex-rules-v2.5.0-workspace-msa
./install.sh "$TEST_ROOT/repositories" --quit

# 예상: 정상 진행, MCP 서버 테스트 통과
```

### 3.3. 필수 파일 존재 확인
```bash
cd "$TEST_ROOT/repositories"

test -f .codex-root && echo "✓ .codex-root" || echo "✗ .codex-root"
test -f .codex/AGENTS.md && echo "✓ .codex/AGENTS.md" || echo "✗ .codex/AGENTS.md"
test -f .codex/config.toml && echo "✓ .codex/config.toml" || echo "✗ .codex/config.toml"
test -f .codex/rules/00-core.md && echo "✓ 00-core.md" || echo "✗ 00-core.md"
test -f .codex/tools/local-search/mcp/server.py && echo "✓ mcp/server.py" || echo "✗ mcp/server.py"

# 예상: 5개 모두 ✓
```

---

## 4. 룰 강화 검증

### 4.1. Local Search 우선 원칙 확인
```bash
grep -A20 "Local Search 우선 원칙" .codex/rules/00-core.md

# 예상: 섹션 존재, MCP 도구 사용법 포함
```

### 4.2. 토큰 절감 예시 확인
```bash
grep -B2 -A2 "92% 절감" .codex/rules/00-core.md

# 예상: Before/After 예시 존재
```

---

## 5. 문서-코드 대조

### 5.1. MCP 관련
| 주장 위치 | 주장 내용 | 실제 구현 |
|-----------|-----------|-----------|
| .codex/AGENTS.md | "MCP 도구 로드" | config.toml 설정 ✓ |
| SETUP.md | "codexw 불필요" | install.sh에 codexw 없음 ✓ |
| 00-core.md | "search, status 도구" | mcp/server.py 구현 ✓ |

### 5.2. 설치 관련
| 주장 위치 | 주장 내용 | 실제 구현 |
|-----------|-----------|-----------|
| SETUP.md | "원커맨드 설치" | install.sh 존재 ✓ |
| SETUP.md | "config.toml 보존" | install.sh CONFIG_BACKUP ✓ |

### 5.3. 포트 정합성 (NEW)
```bash
# config.json의 server_port와 문서 포트 번호 일치 확인
grep -r "127.0.0.1:[0-9]" --include="*.md" . | grep -v "47777"

# 예상: 0 matches (모든 curl 예시가 47777 사용)
```
| 주장 위치 | 주장 내용 | 실제 구현 |
|-----------|-----------|-----------|
| SETUP.md 폴백 | curl 127.0.0.1:47777 | config.json server_port: 47777 ✓ |
| local-search/README.md | curl 127.0.0.1:47777 | 동일 ✓ |

---

## 6. Python 문법 체크

```bash
python3 -m py_compile .codex/tools/local-search/mcp/server.py
python3 -m py_compile .codex/tools/local-search/mcp/test_server.py
python3 -m py_compile .codex/tools/local-search/app/*.py

# 예상: 모두 에러 없음
```

---

## 7. 런타임 파일 체크

```bash
find . -name "*.pyc" -o -name "__pycache__" -o -name ".DS_Store" -o -name "server.pid" -o -name "server.json" -o -name "index.db" 2>/dev/null | grep -v ".git"

# 예상: 0 matches
```

---

## 8. 최종 체크

### 8.1. 압축 테스트
```bash
cd /path/to/source
zip -r codex-rules-v2.5.0-workspace-msa.zip codex-rules-v2.5.0-workspace-msa \
    -x "*.pyc" -x "*__pycache__*" -x "*.DS_Store" -x "*index.db"

unzip -t codex-rules-v2.5.0-workspace-msa.zip
```

### 8.2. 압축 해제 후 MCP 테스트
```bash
unzip codex-rules-v2.5.0-workspace-msa.zip -d /tmp/test-unzip
cd /tmp/test-unzip/codex-rules-v2.5.0-workspace-msa

echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python3 .codex/tools/local-search/mcp/server.py

# 예상: 정상 응답
```

---

## 9. 릴리스 승인 조건

**모든 항목이 PASS여야 릴리스 가능**

- [ ] 1. 버전 표기: 전수 검증 PASS
- [ ] 2. MCP 통합: 서버 시작/도구/테스트 PASS
- [ ] 3. 설치 검증: macOS clean 환경 PASS
- [ ] 4. 룰 강화: Local Search 우선 원칙 존재
- [ ] 5. 문서-코드 대조: 모든 주장 구현 확인
- [ ] 6. Python 문법: 모든 파일 PASS
- [ ] 7. 런타임 파일: 0개 PASS
- [ ] 8. 압축 테스트: 정상 PASS

**FAIL 시**: v2.5.0-rc1 → 수정 → v2.5.0-rc2 → ... → v2.5.0 Stable

---

## 10. 정리

```bash
rm -rf "$TEST_ROOT"

if [[ -n "$CODEX_HOME_BACKUP" ]]; then
    export CODEX_HOME="$CODEX_HOME_BACKUP"
    unset CODEX_HOME_BACKUP
fi
```
