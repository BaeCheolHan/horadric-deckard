# Sari 레포 분석: 문제점 요약

작성일: 2026-02-05

## 범위
- 저장소 전반 정적 점검 (실행/테스트 미실시)

## 발견된 문제점 (요약)

### 1) 워크스페이스 리소스가 해제되지 않음 (높음)
- `sari/mcp/workspace_registry.py`의 `release()`는 ref_count를 줄이기만 하고, 0이 되었을 때 `stop()`/정리를 하지 않음.
- `active_count()`가 세션 수(`len(_sessions)`)만 반환하여, 한 번이라도 workspace가 생성되면 0으로 내려가지 않음.
- `sari/mcp/daemon.py`의 idle/drain 판단이 `active_count()`에 의존하므로, **idle 종료가 사실상 동작하지 않거나** 불필요하게 리소스가 계속 유지될 수 있음.

### 2) `rootUri` 파싱이 파일 URI 규격을 충분히 지원하지 않음 (중간)
- `sari/mcp/session.py`에서 `file://` 접두어를 단순히 잘라서 경로로 사용.
- `file://localhost/...` 또는 URL-encoding(`%20`) 케이스를 해석하지 못해 **workspace_root가 잘못 계산될 가능성**이 있음.

### 3) DB/인덱싱 오류가 조용히 누락될 수 있음 (중간)
- `sari/core/indexer/db_writer.py`에서 `DELETE` 실패 시 `except: pass`로 무시됨.
- `sari/core/indexer/main.py`에서 파일 이벤트/퍼블리시 오류가 `except: pass`로 무시됨.
- 결과적으로 **데이터 불일치나 인덱싱 누락이 관측되지 않고 누적**될 수 있음.

## 보완 제안 (요약)
- ref_count가 0일 때 workspace 정리/해제 로직 복구 + `active_count()` 기준을 ref_count 기반으로 변경.
- `rootUri` 파싱 시 `urllib.parse.urlparse` + `urllib.parse.unquote` 적용.
- `except: pass` 대신 최소한 경고 로그 추가 (특히 DB/인덱싱 경로).

## 적용 상태 (2026-02-05)
- ref_count=0 시 정리/해제 + active_count/last_activity_ts 기준 개선 적용
- file URI 파싱 개선(urlparse/unquote, localhost 허용)
- 인덱싱/DB 경로의 silent error를 warning 로그로 변경
