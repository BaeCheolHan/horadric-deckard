# PROJECT_OVERVIEW (v2.3.3)

이 문서는 현재까지 확인한 codex-forge 구조/동작/도구 사용 관찰을 요약한다.

---

## 1. 레포 성격

- 실행 애플리케이션이 아니라 설치/제거 스크립트 + 문서 중심 레포
- 주요 엔트리:
  - install.sh: 설치/업데이트/구성 병합 로직
  - uninstall.sh: 제거 및 정리 로직
  - README.md: 빠른 시작 요약
  - docs/_meta/SETUP.md: 설치/진단/업데이트 정본

---

## 2. 확인된 파일 구조 (레포 내부)

- 루트
  - install.sh
  - uninstall.sh
  - README.md
  - docs/
- docs/_meta
  - SETUP.md, CHANGELOG.md, RELEASE_CHECKLIST.md, SELF_REVIEW.md, VERSIONING.md
- docs/_shared
  - glossary, lessons-learned, inbox, erd, local-search, skills, state

---

## 3. local-search MCP 관찰

- 상태:
  - index_ready: true
  - workspace_root: /mnt/d/repositories
  - server_version: 2.3.3
- 레포 내부에는 .codex/rules 디렉토리가 없음
  - rules 관련 내용은 install.sh 및 문서 내 문자열로만 존재

---

## 4. 작업 흐름 관찰 (local-search 관점)

- 실제 규칙 파일(.codex/rules)은 설치 후 workspace에 생성됨
- 설치 전에는 rules 내용 검증/문서화가 불가

---

## 5. 문서화/운영 개선 포인트 (관찰 기반)

- local-search가 "인덱싱된 파일 목록"을 직접 제공하는 API가 없음
  - 디버깅 시 파일 스캔 대상을 확인하기 어려움
- repo 지정(repo=codex-forge vs repo=__root__) 설명이 문서에 명시되면 혼란 감소
- 숨김 디렉토리(.codex) 스캔 포함 여부를 명확히 안내하는 FAQ가 유용

