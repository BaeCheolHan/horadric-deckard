# Sari UX 정책 구현 설계 (다중 CLI/워크스페이스, 무중단 업데이트, 종료 정책)

작성일: 2026-02-05  
범위: 실행/업데이트/종료 UX를 정책 수준으로 안정화하는 코드 변경 설계

---

## 1. 목표
1. **다중 CLI/다중 워크스페이스 동시 실행**
   - A 워크스페이스에서 Gemini/Codex 다중 CLI 동시 실행 가능
   - A/B 워크스페이스를 동시에 처리 가능
   - **동일 워크스페이스에는 데몬 1개만 재사용**

2. **무중단 업데이트**
   - 업데이트 중에도 기존 CLI가 끊김 없이 계속 동작
   - 새 데몬이 뜨면 구 데몬/HTTP는 **graceful 종료**
   - 새 CLI는 항상 최신 데몬에 연결

3. **종료 정책 명확화**
   - CLI 종료 ≠ 데몬 종료
   - 워크스페이스 단위 리소스(refcount=0)만 정리
   - 데몬 전체 종료는 **명시적 stop 또는 idle TTL**

---

## 2. 핵심 설계

### 2.1 Daemon Registry v2 (SSOT)
**파일**: `~/.local/share/sari/server.json` (기존 경로 유지)  
**목표**: 워크스페이스 ↔ 데몬 매핑을 명확히 하고, 재사용/업데이트 판단 근거 제공.

**스키마 제안**
```json
{
  "version": "2.0",
  "daemons": {
    "<boot_id>": {
      "host": "127.0.0.1",
      "port": 47791,
      "pid": 12345,
      "version": "0.1.24",
      "start_ts": 1234567890,
      "last_seen_ts": 1234567891,
      "draining": false
    }
  },
  "workspaces": {
    "/abs/path/A": {
      "boot_id": "<boot_id>",
      "last_active_ts": 1234567892,
      "http_host": "127.0.0.1",
      "http_port": 47777
    }
  }
}
```

**규칙**
- 하나의 데몬이 여러 워크스페이스를 담당 가능  
- 워크스페이스는 **boot_id로 데몬을 참조**  
- 업데이트 시 **workspaces 맵을 새 boot_id로 교체**, 구 데몬은 drain  
- 구 버전 레지스트리(1.0)는 읽기 시 자동 마이그레이션  

**추가 규칙**
- `boot_id`는 PID 재사용 문제를 방지하기 위한 고유 토큰
- registry 파일 경로는 `SARI_REGISTRY_FILE`로 override 가능
- atomic write: 임시파일 + rename으로 갱신
- 동시 접근은 파일 락으로 보호 (Windows는 별도 구현 필요)
- workspace 경로는 `resolve()`로 정규화해 중복 방지
- 데몬은 주기적으로 `last_seen_ts` 갱신 (heartbeat)
- 클라이언트 요청마다 workspace의 `last_active_ts` 갱신
- registry 조회 시 dead PID는 정리(cleanup)

---

### 2.2 데몬 재사용 (Policy 1 핵심)
**흐름 (CLI/Proxy 공통)**
1. 워크스페이스 루트 결정
2. registry에서 워크스페이스 매핑 조회
3. 있으면 `sari/identify`로 데몬 검증  
4. 정상이면 해당 데몬 재사용  
5. 없거나 검증 실패면 새 데몬 기동 후 registry 업데이트  
6. **경합 처리**: 새 데몬 기동 직후 registry 재조회 후 최신 매핑이 있으면 그쪽 우선

**의도**
- 동일 워크스페이스 중복 데몬 방지  
- 다중 CLI 동시 실행 안정화  

**동시성/경합 보완**
- CLI A/B가 동시에 시작해도 registry 락 + 재조회로 1개 데몬만 남도록 보장
- `--daemon-port` 명시 시에는 자동 포트 변경 금지
- 포트가 이미 사용 중이고 Sari가 아니면 새 포트로 재시도
- workspace 매핑이 없으면 **기본 포트의 Sari 공유** → 없으면 새 데몬 기동
- 업데이트 판단: `sari/identify.version` 불일치 또는 `draining=true`이면 새 데몬 기동

---

### 2.3 무중단 업데이트 (Policy 2 핵심)
**핵심 아이디어**:  
CLI/Proxy는 **registry 기반 재연결**로 무중단을 보장하고,  
데몬은 registry 갱신을 통해 “새 데몬이 active”임을 표시.

**동작**
- 새 데몬 기동 → registry에서 workspace → new_pid로 교체
- 구 데몬은 주기적으로 registry 확인  
  - 자신이 담당하던 workspace가 다른 pid로 바뀌면  
    refcount==0일 때 graceful 종료  
  - refcount>0이면 drain 모드로 전환 후 일정 시간 대기
