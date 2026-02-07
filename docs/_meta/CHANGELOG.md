# Changelog

## v2.5.0 (2026-01-30)

### 🔧 Fixes (Version Consistency)
- **버전 정합성 통일**: 코드(v2.5.0)와 문서(v2.3.3/v2.4.2)간의 불일치 해소
- **모든 산출물 동기화**: `docs/`, `install.sh`, `.codex/` 등 14개 포인트의 버전을 `v2.5.0`으로 단일화
- **Multi-CLI 지원 공식화**: Gemini CLI와 Codex CLI 모두에 대해 `v2.5.0` 룰셋 적용
- **설치/삭제 스크립트 개선**: `install.sh`의 히어닥 문법 오류 수정 및 `uninstall.sh`에 `docs/` 보존 여부 확인 로직 추가 (안전장치)

---

## v2.4.2 (2026-01-30)

### ✨ Local Search UX & 안정성 개선
- **Multi-Workspace 지원**: DB 경로를 워크스페이스 로컬(`/data/index.db`)로 강제하여 여러 워크스페이스 동시 실행 시 충돌 방지
- **검색 결과 메타데이터 강화**:
  - `scope`: 검색 범위(workspace 또는 특정 repo) 명시
  - `index_status`: 인덱싱된 총 파일 수 및 마지막 스캔 시간 포함
- **Zero Result UX 개선**: 결과가 없을 때 상세 이유(`fallback_reason`) 및 검색 팁(`hints`) 자동 제안
- **AGENTS.md 구조 개선**: Workspace root에 포인터 파일을 생성하여 Codex CLI 진입점 최적화

### v2.4.0 (2026-01-30) (보관용)
... (기존 내용) ...


### 🎯 Major Changes (Multi-CLI 지원)
- **Gemini CLI 지원**: Codex CLI와 Gemini CLI 모두 지원
  - `GEMINI.md`: Gemini CLI 진입점 (workspace root)
  - `.gemini/settings.json`: Gemini CLI MCP 설정
  - `@./path.md` import 문법으로 기존 rules 재사용

- **설치 옵션 추가**: CLI 선택 가능
  - `--codex`: Codex CLI만 설치
  - `--gemini`: Gemini CLI만 설치
  - `--all`: 모두 설치 (기본값)
  - 대화형 프롬프트 지원

### ✨ Local Search 개선
- **`list_files` 도구**: 인덱싱된 파일 목록 조회 (디버깅용)
- **검색 메타데이터 강화**: repo 선택 이유 표시
- **`include_hidden` 옵션**: 숨김 디렉토리(.codex) 포함 여부 명시

### 📁 새 디렉토리 구조
```
workspace/
├── .codex/              # 공유 (rules, tools, scenarios)
│   ├── AGENTS.md        # Codex CLI 진입점
│   └── config.toml      # Codex CLI MCP 설정
├── .gemini/             # Gemini CLI 전용
│   └── settings.json    # Gemini CLI MCP 설정
├── GEMINI.md            # Gemini CLI 진입점
└── ...
```

### 📦 변경된 파일
- `install.sh`: CLI 선택 로직 추가
- `README.md`: Multi-CLI 안내
- `.codex/AGENTS.md`: Gemini CLI 참조 추가
- `.codex/tools/local-search/mcp/server.py`: 신규 도구 추가

---

## v2.3.3 (2026-01-30)

### 🧹 Docs & Meta
- **버전 표기 정합성**: CHANGELOG/SELF_REVIEW/RELEASE_CHECKLIST/system-prompt 정리
- **VERSIONING 갱신**: 실제 파일 기준으로 버전 표기 위치 재정리
- **릴리스 체크리스트**: v2.3.3 예시/경로 업데이트
- **설치 흐름 개선**: 인자 미지정 시 현재 경로 + git 소스 다운로드 지원
- **설치 UX 개선**: rules 덮어쓰기 확인 프롬프트 + config.toml MCP 설정 병합
- **설치 안정성**: 동일 repo 실행 시 로컬 소스 스냅샷으로 자기 덮어쓰기 방지
- **local-search 인덱싱**: docs 기본 포함 + 루트 파일 인덱싱 허용
- **캐시 경로 변경**: `~/.cache/codex-local-search` → `~/.cache/local-search` (자동 마이그레이션)

