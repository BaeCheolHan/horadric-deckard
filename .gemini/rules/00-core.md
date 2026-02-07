# 00 Core (정본) - Gemini 강화판

모든 규칙의 단일 소스. 다른 파일은 이 문서를 참조만 한다.
**Gemini 강화**: 규칙 준수 강제를 위한 경고 강화 버전

CAUTION:
**규칙 위반 시 작업 즉시 중단**. 아래 정책은 제안이 아닌 **필수 요구사항**입니다.

## 목표
- 자연어 요청 처리, 실행은 **진행 의도/예산/증거/체크리스트**로 통제
- [MUST] 최우선 **코드 품질/버그 최소화(P1)**, 그 다음 비용(토큰/탐색/변경량)
- [MUST] 문서 **기본 ON**(S0는 lightweight): 교훈/부채/상태를 초압축으로 누적

## 우선순위 (P0→P4)

| 순위 | 내용 |
|------|------|
| P0 | 안전/보안/데이터 파괴 방지 |
| P1 | 정확성/무결성/버그 최소화 |
| P2 | 문서화/지식 누적 |
| P3 | 속도/편의 |
| P4 | 범위/통제/비용(토큰/변경량) |

## 용어
- **Workspace root**: `.codex-root`가 있는 디렉토리
- **Repo**: workspace 1depth 하위 폴더
- **Active scope**: 이번 작업에서 읽거나/수정하는 repo 집합
- **Code files**: 소스/설정/테스트 등 제품 코드
- **Doc files**: `docs/**`, `.codex/**` (별도 예산)

## 스케일 및 게이트 (S0→S3)

WARNING:
하드캡(30 files / 3000 LOC) 초과 시 **작업 거부**

| 스케일 | 파일 수 | LOC | 스펙 | 롤백 | 재확인 | 문서 |
|--------|---------|-----|------|------|--------|------|
| S0 | ≤3 | ≤300 | - | - | - | 경로만 |
| S1 | 4-10 | ≤1000 | Mini Spec | - | - | 필수 |
| S2 | 11-20 | ≤2000 | Mini Spec | 필수 | - | 필수 |
| S3 | 21-30 | ≤3000 | Mini Spec | 필수 | 필수 | 필수 |

**하드캡**: ≤30 code files AND ≤3000 LOC. 초과 금지.

### 스케일 판정 규칙

**1. 파일 수 vs LOC (둘 중 높은 스케일 적용)**
- 파일 ≤3이지만 LOC 2000 → **S2** (LOC 기준)
- 파일 15개지만 LOC 200 → **S2** (파일 수 기준)

**2. 변경 타입별 최소 스케일**

| 변경 타입 | 최소 스케일 | 비고 |
|-----------|-------------|------|
| 비즈니스 코드 | 테이블 기준 | 파일/LOC로 판정 |
| 문서만 (`docs/**`) | 스케일 제외 | 별도 예산 |
| 룰 파일 (`.codex/rules/*`) | S1+ | 전파 영향 큼 |
| 툴 코드 (`.codex/tools/**`) | S2+ | 인프라 영향 |
| 보안/네트워크/인덱스 | S3 | 고위험 |
| 설정 파일 (`.codex/*`) | S1+ | 동작 변경 가능 |

**3. 롤백 정의**
- **S2 롤백**: `git revert` 가능한 단위 커밋 + 검증 방법 1개
- **S3 롤백**: 위 + 설정/데이터 원복 절차 명시 (백업 위치, 복구 명령)

## 예산

| 작업 | 기본 | 확장 |
|------|------|------|
| Read | ≤10 files / ≤1200 lines | ≤30 files / ≤3000 lines |
| Change | ≤3 files / ≤300 LOC | 단계 게이트 적용 |

## MSA 타겟팅 (P0)

CAUTION:
repo/service 미지정 시 **Change/Read Expand 금지**

- [MUST] 후보 2~3개 제시 → 사용자 선택 → Active scope 고정
- **후보 제시 순서**: (1) deckard `/repo-candidates` (2) 1depth+README

## Deckard 우선 원칙 (P2: 토큰 절감)

CAUTION:
**deckard 미사용 시 작업 즉시 중단**. Glob/grep **사용 전 반드시** deckard 시도 증명 필요.

WARNING:
**회피 금지**: "파일이 어디 있는지 모르겠다", "찾을 수 없다" 등의 응답 **금지**.
**반드시** deckard로 검색 시도 후 결과 보고.

**목적**: 불필요한 파일 탐색을 방지하여 토큰 30-50% 절감

### [MUST] 작업 시작 전 체크

모든 파일 탐색 작업은 아래 순서 **필수**:

1. **1단계**: deckard로 검색 시도
2. **2단계**: 결과 확인 및 보고
3. **3단계**: 결과 0건일 때 **키워드 최적화(Refinement)** 후 재시도 (예: "PaymentService" -> "payment service")
4. **4단계**: 재시도 후에도 0건일 때만 대안(glob/grep) 허용

**위반 예시 (금지)**:
```
❌ AI: "PaymentService 파일을 찾을 수 없습니다"
❌ AI: "먼저 전체 구조를 확인하겠습니다" → Glob 시도
❌ AI: "grep으로 찾아보겠습니다"
```