- Proxy/CLI는 소켓 끊김 시:
  - registry 재조회
  - 새 데몬으로 재연결 + initialize 재전송

**보완 규칙**
- Proxy는 최초 `initialize` 요청을 캐시하고 재연결 시 재전송
- in-flight 요청은 best-effort (끊김 시 실패 가능, 이후 요청은 정상)
- 데몬은 drain 모드에서 신규 세션을 거부하고 기존 세션만 유지
- drain timeout 초과 시 강제 종료 가능 (예: 30~60초)

---

### 2.4 종료 정책 (Policy 3)
- 워크스페이스 단위 refcount (현재 구조 유지)
  - refcount==0 → indexer/DB/HTTP 종료
- 데몬 전체 종료
  - 명시적 `sari daemon stop`
  - 또는 `SARI_DAEMON_IDLE_SEC` (예: 600초) 이후 자동 종료
- idle 판단은 **active workspace refcount==0 지속 시간** 기준

---

### 2.5 프로토콜/호환성
- `sari/identify`는 내부 헬스체크용 private 메서드로 취급
- 구버전 데몬에는 `sari/identify`가 없을 수 있으므로
  - fallback은 `ping` + "Server not initialized" 응답 패턴으로 판별
- proxy는 JSONL/Content-Length 모드 모두 유지하며 재연결 시 동일 모드 사용
- identify 결과에 `version`이 없으면 "dev"로 처리

---

## 3. 변경 포인트(파일)
- `sari/core/registry.py`  
  - registry v2 스키마 + 마이그레이션 + 업데이트/조회 API 추가
- `sari/mcp/daemon.py`  
  - 데몬 시작 시 registry 등록 강화  
  - 주기적 registry 체크(업데이트 감지)
- `sari/mcp/registry.py`  
  - workspace 생성/제거 시 registry 상태 갱신
- `sari/mcp/proxy.py`  
  - 소켓 끊김 시 자동 재연결 + initialize 재전송
- `sari/mcp/cli.py`  
  - registry 우선 데몬 재사용  
  - identify 실패 시 신규 데몬 생성  
  - 포트 충돌 자동 해결
- `bootstrap.sh`, `bootstrap.bat`, `install.py`  
  - 기존 데몬 재사용/업데이트 시나리오 반영
- `sari/core/http_server.py`
  - 워크스페이스별 HTTP 포트 fallback 시 registry에 기록
- `sari/core/main.py`
  - 워크스페이스별 HTTP server.json 갱신 시 registry와 일치시키는 보완
- `sari/core/workspace.py`
  - registry 경로 결정 규칙 정리 (SARI_REGISTRY_FILE 우선)

---

## 4. 종료 정책 상세 (제안)
1. **워크스페이스 리소스 종료**
   - refcount==0이면 바로 종료 (현재 동작 유지)
   - 옵션: `SARI_WORKSPACE_IDLE_SEC`로 지연 종료 가능
2. **데몬 종료**
   - `sari daemon stop`은 즉시 종료
   - idle TTL: 모든 workspace refcount==0 상태가 일정 시간 지속되면 종료
3. **업데이트 후 구 데몬 종료**
   - registry에서 해당 데몬이 담당하는 workspace가 0개가 되면 종료
   - drain 모드에서 신규 세션 차단

---

## 5. 리스크/대응
- **경합**: registry 동시 접근 시 파일 락 필요 (현재 fcntl 사용)
- **유령 데몬**: PID 살아있지 않으면 registry에서 무시
- **in-flight 요청 손실**: 재연결 시 일부 요청 손실 가능 → best-effort 정책 명시
- **윈도우**: 파일 락 구현 확인 필요
- **PID 재사용**: boot_id로 해결
- **HTTP 포트 동기화**: fallback 포트를 registry/워크스페이스 상태에 기록
- **구버전 데몬 판별**: `ping` fallback 규칙 명시
- **레거시 server.json 혼선**: HTTP용 server.json은 유지하되 SSOT는 registry로 명확히 규정

---

## 6. 검증 항목
1. 동일 워크스페이스 CLI 2개 → 데몬 1개만 사용
2. A/B 워크스페이스 동시 연결 → 동일 데몬 처리
3. 업데이트 후 기존 CLI 지속 동작

---

## 7. 패치 메모 (2026-02-05)
- Registry 저장을 atomic write + lockfile로 보강
- Proxy suppress_ids 접근을 동일 락으로 보호
- 내부 initialize 응답 억제용 id를 유니크 음수로 생성
4. 구 데몬 graceful 종료 확인
5. refcount=0일 때 워크스페이스 리소스만 종료, 데몬 유지
6. 포트 충돌 상황에서 Sari 데몬 식별/재사용 동작
7. proxy 재연결 + initialize 재전송 검증
