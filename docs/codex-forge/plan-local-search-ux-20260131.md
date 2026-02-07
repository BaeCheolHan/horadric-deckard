# local-search UX 개선 설계 (2026-01-31)

## 배경
- `search`는 숨김 디렉토리(.codex 등)를 기본 제외하여 규칙 파일 탐색 실패가 빈번함.
- `query`에 `|` 등 정규식 패턴을 넣으면 리터럴로 처리되어 0건이 되어 혼란 발생 (`use_regex=true` 필요).
- `list_files` 출력이 길어 실제 사용 시 limit/offset 사용 가이드가 필요.

## 목표
- 숨김 디렉토리 인덱싱/검색 동작을 사용자가 예측 가능하게 만든다.
- 정규식 사용 여부에 대한 혼란을 줄이고, 0건 상황에서 다음 행동을 안내한다.
- `list_files`의 페이지네이션 UX를 일관되게 제공한다.

## 비목표
- 기본 인덱싱 정책(.codex 제외)의 변경은 하지 않는다.
- 인덱서 성능 최적화/대규모 리팩토링은 범위에서 제외한다.

## 변경 범위 (예상)
- `.codex/tools/local-search/app/*` (MCP 응답/메타 필드 보강)
- `.codex/tools/local-search/scripts/query.py` (CLI 출력/가이드)
- 문서: `.codex/tools/local-search/README.md`, `docs/_shared/local-search/README.md`

> 툴 코드 변경 포함 → 스케일 **S2 이상** 예상, Design Review 필요.

## 설계안

### 1) `search`에 `include_hidden` 옵션 추가 (필터 레벨)
- **의미**: “현재 인덱스에 들어와 있는 숨김 파일”의 포함 여부만 제어.
- **제약**: 인덱서가 `.codex`를 제외하고 있으면, `include_hidden=true`여도 결과는 0.
- **UX**: 0건일 때 “인덱서 제외 설정”을 원인 후보로 안내.

#### API (MCP search)
- 입력 추가: `include_hidden?: boolean` (default: false)
- 응답 메타 추가: `hidden_filter: { enabled: boolean }`

#### 0건 힌트 예시
- “숨김 디렉토리는 기본 제외입니다. 숨김을 포함하려면 `include_hidden=true` (인덱스에 포함된 경우에만 유효) 또는 config의 `exclude_dirs` 확인 후 재인덱싱하세요.”

### 2) 정규식 혼란 완화
- **규칙 감지**: `use_regex=false`인데 query에 정규식 메타문자(`|`, `.*`, `?`, `+`, `[]`, `()`, `{}` 등)가 포함되면 경고.
- **동작 변경 없음**: 자동으로 regex 모드로 전환하지 않고, 힌트만 제공.

#### 응답 힌트
- `warnings[]`에 “정규식 패턴으로 보입니다. 정규식 사용 시 `use_regex=true`를 지정하세요.” 추가.

### 3) `list_files` 페이지네이션 UX 일관화
- `list_files` 응답에 `has_more`, `next_offset` 필드 추가 (search와 동일 패턴).
- 기본 `limit` 값 문서에 명시(예: 50). CLI에서 100개 초과 시 자동 경고 표시.

#### API (MCP list_files)
- 응답 메타 추가: `has_more: boolean`, `next_offset?: number`

## 사용자 가이드 개선
- quick-start 및 README에 아래를 추가:
  - 숨김 디렉토리 탐색 흐름: `status` → config의 `exclude_dirs` 확인 → 재인덱싱 → `search include_hidden=true`
  - 정규식 사용 예시와 `use_regex=true` 필수 안내
  - `list_files` 권장 사용: `limit/offset` 예시

## 테스트 시나리오
1) `use_regex=false` + query에 `|` 포함 → warning 표시 확인.
2) `include_hidden=false/true`로 동일 query 실행 → hidden 필터 메타 차이 확인.
3) `list_files`에 limit/offset 적용 → `has_more/next_offset` 정확성 확인.
4) 0건 상황에서 힌트 메시지 노출 확인.

## 롤백 전략
- MCP 응답 메타/힌트는 하위 호환이므로, 필요 시 필드 제거로 롤백 가능.

## 오픈 이슈
- 숨김 디렉토리 인덱싱을 사용자가 쉽게 켜/끄는 UX 제공 여부 (재인덱싱 비용 포함).
- `include_hidden` 기본값과 도구 일관성 (search vs list_files).