**올바른 예시 (필수)**:
```
✅ AI: deckard "PaymentService" 실행
     → 3개 파일 발견
     → payment-service/PaymentService.java 확인
```

### MCP 도구 사용 (v2.3.0+)
deckard가 MCP 도구로 등록되어 있다면 (`/mcp`로 확인):
1. **search**: 키워드로 파일/코드 검색
2. **status**: 인덱스 상태 확인

MCP 미등록 시: `python3 .codex/tools/deckard/scripts/query.py search "keyword"`

### 필수 사용 시나리오

| 상황 | [MUST] 필수 행동 | [금지] |
|------|------------------|--------|
| 파일 위치 모름 | deckard `search` 먼저 | Glob 전체 탐색 |
| 키워드 검색 | deckard > grep | 추측 경로 접근 |
| Cross-repo 탐색 | deckard로 전체 검색 | 수동 탐색 |
| **지식 문서 조회** | deckard로 검색 (lessons/glossary/API/ERD) | 직접 경로 접근 |
| **"어디 있는지?"** | deckard 시도 → 결과 보고 | "모르겠다" 응답 |

### 예시: Before vs After

**❌ Before (토큰 낭비 - 금지)**:
```
User: "로그인 코드 찾아줘"
AI: Glob **/*auth* → 20개 파일 읽기 → 12000 토큰
```

**✅ After (토큰 절감 - 필수)**:
```
User: "로그인 코드 찾아줘"
AI: deckard "login auth" → 3개 파일 → 900 토큰 (92% 절감)
```

**✅ 추가 예시 - Cross-repo**:
```
User: "결제 관련 코드"
AI: deckard "payment" --scope all
→ payment-service/PaymentController.java
→ order-service/OrderPayment.java
→ 2개 파일만 읽기
```

**✅ 추가 예시 - 지식 문서**:
```
User: "API 인증 관련"
AI: deckard "auth API" --type docs
→ docs/_shared/api/auth-api.md 발견
→ 재탐색 방지
```

**✅ 추가 예시 - 0건 시 대안**:
```
User: "새 파일 NewService 어디 만들까?"
AI: deckard "NewService" → 0건
    deckard 결과 없으므로 유사 파일 탐색
    → grep으로 대안 검색
```

### 예외 허용 (명시 필요)

다음 경우만 대안 허용:
- [✓] deckard 결과 0건 -> **키워드 최적화 재시도** -> 최종 0건 시 Glob 허용 (로그: "deckard 최적화 후에도 0건, glob 시도")
- [✓] deckard 서버 미응답 → grep 허용 (로그: "deckard 서버 오류, grep 시도")

**예외 사용 시 반드시 로그 남기기**

## 게이트 & 워크플로우

상세 내용: `03-gate.md`

- 진행 의도 게이트 (3단계 승인)
- Phase Prompt (S1+ 개발 흐름)
- 증거 규칙
- Run 정책 (SAFE)
- Design Review 트리거

## 토큰/비용 절감

| 항목 | 상한 |
|------|------|
| 기본 응답 | 8줄 |
| 계획 | 6 bullets |
| diff | 3 hunk |
| 로그/출력 | 10줄 |

- 같은 내용 재설명 금지 (링크/키워드로만 참조)
- 문서 본문은 저장용, 컨텍스트에는 요약/경로만

## Knowledge Capture

CAUTION:
**S1+ 완료 시 문서 미작성 = 작업 미완료**

- `docs/**` 산출물은 **한국어** (코드 식별자는 영문 유지)
- [MUST] "분석/설계/API 분석" 요청 시 코드 변경 없어도 **문서 저장 필수**
- [MUST] **S1+ 완료 시 문서 미작성 = 작업 미완료로 간주**
- 채팅 출력: 요약(≤8줄) + 저장 경로 목록만

## 산출물 경로

| 종류 | 경로 |
|------|------|
| 기획/설계 | `docs/<repo>/plan/plan-<id>.md` |
| API 분석 | `docs/<repo>/api/<api-name>.md` |
| ERD | `docs/<repo>/erd/<api-name>.md` |
| 통합 ERD | `docs/_shared/erd/erd.md` |
| 용어집 | `docs/_shared/glossary/glossary.md` |
| 교훈 | `docs/_shared/lessons-learned/lessons-learned.md` |

## 환각 억제

WARNING:
완료/해결/확인은 **증거 없이 선언 금지**

- [MUST] 완료/해결/확인은 **재현 가능한 증거** 필수
- [MUST] 도구 실패/모호 결과 시: (1) 실패 명시 (2) 확보 증거만 사용 (3) 빈칸 상상 금지

## Skills
- 절차 재사용 문서 패키지
- **사용자 승인 없이 생성/설치/사용 금지**
- approval/budget/evidence/checklist 우회 불가

## 레포 청결
- 커밋 허용: `docs/_shared/lessons-learned/**`, `docs/_shared/erd/**`, `docs/_shared/glossary/**`, `docs/<repo>/api/**`, `docs/<repo>/erd/**`
- 비커밋(로컬): `docs/**/state/**`