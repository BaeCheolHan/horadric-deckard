# Sari (사리) - 로컬 코드 검색 에이전트

**Sari**는 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)를 구현한 고성능 **로컬 코드 검색 에이전트**입니다. AI 어시스턴트(Claude, Cursor, Codex 등)가 코드를 외부 서버로 전송하지 않고도 대규모 코드베이스를 효율적으로 탐색하고 이해할 수 있도록 돕습니다.

[English README](README.md)

> **핵심 기능:**
> - ⚡ **빠른 인덱싱:** SQLite FTS5 + AST 기반 심볼 추출 (초당 1,000개 이상의 파일 처리).
> - 🌐 **다중 워크스페이스:** 하나의 백그라운드 데몬으로 여러 프로젝트를 동시에 관리.
> - 🧠 **코드 인텔리전스:** 콜 그래프, 스니펫 관리, 도메인 컨텍스트 아카이빙.
> - 🩺 **자가 치유:** 환경 문제를 자동으로 진단하고 해결하는 내장 `doctor` 기능.
> - 🔒 **로컬 보안:** 모든 데이터는 사용자 로컬 머신에만 저장됩니다.

---

## 🚀 설치 및 빠른 시작

1. 설치 스크립트 실행:
```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - -y --update
```

2. 프로젝트 루트에서 초기화 및 실행:
```bash
cd /absolute/path/to/your/project
sari init
sari daemon start -d
```

3. MCP 클라이언트에 연결 (아래 **클라이언트 연동** 섹션 참조).

---

## 🌐 다중 워크스페이스 지원

Sari는 자원 소모를 최소화하면서 여러 코드베이스를 동시에 처리하도록 설계되었습니다.

### 작동 원리:
- **공유 데몬**: 시스템 전체에서 단 하나의 백그라운드 데몬만 실행됩니다.
- **자동 감지**: Cursor나 Claude에서 새로운 프로젝트를 열면, Sari가 실행 중인 데몬을 찾아 새 워크스페이스를 자동으로 등록합니다.
- **격리된 환경**: 각 프로젝트는 독립적인 SQLite DB와 HTTP 포트를 갖지만, 메모리와 프로세스 자원은 효율적으로 공유합니다.

### 중첩 방지 (Overlap Prevention):
실수로 상위 폴더와 하위 폴더를 동시에 등록한 경우(예: `~/Documents`와 `~/Documents/Project`), `sari doctor`가 **Workspace Overlap** 경고를 보내 중복 인덱싱과 데이터 가비지 생성을 방지합니다.

---

## 🔌 클라이언트 연동

### 자동 설정 (권장)
```bash
sari --cmd install --host cursor # 가능 호스트: cursor, codex, gemini, claude
```

### 수동 설정 (Stdio 방식)
`mcpSettings.json` 또는 `.cursorrules` 예시:
```json
{
  "mcpServers": {
    "sari": {
      "command": "sari",
      "args": ["--transport", "stdio", "--format", "pack"],
      "env": {
        "SARI_WORKSPACE_ROOT": "/absolute/path/to/project"
      }
    }
  }
}
```

---

## 🩺 점검 및 유지보수

### Sari Doctor (전문 주치의)
Sari가 응답하지 않거나 인덱싱이 느리다면 닥터를 실행하세요:
```bash
sari doctor --auto-fix
```
닥터는 다음 항목을 진단하고 자동으로 고칩니다:
- **버전 불일치**: 이전 설치로 인한 구버전 데몬 생존 확인.
- **좀비 PID**: 포트를 점유하고 있는 죽은 프로세스 정리.
- **레지스트리 복구**: 손상된 `server.json` 파일 재구성.
- **DB 무결성**: SQLite 데이터 파일의 물리적 손상 여부 체크.
- **로그 정밀 검사**: 최근 로그에서 "Database Locked"나 메모리 부족 징후 포착.

### 성능 모니터링
Sari는 스스로의 성능을 추적합니다. 실시간 지표를 확인하세요:
```bash
sari status
```
리포트의 `slow_files` 항목을 통해 인덱싱 속도를 저하시키는 크고 복잡한 파일들을 파악할 수 있습니다.

---

## ⚙️ 고급 설정 (환경 변수)

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `SARI_WORKSPACE_ROOT` | 워크스페이스 경로 수동 지정. | 자동 감지 |
| `SARI_DAEMON_PORT` | 데몬 TCP 포트. | `47779` |
| `SARI_STORE_CONTENT_COMPRESS` | DB 저장 시 zlib 압축 활성화 (용량 절약). | `0` |
| `SARI_DEV_JSONL` | 구버전 JSONL 프레이밍 허용 (개발용). | `0` |
| `SARI_MCP_DEBUG_LOG` | MCP 디버그 트래픽 로그(`mcp_debug.log`) 활성화(마스킹 적용). | `0` |
| `SARI_ALLOW_LEGACY` | 레거시 fallback(비네임스페이스 env / legacy root-id) 옵트인. | `0` |

---

## ✅ 필수 테스트 게이트

치명 경로(서버 크래시, 동시성 프레이밍, 의존성 드리프트)는 일반 유닛 테스트와 별도로 게이트 테스트를 통과해야 합니다.

```bash
pytest -m gate -q
```

로컬 필수 실행(게이트 + 스모크 세트 순차 실행):

```bash
./scripts/verify-gates.sh
```

핵심 스모크 세트:

```bash
pytest -q tests/test_core_main.py tests/test_engines.py tests/test_server.py tests/test_search_engine_mapping.py
```

---

## 🧭 최근 런타임 변경사항 (1.0.3+)

- **통합 DB 단일 정책 유지**: Sari는 계속 전역 단일 DB(`~/.local/share/sari/index.db`)를 사용합니다.
- **쓰기 경합 안정화**:
  - SQLite `busy_timeout` 적용
  - 프로세스 간 write gate 락(`.write.lock`) 추가
  - 멀티 워크스페이스 동시 인덱싱 안정성 강화
- **MCP 디버그 로그 보안 강화**:
  - 디버그 트래픽 로깅 기본값을 **비활성화**
  - `SARI_MCP_DEBUG_LOG=1`일 때만 활성화
  - 요청/응답 전문 덤프 대신 요약/마스킹(redaction) 기록
- **워크스페이스 root-id 경계 안정화**:
  - 중첩 워크스페이스 대응을 위해 명시 루트 기준 `root_id_for_workspace` 경로 추가
  - 기본 path resolve는 명시 워크스페이스 스코프를 우선 사용
- **레거시 호환은 옵트인**:
  - 기본은 엄격 모드(`SARI_*` 네임스페이스 환경변수만 사용)
  - 필요 시에만 `SARI_ALLOW_LEGACY=1`로 레거시 fallback 허용

---

## 🗑️ 제거 (Uninstall)
Sari와 관련된 모든 로컬 데이터(DB, 로그, 레지스트리)를 완전히 삭제하려면:
```bash
# macOS/Linux
curl -fsSL https://raw.githubusercontent.com/BaeCheolHan/sari/main/install.py | python3 - --uninstall
```

---

## 📜 라이선스
Apache License 2.0
