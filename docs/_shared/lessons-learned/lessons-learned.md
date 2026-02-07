# Lessons Learned

- 룰 문서에서 Deckard 용어를 sari로 통일할 때, 관련 도구 경로/실체 일치 여부를 함께 점검해야 한다.
- Codex MCP initialize는 rootUri/workspaceFolders를 전달하지 않는 경우가 있으므로, Sari는 CWD/`.codex-root` 기반 fallback이 필요하다.
- MCP proxy 로그는 stderr만으로는 확인이 어렵다. sari.log로 기록하는 경로가 필요하다.
- 글로벌 설치(클론) 경로는 git diverged가 발생할 수 있어, install 시 rebase/backup 정책을 안내해야 한다.
- MCP stdio 프로토콜 안정성을 위해 `sari/main.py`가 stdout을 stderr로 전환한다. CLI 출력 스트림은 반드시 이 전제를 고려해야 한다.
- MCP `tools/call` 경로는 단위 테스트가 없으면 속성 참조 결함이 런타임에서 바로 크래시로 이어진다. 서버 경로 테스트를 최소 1개 이상 유지해야 한다.
- 선택적 의존성(`tantivy`)은 범위 지정(`>=`)만 두면 배포 환경별 드리프트가 발생하므로, 런타임 API 민감 구간은 버전 핀과 게이트 테스트를 같이 운영해야 한다.
- MCP stdio 병렬 응답 처리에서는 `write_message`를 잠금 없이 호출하면 프레임이 섞일 수 있다. 출력 구간 직렬화 테스트를 반드시 포함해야 한다.
- 커버리지율만으로 치명 결함을 막을 수 없다. `pytest -m gate`처럼 실패 경로 중심 게이트를 CI 필수 단계로 강제해야 한다.
- 경로 정규화에서 루트(`/`)가 빈 문자열로 축약되면 워크스페이스 경계 검증이 붕괴한다. normalize 단계에서 루트 보존을 강제해야 한다.
- `root-.../rel` 포맷 입력은 rel 부분에 대해 traversal(`..`) 검증을 별도로 수행해야 한다.
- Mock 중심 테스트만으로는 런루프/프레이밍/소켓 수명 주기 결함을 놓치기 쉽다. 최소 1개 이상은 실제 프레이밍 I/O를 타는 통합 게이트를 유지해야 한다.

### 2026-02-01: Sari 구조 및 성능 개선
- **문제**: 여러 진입점(Main, MCP Server, Proxy) 간의 워크스페이스/설정 감지 로직이 파편화되어 동작 예측이 어렵고, 소켓 통신 시 개행 문자가 포함된 JSON 처리 시 리스크가 있었음.
- **해결**: 
  - `app/workspace.py`로 모든 감지 로직을 통합하여 SSOT(Single Source of Truth) 확보.
  - 소켓 프로토콜을 JSONL에서 Content-Length 프레임 방식으로 전환하여 안정성 강화.
  - `last_seen` 컬럼 기반 삭제 감지 및 `approx` 카운트 최적화로 대형 워크스페이스 성능 개선.
- **교훈**: 시스템의 규모가 커질수록 경로 결정 및 통신 규약과 같은 기초 인프라 로직은 조기에 단일 모듈로 통합 관리하는 것이 유지보수와 신뢰성 측면에서 필수적임.
