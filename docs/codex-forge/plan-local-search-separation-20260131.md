# local-search 분리 및 npm 패키징 계획

> **작성일**: 2026-01-31  
> **버전**: v1.0  
> **목표**: ai-local-search를 독립 npm 패키지로 분리 + codex-forge 서브모듈 통합

---

## 배경

### 문제점
- local-search가 codex-forge에 강하게 결합
- 단독 사용 불가능
- 버전 관리 어려움

### 목표
1. **단독 사용**: npm 패키지로 배포 → local-search만 사용 가능
2. **통합 사용**: codex-forge 서브모듈 → 룰셋 + local-search
3. **편의성**: npx로 즉시 실행 (Serena MCP 패턴)

---

## 핵심 전략

### Serena MCP 모범사례 반영
- **npx 패턴**: 별도 설치 없이 즉시 실행
- **자동 설정**: postinstall 스크립트로 MCP 설정 자동 업데이트
- **경량화**: production 의존성만 배포

### 하이브리드 접근
```
npm 패키지 (단독 사용) + Git 서브모듈 (codex-forge 통합)
```

---

## 패키지 구조

```
ai-local-search/
├── package.json          # npm 메타데이터
├── bin/
│   └── ai-local-search   # CLI wrapper (Node.js)
├── src/
│   ├── app/              # Core (Python)
│   ├── mcp/              # MCP server (Python)
│   ├── config/
│   └── scripts/
├── scripts/
│   └── postinstall.js    # 자동 MCP 설정
├── README.md
└── .npmignore
```

---

## 세 가지 설치 방법

### A. npx 즉시 실행 (권장)
```bash
# MCP 설정만 추가
[mcp_servers.local-search]
command = "npx"
args = ["@your-org/ai-local-search"]
```

**장점**: 설치 불필요, 항상 최신 버전
**주의**: npx는 실행 시 패키지를 캐시 설치하며, `postinstall`은 캐시 설치 과정에서만 실행됨.
설정 자동 수정은 `AI_LOCAL_SEARCH_CONFIG_WRITE=1`가 있을 때만 동작하도록 제한.

### B. npm 전역 설치
```bash
npm install -g @your-org/ai-local-search

# MCP 설정
[mcp_servers.local-search]
command = "ai-local-search"
```

**장점**: 오프라인 사용, 버전 고정

### C. codex-forge 서브모듈
```bash
git clone --recurse-submodules codex-forge
./install.sh /workspace
```

**장점**: 룰셋 + local-search 통합

---

## 구현 로드맵

### Phase 1: npm 패키지 구조 생성

**파일 생성:**
1. `package.json` — npm 메타데이터
2. `bin/ai-local-search` — CLI wrapper
3. `scripts/postinstall.js` — 자동 MCP 설정
4. `.npmignore` — 배포 제외 파일
5. `src/**` — 기존 Python 코어 이관
6. `requirements.txt` — Python 의존성 명시

**핵심 코드:**

#### package.json
```json
{
  "name": "@your-org/ai-local-search",
  "version": "2.6.0",
  "bin": {
    "ai-local-search": "./bin/ai-local-search"
  },
  "scripts": {
    "postinstall": "node scripts/postinstall.js"
  },
  "files": ["bin/", "src/", "scripts/"]
}
```

#### bin/ai-local-search
```javascript
#!/usr/bin/env node
const { spawn } = require('child_process');
const path = require('path');

const serverPath = path.join(__dirname, '../src/mcp/server.py');
spawn('python3', [serverPath], { stdio: 'inherit' });
```
> 실행 전 `python3` 유무/버전(3.8+)을 검사하고, 부족 시 오류 메시지로 설치 가이드 출력.

