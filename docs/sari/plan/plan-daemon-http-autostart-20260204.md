# 미니 스펙: 데몬 시작 시 HTTP 서버 자동 기동

## 배경/문제
- `sari status`는 HTTP 서버에 연결해야 동작한다.
- 현재 데몬은 실행 중이어도 워크스페이스가 초기화되지 않으면 HTTP 서버가 뜨지 않아, 사용자가 "연결 안됨" UX를 자주 경험한다.

## 목표
- `sari daemon start`로 데몬을 올리면 **현재 워크스페이스의 HTTP 서버도 자동으로 기동**한다.
- 데몬 종료 시 HTTP 서버도 함께 종료된다.

## 비범위
- 멀티 워크스페이스 자동 전환/동시 기동
- 원격/비루프백 접근 지원

## 변경 요약
- 데몬 시작 시 `SARI_DAEMON_AUTOSTART=1` 과 `SARI_WORKSPACE_ROOT`를 전달한다.
- 데몬은 환경 변수를 확인해 워크스페이스를 자동 초기화하고, 공유 상태를 유지(핀)하여 HTTP 서버를 지속 실행한다.
- `auto` 모드로 데몬을 띄울 때도 동일한 자동 기동 정책을 적용한다.

## 기대 효과
- `sari status`/웹페이지 등 HTTP 기반 기능이 데몬 시작 직후 즉시 사용 가능.
- "데몬은 켰는데 연결이 안됨" UX 감소.

## 위험/완화
- 자동 기동으로 인덱싱/DB 접근이 즉시 시작됨.
  - 완화: 루프백 강제 및 기존 설정/워크스페이스 해석 로직 재사용.

## 프리플라이트
- Deckard 검색 실패: `.codex/tools/deckard/scripts/query.py` 미존재
- 대체: `sari/README.md` 확인 (status/daemon UX 문서)

## 추가 고려
- 샌드박스/권한 제한 환경에서는 PID 파일 경로가 쓰기 불가일 수 있음.
  - `SARI_DATA_DIR`(또는 `SARI_GLOBAL_DATA_DIR`)로 글로벌 데이터 디렉터리를 재지정 가능.
- 레거시 DB에서 `symbols.qualname`/`symbol_id` 누락 시 인덱스 생성 실패를 방어하도록 마이그레이션 보강.
- `sari status` UX 개선: 데몬/HTTP 상태를 분리 출력해 원인 진단 가능.
- 데몬 포트 점유 시 PID 누락 경고 및 포트 변경 힌트 제공.
- 문서 보강: 포트 충돌 시 해결 방법 추가 (README).
- 릴리즈 버전: 0.1.15.
- 문서 보강: 데몬+HTTP 동시 실행 가이드 추가 (README).
- 무중단 옵션: `--daemon-port/--http-port` 지원 및 문서화.
- HTTP 서버는 `http_api_host/http_api_port` 설정을 사용하도록 일치시킴.
- CLI가 데몬을 띄울 때 로컬 코드 사용을 보장하도록 PYTHONPATH 및 cwd를 조정.
- 릴리즈 버전: 0.1.17.
- 문서 보강: install.py 업데이트 명령 및 재시작 절차 추가.
- 자동 발견: `sari status`가 server.json의 실제 HTTP 포트를 우선 사용.
- 자동 발견 보강: global registry(~/.local/share/sari/server.json) 우선 조회.
- status는 HTTP가 살아있으면 성공하도록 완화.
- 릴리즈 버전: 0.1.18.
- registry fallback: cwd/parent match or single instance 선택.
- 릴리즈 버전: 0.1.19.
- registry 우선순위 수정: config보다 registry/서버정보를 우선.
- 릴리즈 버전: 0.1.20.
- install.py 부트스트랩이 `python3 -m sari.main`으로 실행되도록 수정.
- 릴리즈 버전: 0.1.21.
- 데몬 포트는 global registry(~/.local/share/sari/server.json)로 등록/조회하도록 정리.
- HTTP 포트는 workspace-local server.json 사용.
- 릴리즈 버전: 0.1.22.
- 부트스트랩이 free port 선택 + 새 데몬 자동 기동 (무중단 UX).
- 릴리즈 버전: 0.1.23.
