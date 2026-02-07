# Debt

- 룰 문서의 Deckard→sari 용어 변경과 실제 도구 경로(.codex/tools/sari) 존재 여부의 일치 확인 필요.
- Workspace detection 우선순위가 문서로만 정의되어 있어 코드 구현과 동기화 필요.
- 글로벌 설치 경로 git diverged 처리 로직이 install.py에 없음.
- MCP 클라이언트(rootUri 전달) 수정은 외부 의존으로 미해결 상태.
- 데몬/프록시/서버 경로가 분기되어 있어, 레지스트리/포트/워크스페이스 경로 동기화 문제 발생 시 진단 비용이 높다.
- `sari/mcp/test_server.py`는 레거시 import/경로 주석으로 수집 실패 상태라 MCP 회귀 보호가 불완전하다.
