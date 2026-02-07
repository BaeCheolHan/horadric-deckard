# 02 Knowledge & Debt

지식 누적 루프: 운용할수록 재설명/재탐색/재실수를 줄여 총 비용을 낮춘다.
정본: `00-core.md`

---

## 목표
- 문서는 **초압축 + 예산 기반 + 절차 강제**
- docs 업데이트는 **code change 스케일(S0~S3) 산정에서 제외**
- **언어 원칙**: 모든 문서는 **한국어**로 작성 (단, 코드 식별자/경로는 영문 유지)

---

## 저장 위치

### 공유 (커밋 대상)
| 종류 | 경로 |
|------|------|
| 교훈 | `docs/_shared/lessons-learned/lessons-learned.md` |
| 통합 ERD | `docs/_shared/erd/erd.md` |
| 용어집 | `docs/_shared/glossary/glossary.md` |

### 로컬 (비커밋)
| 종류 | 경로 |
|------|------|
| 현재 상태 | `docs/_shared/state/current-state.md` |
| 상태 상세 | `docs/_shared/state/current-state.d/<repo>.md` |
| 부채 | `docs/_shared/state/debt.md` |
| 로그 | `docs/_shared/state/state-log.md` |

### 스킬 (로컬)
- `.codex/skills/<skill-name>/SKILL.md`

---

## Preflight/Postflight 예산

| 스케일 | Preflight 읽기 | Postflight 쓰기 |
|--------|----------------|-----------------|
| S0 | state ≤6줄만 | 경로 목록 + state ≤6줄 |
| S1+ | lessons ≤10줄, debt ≤20줄, state ≤12줄 | lessons/debt/state 전부 |

### Preflight 선택 알고리즘
1. 요청에서 태그/키워드 후보 추출
2. lessons: 태그 매칭 우선 ≤10줄
3. debt: 태그 매칭 우선 ≤20줄

### State ↔ Repo 연결
- Active scope 확정 시 `current-state.md`에 `current-state.d/<repo>.md` 링크 1줄 포함
- 링크 누락 시 다음 턴 첫 액션으로 보완

---

## Write Rules

CAUTION:
아래 규칙 위반 시 문서 작성 **무효 처리**

### 델타 정책 (토큰 절감)
- [MUST] **델타 기록 우선**: 기존 문서 재요약 금지. 신규 발견/변경점만 추가.
- [MUST] **중복 방지**: 동일 내용은 링크/키워드 참조로 대체. 본문 재서술 금지.
- [MUST] **근거 최소화**: 근거 파일은 리스트만 기재. 본문 인용/재서술 금지.

### 참조 형식
- 경로 링크: `→ docs/api/xxx.md`
- 인덱스 참조: `[lessons:L042]`, `[debt:L015]`

### 기본 규칙
- 파일 폭증 금지: state는 overwrite 기본
- 업데이트는 '사실/결정/다음 액션'만 (장문 금지)
- 문서 1개당 ≤120줄

### 신규 기록 포맷 (3블록)
```
**신규 발견**: [1~3줄]
**영향**: [1~2줄]
**다음 액션**: [1줄]
```
→ 1개 항목당 총 6줄 이내

### 상한

| 문서 | 상한 |
|------|------|
| lessons | 항목당 1~2줄, 총 ≤6줄 추가 |
| debt | 항목당 1~2줄, 총 ≤10줄 |
| state (index) | ≤6줄 (S1+는 ≤8줄) |
| state (repo) | 상단 12줄 요약 유지 |
| plan 파일 | ≤200줄 (초과 시 요약 20줄로 압축) |


---

## 태그 (표준)

한 엔트리에 **2~4개 태그**만 사용. 형식: `[tag]`

### Core Process
`process`, `scope`, `tools`, `ux`, `review`, `docs`

### Engineering
`arch`, `msa`, `design`, `api`, `dto`, `test`, `build`, `deploy`

### Contracts
`contract`, `compat`, `rollback`

### Data/DB
`db`, `sql`, `mysql`, `index`, `tx`, `migration`

### Runtime
`perf`, `concurrency`, `memory`, `io`, `network`

### Security
`auth`, `jwt`, `secrets`, `vuln`

### Java/Spring
`java`, `spring`, `jpa`, `mybatis`, `querydsl`

### Ops
`ops`, `logging`, `monitoring`, `incident`, `hotfix`

**태그 추가 규칙**: 표준 외 필요 시 Plan에서 이유 1줄 + 이 파일에 1줄 추가

---

## Skills 정책

- 스킬은 **절차 재사용 문서 패키지**
- 제안은 가능, 생성/설치/사용은 **사용자 승인** 필요
- 템플릿: `.codex/skills/_templates/SKILL_TEMPLATE.md`

### Repo-map 스킬 (권장)
- 길이: 30~60줄
- 필드: Repo scope, Key paths, Test commands, Dependencies
- 금지: 전체 트리/장문
- 갱신: 구조/빌드/모듈 변경 시만