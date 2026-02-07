# 설계: Zero-Install 부트스트래퍼 아키텍처 (v11)

> **날짜**: 2026-01-31
> **단계**: Design (최종 상세 설계)
> **목표**: Local Search 도구를 설정 파일만으로 자동 설치(Just-in-Time Provisioning)하는 기술 설계.
> **최종 보강**: Sari 리브랜딩 상세 체크리스트, 리스크 대응, 구버전 정리 로직 추가.

## 1. 네이밍 및 경로 (확정)
- **MCP 도구명**: `sari`
- **리포지토리**: `sari`
- **설치 경로**: `.codex/tools/sari`
- **데이터 경로**: `.codex/tools/sari/data/index.db`
- **구버전 처리**: 설치 시 `.codex/tools/local-search` 발견 시 자동 삭제.

## 2. 상세 실행 체크리스트 (Implementation Checklist)

### Phase 1: `sari` (소스 코드 리팩토링)
- [ ] `mcp/server.py`: `SERVER_NAME = "sari"` 로 수정.
- [ ] `mcp/workspace.py`: `get_local_db_path` 내 경로 문자열 `"local-search"` -> `"sari"` 치환.
- [ ] `app/config.py`: `default_db_path` 및 설정 로드 경로 수정.
- [ ] `app/main.py`: HTTP 폴백 서버 기동 시 출력 메시지 수정.
- [ ] `README.md`: 프로젝트 명칭 및 예시 커맨드 업데이트.

### Phase 2: `horadric-forge-rules` (룰셋 리브랜딩)
- [ ] 모든 `.md` 파일 전수 조사 (`grep -r "local-search" .`)
- [ ] `00-core.md`, `01-checklists.md` 등 핵심 룰 파일 내 명칭 치환.
- [ ] `GEMINI.md`, `AGENTS.md` 템플릿 내 MCP 도구 이름 `sari`로 변경.

### Phase 3: `horadric-forge` (메타 및 인스톨러)
- [ ] `manifest.toml`: `[tools.sari]` 섹션으로 변경 및 ZIP URL 등록.
- [ ] `templates/bootstrap.sh`: 
    - [ ] `REQUIRED_VERSION`, `ZIP_URL` 플레이스홀더 추가.
    - [ ] Python 3.8+ 환경 정밀 체크 로직.
    - [ ] 동시성 제어 Lock (`provision.lock`) 로직.
    - [ ] 로그 파일(`logs/bootstrap.log`) 기록 로직.
- [ ] `install.sh`:
    - [ ] 대화형 Python 체크 (사용자 설치 유도).
    - [ ] 구버전(`.codex/tools/local-search`) 감지 및 삭제.
    - [ ] `bootstrap.sh` 동적 생성 및 설치.
    - [ ] `settings.json` (Gemini), `config.toml` (Codex) 설정 주입.

## 3. 리스크 대응 설계 (Risk Mitigation)

| 리스크 | 대응 방안 |
| :--- | :--- |
| **명칭 불일치** | MCP ID를 `sari`로 통일하고, 룰셋 내의 모든 참조를 전수 치환하여 AI 에이전트의 혼선을 방지함. |
| **데이터 오염** | 구버전 `local-search` 폴더를 삭제하여 설정/코드 충돌을 원천 차단함. |
| **동시 실행 충돌** | `mkdir` 기반의 Atomic Lock을 사용하여 여러 에이전트가 동시에 프로비저닝하는 것을 막음. |
| **사용자 설정 소실** | 업데이트 시 `config/` 디렉토리는 삭제 대상에서 제외하고, `cp -n` 방식으로 신규 파일만 추가함. |

## 4. 최종 DoD (Definition of Done)
1. `install.sh` 실행 시 Python이 없으면 적절한 안내가 나오는가?
2. 설치 후 `.codex/tools/sari/bootstrap.sh`가 생성되었는가?
3. Gemini/Codex CLI 실행 시 자동으로 도구가 다운로드되는가?
4. `/mcp` 호출 시 도구 이름이 `sari`로 표시되는가?
5. `sari scan` 후 인덱싱 데이터가 `test-workspace/.codex/tools/sari/data`에 생성되는가?
