# 01 Checklists - Gemini 강화판

환각 억제 및 지식 표류 방지를 위한 통합 체크리스트.
정본: `00-core.md`
**Gemini 강화**: 모든 체크 항목 준수 강제

CAUTION:
**체크리스트 미통과 시 작업 즉시 중단**. 각 항목은 선택이 아닌 **필수**입니다.

**라벨**: [MUST] 항상, [IF] 해당 시, [OPT] 선택

---

## A. Preflight (Change/Run 전)

WARNING:
Preflight 체크 누락 시 작업 시작 금지

- [ ] [MUST] **Intent 고정**: 목표/제약/금지를 1~2줄로 재진술
- [ ] [MUST] **진행 의도 확인**: 변경 의사 + 타겟 repo 지정 (`03-gate.md` 3단계 게이트 참조)
- [ ] [MUST] **최종 승인**: 스케일 고지 + 사용자 "approve execute" (또는 명시적 승인) 확인
- [ ] [MUST] **Deckard 우선**: 파일 탐색 전 deckard 먼저 (토큰 절감)
- [ ] [IF] **위험 행동 재확인**: 파괴/외부/대규모면 1회 재확인 완료
- [ ] [IF] **Knowledge 확인**:
  - S0: `current-state.md` ≤6줄만 (lessons/debt 자동 읽기 금지)
  - S1+: lessons ≤10줄, debt ≤20줄, state ≤12줄
  - **S1+ 설계 시**: deckard로 관련 API/ERD/glossary 검색 (버그 방지)

**Preflight 체크 예시**:
```
✓ Intent: PaymentService null 체크 추가, 3 files 이내
✓ 진행 의도: "approve execute" 확인
✓ 최종 승인: S0 (3 files) 승인됨
✓ Deckard: deckard "PaymentService" → 3개 파일
✓ Knowledge: current-state 6줄 읽음
```

---

## B. 수행 중 (Change/Run)

- [ ] [MUST] **Scope 고정**: 스케일 예산 내 (S0: ≤3 files, ≤300 LOC)
- [ ] [IF] **Security Baseline**: 입력 검증/권한/시크릿/로그/인젝션 체크 (N/A면 이유 기재)
- [ ] [IF] **Design Review**: 동작/계약/성능 변경 시 선행 완료

---

## C. Postflight (완료 주장 전)

CAUTION:
**증거 없는 완료 선언 = 작업 무효**

### C.1. 증거 (필수)

- [ ] [MUST] **Evidence**: (a) 경로+diff 요약, (b) 명령+출력 요약, (c) 테스트+assert 중 1개 이상
- [ ] [MUST] **Testing**: 동작 변경이면 테스트 증거 또는 대체 검증 (재현 3단계/스모크/로그)

**증거 예시**:
```
✓ Evidence:
  - 경로: PaymentService.java
  - diff: +3줄 (null 체크 추가)
✓ Testing: 수동 테스트 - payment null 입력 시 예외 발생 확인
```

### C.2. 리뷰 (필수)

- [ ] [MUST] **Self-Review x2**: 1차 정확성/스코프, 2차 단순화/엣지/보안

### C.3. 문서 업데이트

CAUTION:
**S1+ 규모에서 문서 미작성 시 작업 미완료 처리**
모든 문서는 **한국어**로 작성합니다 (코드 식별자 제외).

**변경 유형 선언** [MUST]: Code / API / Data / Enum-Status / Process

| 스케일 | 필수 업데이트 |
|--------|---------------|
| S0 (코드 변경 있음) | 경로 목록 + `current-state` ≤6줄 |
| S0 (코드 변경 없음) | N/A (단, Knowledge Capture 트리거 시 문서 저장) |
| S1+ | lessons/debt/state 전부 업데이트 **[MUST-BLOCK]** |

- [ ] [MUST] **델타 정책 준수**: 재요약/재서술 없음, 3블록 포맷 사용

**문서 작성 예시**:
```
✓ 변경 유형: Code
✓ current-state 업데이트:
  **신규 발견**: PaymentService null 체크 누락
  **영향**: 결제 실패 방지
  **다음 액션**: 테스트 케이스 추가
```

**유형별 최소 업데이트**:
- Code: `current-state.md` 갱신
- API: API 분석 문서 + 용어 영향 1줄
- Data: ERD 갱신 + 영향 API 1줄
- Enum-Status: 정의 + 계약/API 영향 1줄

**Canonical Paths**:
- API: `docs/<repo>/api/METHOD__path.md`
- ERD: `docs/<repo>/erd/<api-name>.md`
- 통합 ERD: `docs/_shared/erd/erd.md`
- 용어: `docs/_shared/glossary/glossary.md`
- 교훈: `docs/_shared/lessons-learned/*`

### C.4. 최종 점검

- [ ] 요구사항 누락 없음
- [ ] 범위(Repo/파일/LOC) 명확
- [ ] 가정 vs 사실 분리 (확인 불가 라벨)
- [ ] 리스크/롤백 존재
- [ ] 검증 정량화
- [ ] 불필요한 변경 제거

---

## D. Verification (S2+ 필수)

S2 이상이면 아래 중 최소 1개:
- 실행 가능한 테스트 커맨드 1개
- 재현 스텝 3단계 + 기대 결과 1개
- 영향 범위 스모크 체크 5항목

---

## E. 스킬 변경 시

- [ ] 사용자 진행 의도 또는 승인 확인
- [ ] `.codex/skills/_templates/SKILL_TEMPLATE.md` 준수
- [ ] Validation ≤5 bullets (재현 가능한 증거)
- [ ] approval/budget/evidence/checklist 우회 없음 명시
- [ ] 증거: 경로 + diff 요약 + 사용 예시 1개

---

## Failure Policy

CAUTION:
실패 시 **즉시 중단**, 추측 진행 금지

- 모호/불확실/도구 실패: **"확인 불가"** 명시 + 필요 증거/다음 액션 제시
- 체크리스트 미통과: **진행 중단 → Plan 회귀 → 선택지 2~3개 제시**