#### scripts/postinstall.js
- Codex CLI 감지 → `.codex/config.toml` 업데이트
- Gemini CLI 감지 → `.gemini/settings.json` 업데이트 (파일이 없으면 스킵)
- **안전장치**: 자동 수정은 기본 OFF, 명시적 플래그가 있을 때만 수행
  - 예: `AI_LOCAL_SEARCH_CONFIG_WRITE=1` 존재 시에만 쓰기
  - 수정 전 백업 파일 생성: `.codex/config.toml.bak`, `.gemini/settings.json.bak`
  - 기존 `mcp_servers.local-search` 존재 시 덮어쓰기 금지, 충돌 메시지 출력
  - npx 캐시 설치 시점에만 실행되므로, 수동 실행 스크립트도 제공(예: `node scripts/postinstall.js`)

---

### Phase 2: codex-forge 서브모듈 통합

**작업:**
1. 기존 `.codex/tools/local-search` 백업(삭제 금지)
2. 서브모듈 추가:
   ```bash
   git submodule add \
     https://github.com/<org>/ai-local-search \
     .codex/tools/local-search
   ```
3. `install.sh` 수정:
   - 서브모듈 자동 init
   - `npm install --production` 실행
   - `python3` 버전 체크(3.8+) 및 실패 시 가이드 출력
4. README/마이그레이션 가이드 업데이트

**자동 마이그레이션:**
```bash
# 기존 사용자 감지
if [ -d ".codex/tools/local-search" ] && [ ! -d ".codex/tools/local-search/.git" ]; then
    echo "Migrating..."
    # 백업 보존 (롤백 가능)
    mv .codex/tools/local-search .codex/tools/local-search.bak-$(date +%Y%m%d%H%M%S)
fi
git submodule update --init .codex/tools/local-search
```

---

### Phase 3: npm 배포 및 문서

**npm 배포:**
```bash
cd ai-local-search
npm publish --access public
```

**문서 업데이트:**
- `README.md` — 3가지 설치 방법
- `codex-forge/README.md` — 서브모듈 안내
- 마이그레이션 가이드

---

## 호환성 보장

### 경로 불변성
서브모듈 마운트: `.codex/tools/local-search`  
→ 기존 MCP 설정 수정 불필요

### API 호환성
- MCP 서버 인터페이스 유지
- 환경변수 이름 유지
- DB 경로 유지

### 실행/경로 규칙 (명시)
- 워크스페이스 루트는 `LOCAL_SEARCH_WORKSPACE_ROOT`가 있으면 우선 사용
- 없으면 **실행 시점의 현재 디렉토리**를 workspace root로 간주
- DB 경로는 기존 규칙 유지: `{workspace}/.codex/tools/local-search/data/index.db`
- 경로 기준은 MCP 서버 실행 프로세스 기준이며, CLI 래퍼는 `cwd`를 변경하지 않음

---

## 보안 및 모범사례

### npm 패키징
- `package-lock.json` 포함
- `.npmignore`로 불필요 파일 제외
- `--production` 플래그로 dev 의존성 제외
- `npm audit` 정기 실행

### Python 의존성
- `requirements.txt` 명시
- 최소 Python 버전: 3.8+

---

## 구현 체크리스트

### Phase 1: npm 패키지
- [ ] `ai-local-search` 신규 레포 생성 및 기본 구조 생성
- [ ] 기존 `.codex/tools/local-search/{app,mcp,config,scripts}`를 `ai-local-search/src/`로 이관
- [ ] `package.json`/`bin/ai-local-search`/`scripts/postinstall.js`/`.npmignore` 작성
- [ ] postinstall: 백업/옵트인/충돌 처리 동작 확인 (dry run)
- [ ] 로컬 테스트 (`npm link` + MCP initialize 호출)
- [ ] GitHub 레포 생성 및 초기 태그(v2.6.0)

### Phase 2: codex-forge 통합
- [ ] 기존 local-search 백업 절차/경로 정의
- [ ] 서브모듈 추가 및 고정 커밋 확인
- [ ] `install.sh` 수정(서브모듈 init + `npm install --production`)
- [ ] 마이그레이션 로직 추가(백업 후 교체)
- [ ] 테스트: 신규 설치에서 MCP 동작 확인
- [ ] 테스트: 기존 사용자 마이그레이션 후 MCP 동작 확인