---

## v2.3.1 (2026-01-30)

### ✨ New Features (검색 기능 강화)
- **파일 타입 필터**: `file_types: ["py", "ts"]`로 특정 확장자만 검색
- **경로 패턴 매칭**: `path_pattern: "src/**/*.ts"`로 경로 필터
- **제외 패턴**: `exclude_patterns: ["node_modules", "test"]`로 제외
- **최근 파일 우선순위**: `recency_boost: true`로 최근 수정 파일 상위 노출
- **정규식 검색**: `use_regex: true`로 정규식 패턴 검색
- **대소문자 구분**: `case_sensitive: true` (정규식 모드에서)
- **컨텍스트 라인 조절**: `context_lines: 10`으로 snippet 크기 조절

### 🎨 검색 결과 개선
- 매칭 라인 하이라이트 (`>>>키워드<<<` 마커)
- 파일 메타데이터 포함 (mtime, size, file_type, match_count)
- 현재 라인 표시 (`→L15:` vs ` L14:`)

### 📦 변경된 파일
- `.codex/tools/local-search/app/db.py`: SearchOptions 클래스, search_v2() 메서드 추가
- `.codex/tools/local-search/mcp/server.py`: MCP 스키마에 새 옵션 추가
- `.codex/tools/local-search/README.md`: 사용 예시 추가

---

## v2.3.0 (2026-01-30)

### 🎯 Major Changes (구조 단순화)
- **Workspace 정리**: 루트 레벨 파일 수를 최소화
  - Before: `.codex-root`, `.codex/`, `codex/`, `tools/`, `docs/`, `AGENTS.md`, `SETUP.md` 등
  - After: `.codex-root`, `.codex/`, `docs/` 만 (깔끔!)
  
- **경로 구조 통합**: 모든 codex 관련 파일을 `.codex/` 아래로 이동
  - `codex/rules/` → `.codex/rules/`
  - `codex/scenarios/` → `.codex/scenarios/`
  - `tools/local-search/` → `.codex/tools/local-search/`
  - `codex/quick-start.md` → `.codex/quick-start.md`
  - 루트의 `AGENTS.md`, `SETUP.md` 등 → `.codex/` 또는 `docs/_meta/`

- **모든 경로 참조 업데이트**: 14개 파일

### 📁 새 디렉토리 구조
```
workspace/
├── .codex-root          # 마커
├── .codex/              # 룰셋/도구 (숨김)
│   ├── AGENTS.md
│   ├── config.toml
│   ├── quick-start.md
│   ├── rules/
│   ├── scenarios/
│   ├── skills/
│   └── tools/
├── docs/                # 공유 문서 (보임)
└── [repos...]           # 실제 저장소들
```

### ✅ 개선 효과
- **시각적 정돈**: repo 폴더가 룰셋 파일에 묻히지 않음
- **명확한 구분**: 사용자 repo vs. 시스템 파일
- **유지보수성**: 모든 룰셋 파일이 단일 디렉토리에

---

## v2.2.1 (2026-01-30)

### 🐛 Bug Fixes (Blocking Issues)
- **zip 구조 문서 수정**: SETUP.md, quick-start.md의 수동 설치 안내가 실제 zip 구조와 일치하도록 수정
  - 이전: `unzip ... -d .` → `.codex/, codex/ 생성됨` (틀림)
  - 이후: zip은 `codex-rules-v2.2.1-workspace-msa/` 폴더 생성 → 복사 필요
- **install.sh config.toml 보존**: 백업된 사용자 설정을 실제로 복원하도록 로직 수정
  - 이전: 백업 후 덮어쓰기 → 복원 안함 → 설정 유실
  - 이후: 백업 → 복사 → 복원 → MCP 설정 추가
- **폴백 경로 수정**: 존재하지 않는 `ensure_running.py` 대신 `app/main.py` 안내
  - SETUP.md, quick-start.md, .codex/AGENTS.md의 폴백 경로 통일

### 🐛 Bug Fixes (2차 리뷰)
- **HTTP 폴백 포트 정합성**: 문서의 `curl 9999` → `47777`로 통일 (config.json과 일치)
- **.codex/config.toml 버전**: v2.2.0 → v2.2.1
- **RELEASE_CHECKLIST 예시 버전**: MCP initialize 출력의 version 2.2.0 → 2.2.1

