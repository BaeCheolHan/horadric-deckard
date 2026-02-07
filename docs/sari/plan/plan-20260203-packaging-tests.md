# [08] 패키징/테스트 전략 v1

[scope][packaging][pypi]
**목표**: PyPI 표준 배포를 지원하고 설치 안정성을 확보한다.
**원칙**: 배포명/entrypoints/버전/의존성 관리의 SSOT를 `pyproject.toml`로 고정한다.

---

## 1) 패키징 설계 (PyPI)

### 1.1 배포명/임포트명
- 배포명(dist): `sari` (PyPI)
- 파이썬 import: `sari` (호환용 `deckard` 유지)
- 콘솔 스크립트: `sari=deckard.main:main` (shim)

### 1.2 pyproject.toml (필수)
- 빌드 백엔드: `setuptools` 또는 `hatchling` (둘 중 하나로 고정)
- `project.scripts`에 `sari` 등록
- 버전 소스: `sari/version.py` 또는 SCM tag 연동(택1)

### 1.3 최소 요구 사항
- pip 설치 후 `sari` 명령이 즉시 동작해야 함
- `python -m sari`도 동작해야 함 (콘솔 스크립트 장애 대비)

---

## 2) 테스트 전략 (계약 테스트 우선)

**핵심 원칙**: 기능 테스트보다 계약(contract) 테스트를 먼저 고정한다.

### 2.1 Search 계약
- 요청 필드/응답 필드 스키마 고정
- `total_mode` 처리 규칙
- `root_ids` 범위 정책
- PACK1/JSON 결과 일관성

### 2.2 Status 계약
- `http_api_port`(configured/bound)
- `engine_*` 메타 필드 노출
- indexer 상태 필드 고정

### 2.3 Config Migration 계약
- SSOT 경로 우선
- legacy 1회 이전(복사 + backup/migrated marker)
- 재실행 시 재이전/덮어쓰기 금지

### 2.4 include_ext / max_file_bytes 의미론
- `include_ext` empty = no filter
- `include_files`는 allow-list로서 exclude 규칙보다 우선
- `return None` = 진짜 제외
- `parse_status=skipped` = meta row 유지
- `max_file_bytes=0` = 제한 없음

---

## 3) TODO
- [x] `pyproject.toml` 템플릿 작성
- [x] 계약 테스트 목록을 구체 테스트 케이스로 분해
- [ ] CI에서 계약 테스트를 최소 보장 스위트로 분리
- [ ] 배포 전 `twine check` 고정 단계 추가