### Phase 3: 배포
- [ ] `npm pack`으로 배포 산출물 검증
- [ ] npm publish
- [ ] README.md 업데이트(3가지 설치 방법 + 롤백)
- [ ] CHANGELOG.md 작성
- [ ] 마이그레이션 가이드 작성

---

## 실제 구현 범위/스케일 산정
- **대상 repo**: `codex-forge` (+ 신규 `ai-local-search` 레포)
- **변경 파일(예상)**:
  - `ai-local-search/package.json`
  - `ai-local-search/bin/ai-local-search`
  - `ai-local-search/scripts/postinstall.js`
  - `ai-local-search/.npmignore`
  - `ai-local-search/README.md`
  - `ai-local-search/requirements.txt`
  - `codex-forge/.codex/tools/local-search` (서브모듈화)
  - `codex-forge/install.sh`
  - 문서: `codex-forge/README.md`, 마이그레이션 가이드
- **예상 규모**: S2 (코드/설정 8~12 files, ~400~800 LOC)
- **변경 유형**: 배포/설치 UX, MCP 설정 자동화, 모듈 분리

## API 스펙 (요청/응답 JSON)
### MCP 설정 (Codex)
**요청**
```toml
[mcp_servers.local-search]
command = "npx"
args = ["@your-org/ai-local-search"]
```
**결과(설정 반영 후 기대 상태)**
```json
{
  "status": "ok",
  "server": "local-search",
  "mode": "mcp-stdio"
}
```

### MCP 설정 (Gemini)
**요청**
```json
{
  "mcpServers": {
    "local-search": {
      "command": "npx",
      "args": ["@your-org/ai-local-search"]
    }
  }
}
```
**결과(설정 반영 후 기대 상태)**
```json
{
  "updated": true,
  "backup_created": true
}
```

### postinstall 동작 (옵트인)
**요청**
```json
{
  "env": {
    "AI_LOCAL_SEARCH_CONFIG_WRITE": "1"
  },
  "targets": [".codex/config.toml", ".gemini/settings.json"]
}
```
**응답**
```json
{
  "written": [".codex/config.toml"],
  "skipped": [".gemini/settings.json"],
  "reason": "conflict_detected"
}
```

## 변경 후 테스트 시나리오
1) **정상 케이스**: `npx @your-org/ai-local-search`로 MCP 서버 기동 확인(실행 로그/종료 코드 0).
2) **경계/오류 케이스**: `AI_LOCAL_SEARCH_CONFIG_WRITE` 미설정 시 postinstall이 **설정 파일을 쓰지 않음** 확인.
3) **회귀 케이스**: 기존 codex-forge 설치 상태에서 서브모듈 마이그레이션 후 MCP 동작 동일(검색/상태 호출).
4) **마이그레이션**: `.codex/tools/local-search`가 디렉토리일 때 백업 생성 및 서브모듈로 대체 확인.

## 롤백 전략
- 서브모듈 롤백: `.codex/tools/local-search.bak-*`를 복구하여 이전 버전으로 되돌림.
- 설정 롤백: `.codex/config.toml.bak`, `.gemini/settings.json.bak` 복원.

## 오픈 이슈
- Python 런타임 의존성: `npx` 실행 시 시스템 `python3` 요구 여부 및 실패 메시지 정책.
- 기존 MCP 설정 충돌 시 우선순위/병합 규칙 확정.

## 참고 자료

- [Serena MCP](https://github.com/oraios/serena) — npx 패턴
- [npm Best Practices](https://snyk.io/blog/best-practices-create-modern-npm-package/)
- [MCP Specification](https://modelcontextprotocol.io/)

---

## 다음 단계

이 계획 승인 후:
1. Phase 1 구현 시작
2. 로컬 테스트
3. GitHub 레포 생성 및 npm 배포
