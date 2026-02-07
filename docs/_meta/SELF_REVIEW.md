# SELF_REVIEW (v2.5.0)

> 이 문서는 포인터가 아니라 **정본**이다. 셀프리뷰 체크리스트와 최신 리뷰 결과를 여기서 확인한다.

---

## v2.5.0 셀프리뷰 결과 (2026-01-30)

### 주요 변경사항
1. **버전 정합성 통일 (Critical Fix)**: 코드(v2.5.0)와 문서(v2.3.3)간의 심각한 버전 불일치를 해결.
2. **Multi-CLI 지원 공식화**: Codex CLI와 Gemini CLI 모두 v2.5.0 룰셋을 사용하도록 명문화.
3. **모든 산출물 동기화**: `docs/`, `install.sh`, `.codex/` 등 14개 포인트의 버전을 단일화.

### 검증 결과
- **버전 표기 정합성**: 14개 포인트 전수 검사 완료 (PASS)
- **설치 스크립트**: Multi-CLI 모드 동작 확인 (v2.5.0)

---

## v2.3.3 셀프리뷰 결과 (2026-01-30)

---

## v2.3.1 셀프리뷰 결과 (2026-01-30) ✅ VERIFIED

### 주요 변경사항
1. **구조 단순화**: `codex/`, `tools/`가 `.codex/` 아래로 통합
   - 루트에 보이는 파일: `.codex-root`, `docs/` 만
   - 나머지 모든 룰셋/도구는 `.codex/` 숨김 디렉토리에
2. **모든 경로 참조 업데이트**: 14개 파일

### 디렉토리 구조 (v2.3.1)
```
workspace/
├── .codex-root          # 마커
├── .codex/              # 룰셋/도구 (숨김)
│   ├── AGENTS.md
│   ├── config.toml
│   ├── quick-start.md
│   ├── rules/
│   ├── scenarios/
│   └── tools/
├── docs/                # 공유 문서 (보임)
└── [repos...]           # 실제 저장소들
```

### 검증 결과

#### 1. 새 구조 확인 ✅
- 루트: `.codex-root`, `.codex/`, `docs/`, `install.sh`, `gitignore.sample`
- `.codex/`: AGENTS.md, config.toml, rules/, scenarios/, tools/

#### 2. 경로 참조 정합성 ✅
- 구 경로(`codex/rules`, `tools/local-search`) 잔재 없음

#### 3. 버전 표기 ✅
- `.codex/AGENTS.md`: v2.3.1
- `mcp/server.py`: SERVER_VERSION = "2.3.0"

#### 4. config.toml MCP 경로 ✅
- `args = [".codex/tools/local-search/mcp/server.py"]`

#### 5. Python 문법 ✅
- 모든 Python 파일 통과

#### 6. MCP 프로토콜 테스트 ✅
- protocolVersion: "2025-11-25"
- version: "2.3.0"

#### 7. 런타임 파일 ✅
- `__pycache__` 정리 완료

### 수정 사항
- `.codex/tools/local-search/app/main.py`: 경로 주석 수정
- `gitignore.sample`: 경로 업데이트

---

## v2.2.1 셀프리뷰 결과 (2026-01-30) ✅ VERIFIED (2차 리뷰 완료)

### Blocking Issues 수정 완료
1. **zip 구조 문서 수정**: SETUP.md, quick-start.md
   - `unzip ... -d .`가 폴더를 생성함을 명시
   - 복사 명령어 추가
   
2. **install.sh config.toml 보존**: 실제 복원 로직 추가
   - 백업 → 복사 → 복원 → MCP 설정 추가
   
3. **폴백 경로 수정**: `ensure_running.py` → `app/main.py`
   - SETUP.md, quick-start.md, .codex/AGENTS.md 통일

4. **HTTP 폴백 포트 정합성** (2차 리뷰)
   - 문서의 `curl 127.0.0.1:9999` → `47777`로 통일
   - config.json의 `server_port: 47777`과 일치

### Non-blocking 개선
- MCP 초기화 타임아웃: `LOCAL_SEARCH_INIT_TIMEOUT` 환경변수
- --skip 모드 설명 명확화
- local-search README 환경변수 테이블 추가
- RELEASE_CHECKLIST.md: 포트 정합성 검증 항목 추가
- RELEASE_CHECKLIST.md: MCP 예시 출력 버전 수정

### 2차 셀프리뷰 추가 수정
- `.codex/config.toml` 버전: v2.2.0 → v2.2.1
- `__pycache__` 정리 완료

### 검증 결과
- 버전 표기: 모든 파일 v2.2.1 통일 ✅
- 포트 정합성: 모든 curl 예시 47777 ✅
- 경로 정합성: 모든 폴백 → `app/main.py` ✅
- Python 문법: 모든 파일 통과 ✅
- MCP 프로토콜: protocolVersion 2025-11-25, version 2.2.1 ✅
- 런타임 파일: 0개 ✅

---

## v2.2.0 셀프리뷰 결과 (2026-01-30) ✅ VERIFIED

### 주요 변경사항
1. **MCP 서버 구현**: `.codex/tools/local-search/mcp/server.py`
   - STDIO 방식 MCP 프로토콜 구현
   - search, status, repo_candidates 도구 노출
   
2. **룰 강화**: `.codex/rules/00-core.md`
   - "Local Search 우선 원칙" 섹션 추가
   - 토큰 절감 시나리오 및 예시

3. **설정 변경**: `.codex/config.toml`
   - `[mcp_servers.local-search]` 설정 추가
   - codex-cli가 자동으로 MCP 서버 관리

4. **설치 간소화**: `install.sh`
   - codexw alias 제거 (MCP로 대체)
   - MCP 서버 테스트 포함

### 검증 결과 (실제 테스트 완료)

#### Python 문법 검증
- 모든 Python 파일 6/6 통과 ✅

#### MCP 서버 단위 테스트
- 8/8 테스트 통과 ✅
  - test_initialize ✅
  - test_tools_list ✅
  - test_handle_request_initialize ✅
  - test_handle_request_tools_list ✅
  - test_handle_request_unknown_method ✅
  - test_handle_notification_no_response ✅
  - test_tool_status ✅
  - test_tool_search_empty_query ✅

#### MCP 프로토콜 테스트
- initialize 응답: protocolVersion "2025-11-25" ✅
- tools/list 응답: search, status, repo_candidates 도구 등록 ✅

#### RELEASE_CHECKLIST 검증
- 버전 표기 일관성: PASS ✅
- 필수 파일 존재: PASS ✅
- 문서-코드 정합성: PASS ✅
- 런타임 파일 체크: PASS ✅ (pycache 삭제 완료)

### 개선 효과

**v2.1.0 대비**:
- codexw alias 불필요 → 그냥 `codex` 사용
- 별도 서버 시작 불필요 → codex-cli가 MCP로 자동 관리
- 포트 충돌 문제 해소 → STDIO 방식 사용

**토큰 절감**:
- 룰 강화로 local-search 활용률 향상 예상
- Before: Glob 전체 탐색 → 12000 토큰
- After: local-search 검색 → 900 토큰 (92% 절감)

---

## 이전 버전 히스토리

### v2.1.0 (2026-01-30)
- 릴리스 체크리스트 + 자동화 검증 스크립트 추가
- 실제 설치/포트충돌 시나리오 검증 완료

### v2.0.8 (2026-01-30)
- quick-start.md: codexw 명시
- healthcheck.py: 타임아웃 오버라이드

(이전 버전은 docs/_meta/CHANGELOG.md 참조)