### ⚡ Non-blocking Improvements
- **MCP 초기화 타임아웃**: `LOCAL_SEARCH_INIT_TIMEOUT` 환경변수 지원 (대형 워크스페이스용)
- **--skip 모드 설명**: "디렉토리 단위 스킵"임을 명확히 안내
- **local-search README**: 환경변수 테이블 추가, 폴백 동선 명확화
- **RELEASE_CHECKLIST**: 포트 정합성 검증 항목 추가

---

## v2.2.0 (2026-01-30)

### 🎯 Major Changes (MCP 통합)
- **MCP 서버 구현**: `.codex/tools/local-search/mcp/server.py`
  - STDIO 방식 MCP 프로토콜 구현
  - codex-cli가 자동으로 lifecycle 관리
  - 도구: search, status, repo_candidates

- **룰 강화**: `.codex/rules/00-core.md`
  - "Local Search 우선 원칙" 섹션 추가
  - 토큰 절감 시나리오 및 Before/After 예시

- **설정 변경**: `.codex/config.toml`
  - `[mcp_servers.local-search]` 설정 추가

- **설치 간소화**: `install.sh`
  - codexw alias 제거 (MCP로 대체)
  - MCP 서버 테스트 포함

### ✅ 개선 효과
- **UX**: codexw 불필요 → 그냥 `codex` 사용
- **자동화**: 별도 서버 시작 불필요 → MCP가 관리
- **안정성**: 포트 충돌 해소 → STDIO 방식 사용
- **토큰**: 룰 강화로 local-search 활용률 향상

### Documentation
- 모든 버전 표기 v2.2.0 통일
- MCP 통합 가이드 추가

---

## v2.1.0 (2026-01-30)

### 🎯 Major Changes (버그 재발 방지 시스템)
- **RELEASE_CHECKLIST.md** (신규): 7단계 릴리스 검증 절차 + 문서-코드 대조표
- **tools/verify-release.sh** (신규): 자동화 검증 스크립트
- **실제 설치 테스트**: macOS clean 환경에서 전체 설치/포트충돌 시나리오 검증 완료

### ✅ Verified Features
- 포트 정책: 47777 충돌 → 47778 자동 선택
- 안전 설치: 기존 파일 백업/건너뛰기/중단 선택
- 환경 호환성: ~/Documents vs ~/documents 자동 감지
- codexw alias: 기존 codex 충돌 방지
- 타임아웃: LOCAL_SEARCH_HEALTH_TIMEOUT 오버라이드

---

## v2.0.8 (2026-01-30)

### Bug Fixes
- quick-start.md: codexw 명시 (codex vs codexw 혼동 해소)
- healthcheck.py: LOCAL_SEARCH_HEALTH_TIMEOUT 오버라이드 지원
- config.toml 주석: 일관된 톤으로 수정

### Documentation
- local-search 문서 중복 제거 (docs/_shared → 포인터)

---

## v2.0.7 (2026-01-30)

### Bug Fixes
- install.sh: codexw alias로 기존 codex 충돌 방지
- install.sh: WORKSPACE_ROOT 기준 상대 경로 계산
- ensure_running.py: healthcheck 타임아웃 5초

---

## v2.0.6 (2026-01-30)

### Bug Fixes
- SETUP.md: v2.0.4 잔재 제거
- quick-start.md: v2.0.3 잔재 제거
- install.sh: --backup/--skip/--quit 비대화형 옵션

---

## v2.0.5 (2026-01-30)

### Bug Fixes
- install.sh: 기존 파일 덮어쓰기 방지 (backup/skip/quit)
- install.sh: .codex/config.toml 보호
- 포트 폴백: OS가 할당한 포트 추적

---

## v2.0.4 (2026-01-30)

### Bug Fixes
- 포트 자동 선택: 47777 충돌 시 47778 → server.json/status 추적
- query.py status: 호스트/포트 출력

---

## v2.0.0 - v2.0.3 (2026-01-30)

### Major Refactoring
- 룰셋 구조 단순화
- 정본/포인터 체계 도입
- MSA workspace 지원
- local-search Python 도구
- 온보딩 가이드 (Quick Start)
