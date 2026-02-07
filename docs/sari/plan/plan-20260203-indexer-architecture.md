# [09] 인덱서 구조 개선 설계 v1

[scope][indexer][architecture]
**목표**: 인덱서의 확장성/안정성을 높이고, 언어별 파서 추가와 기능 확장을 구조적으로 용이하게 만든다.

---

## 1) 문제 인식

### 현재 한계
- 단일 구현체/단일 파이프라인 구조로 확장 시 결합이 큼
- 파싱 실패가 전체 파이프라인의 신뢰성에 영향
- 언어별/기능별 정책이 코드 곳곳에 분산

### 요구 사항
- 파서 확장 (언어별, heuristic별)
- 파이프라인 단계 분리 (수집/파싱/AST/저장)
- 정책 객체화 (filter/size/profile/root boundary)

---

## 2) 목표 구조

### 2.1 Pipeline 단계 분리
1. **Collector**: 파일 목록 수집 및 파일 메타 확보
2. **Loader**: 파일 읽기/디코딩(content 생성)
3. **Parser**: 언어별 파싱 및 AST/심볼 추출
4. **Validator**: 스키마/규격 검증
5. **Sink**: 결과 저장(DB/엔진 인덱스)

### 2.2 핵심 인터페이스(초안)
**Collector**
```
collect(ctx, policy) -> Iterable[FileItem]
```

**Loader**
```
load(file_item, ctx, policy) -> LoadedFile
```

**Parser**
```
id: str
category: "language" | "heuristic"
priority: int  # 높을수록 우선

can_handle(file_item, ctx, policy) -> bool
parse(loaded_file, ctx, policy) -> ParseResult
```

**Validator**
```
validate(parse_result, ctx, policy) -> ValidationResult
```

**Orchestrator**
```
run(ctx, policy, registry) -> None
```

**Sink**
```
begin_batch(ctx) -> None
upsert(records, ctx) -> None
delete(doc_ids, ctx) -> None
end_batch(ctx) -> None
```

**Orchestrator 책임**
- Collector 호출 및 root_id_map 구성
- Policy 적용 결과에 따라 제외/스킵 최종 결정
- Loader/Parser/Validator/Sink 호출 순서 제어
- ValidationResult 실패 시 parse_status=failed 전환


### 2.3 데이터 구조(초안)
**FileItem**
- `root`: str
- `root_id`: str
- `path`: str (absolute)
- `rel_path`: str
- `repo`: str (rel_path 첫 세그먼트, 없으면 __root__)
- `size`: int
- `mtime`: int
- `ext`: str
- `is_excluded`: bool (policy 적용 결과)

**LoadedFile**
- `file_item`: FileItem
- `content`: str (best-effort, empty 가능)
- `decode_policy`: str (policy.decode_policy 사용)
- `is_binary`: bool
- `sampled`: bool

**Context**
- `workspace_roots`: list[str]
- `follow_symlinks`: bool
- `logger`: Any
- `clock`: Any
- `root_id_map`: dict[str, str]  # root path -> root_id (WorkspaceManager.root_id 규칙)

**Registry**
- `collector`: Collector
- `loader`: Loader
- `parsers`: list[Parser]
- `validator`: Validator
- `sinks`: list[Sink]

**ParseResult**
- `doc_id`: str (`root_id/rel_path`)
- `root_id`: str
- `rel_path`: str
- `repo`: str (rel_path 첫 세그먼트, 없으면 __root__)
- `path_text`: str
- `body_text`: str (parse_ok인 경우만)
- `preview`: str (snippet용)
- `mtime`: int
- `size`: int
- `sampled`: bool
- `content_bytes`: int
- `parse_status`: ok|skipped|failed
- `parse_reason`: too_large|binary|minified|excluded|error|none
- `ast_status`: ok|skipped|failed
- `ast_reason`: no_parse|too_large|excluded|error|none
- `symbols`: list
- `relations`: list
- `metadata`: dict
- `errors`: list[str]

**ValidationResult**
- `ok`: bool
- `errors`: list[str]
- `warnings`: list[str]
 
### 2.4 의미론 고정
- `return None`은 **진짜 제외**(인덱스에 없음)
- `parse_status=skipped`는 **메타 row 유지**
- `parse_reason=excluded`는 **soft exclude(메타 유지 정책)**에서만 사용, 기본은 hard exclude
- `max_file_bytes=0`은 **무제한**
- `include_ext empty = no filter`
 - `doc_id = f\"{root_id}/{rel_path}\"` 형식 고정

### 2.5 스키마 상세(구현 레벨)
**Parser 입력 스키마**
- `loaded_file`: LoadedFile (필수)
- `policy`: Policy (필수)
- `ctx`: Context (필수, 루트/환경/로그 포함)

**ParseResult 스키마(필수/옵션)**
- 필수:
  - `doc_id`: str
  - `repo`: str (rel_path 첫 세그먼트, 없으면 __root__)
  - `root_id`: str
  - `rel_path`: str
  - `path_text`: str
  - `preview`: str
  - `parse_status`: enum
  - `parse_reason`: enum
  - `ast_status`: enum
  - `ast_reason`: enum
  - `mtime`: int
  - `size`: int
- 옵션:
  - `body_text`: str (parse_ok만, 미존재 가능)
  - `symbols`: list (없으면 빈 배열)
  - `relations`: list (없으면 빈 배열)
  - `metadata`: dict (없으면 빈 dict)
  - `errors`: list[str] (없으면 빈 배열)
  - `sampled`: bool
  - `content_bytes`: int

**ValidationResult 스키마**
- `ok`: bool
- `errors`: list[str]
- `warnings`: list[str]

---

## 3) 정책 객체 (Policy)

### Policy 역할
- include_ext/include_files
- exclude_dirs/exclude_globs
- max_file_bytes
- size profile (parse/ast)
- root boundary

Policy는 파이프라인 단계에 주입 가능해야 함.

### 3.1 우선순위 규칙
1. `include_files`(절대/상대 지정) 우선
2. `include_ext` (비어있으면 필터 미적용)
3. `exclude_dirs` / `exclude_globs`
4. `max_file_bytes`는 **parse/ast 제어**, meta는 유지

### 3.2 size profile 적용
- `DECKARD_MAX_*` explicit override가 최우선
- 그 외 `DECKARD_SIZE_PROFILE` 프리셋 사용

### 3.3 Policy 스키마(초안)
- `include_ext: list[str]` (기본: [])
- `include_files: list[str]` (기본: [])
- `exclude_dirs: list[str]` (기본: [])
- `exclude_globs: list[str]` (기본: [])
- `max_file_bytes: int` (기본: 0 = 무제한)
- `parse_limit_bytes: int` (size profile 적용)
- `ast_limit_bytes: int` (size profile 적용)
- `allow_metadata_only_ok: bool` (기본: false)
- `decode_policy: str` (기본: "strong")
- size profile 적용 규칙: `DECKARD_MAX_*` explicit override > `DECKARD_SIZE_PROFILE`
 - soft exclude 규칙: `allow_metadata_only_ok=true`일 때만 excluded 파일의 meta row 유지

---

## 3.4 Validator 규칙(최소 스키마)

**필수 필드 검증**
- `doc_id`, `root_id`, `rel_path`, `repo`, `path_text`, `parse_status`, `parse_reason`, `ast_status`, `ast_reason`, `mtime`, `size` 누락 시 오류

**형식 검증**
- `doc_id`는 `root_id/rel_path` 형식
- `mtime`/`size`는 0 이상의 정수
- `parse_status`는 {ok, skipped, failed} 중 하나
- `parse_reason`는 {none, too_large, binary, minified, excluded, error} 중 하나
- `ast_status`는 {ok, skipped, failed} 중 하나
- `ast_reason`는 {none, no_parse, too_large, excluded, error} 중 하나
- `repo`는 rel_path 첫 세그먼트, 없으면 `__root__`

**내용 검증**
- `parse_status=ok` 인 경우 `body_text` 또는 `symbols` 중 하나는 존재
- metadata-only ok 허용은 **기본 false**, `Policy.allow_metadata_only_ok=true`일 때만 허용
- `parse_status=skipped/failed` 인 경우 `body_text`는 비어야 함
- `preview`는 최대 길이 정책(`DECKARD_ENGINE_PREVIEW_BYTES`) 준수
- `parse_reason=none`은 **정상(ok)** 상태에서만 허용

**오류 처리**
- Validation 실패 시 **Validator는 parse_status를 변경하지 않고** ValidationResult로만 반환
- Pipeline Orchestrator가 ValidationResult.ok=false를 감지해 `parse_status=failed`로 **최종 전환**
- 실패 이유는 `errors[]`에 누적 기록

---

## 4) 확장 전략

- 언어별 Parser 모듈을 독립적으로 추가
- 새로운 저장소 타입(Sink) 도입 가능
- 평가/검증 단계(Validator)에서 schema/metadata 규정 강화

### 4.1 파서 선택 규칙
1. `language` 카테고리 우선
2. `priority` 높은 순
3. `can_handle`이 true인 최초 파서를 선택
4. 실패 시 `heuristic` 카테고리로 폴백 가능
5. priority 동률 시 등록 순서 우선

### 4.2 폴백 정책(명시)

### 4.2.1 Parser 규칙(추가)
- `is_binary=true`인 경우 parse_status=skipped, parse_reason=binary
- content empty & not binary → parse_status=skipped, parse_reason=no_parse (meta only)
- Loader 실패는 Orchestrator가 parse_status=failed, parse_reason=error로 전환
- `is_excluded=true`는 Orchestrator가 hard exclude 처리하며 Parser에는 전달하지 않음 (soft exclude는 allow_metadata_only_ok일 때만)
- 파서 실패 시:
  1) 동일 카테고리 내 다음 priority 파서로 재시도
  2) 실패 누적 시 heuristic 카테고리로 전환
  3) heuristic 실패 시 parse_status=failed 로 기록(메타 유지)

---

## 4.3 Collector/Sink 인터페이스 상세

### Collector (예시)
```
collect(ctx, policy) -> Iterable[FileItem]
```
- `ctx`: workspace_roots, logger, follow_symlinks, clock
- `policy`: include/exclude/size profile

**Collector 책임**
- 경로 수집 및 root boundary 적용 (roots 밖은 FileItem 생성 안 함)
- `FileItem` 생성 (rel_path/repo/size/mtime)
- include/exclude 정책 1차 적용 (`is_excluded` 표시, 실제 제외 결정은 Policy 단계에서 확정)
- Policy 적용 시점: Collector 이후, Loader/Parser 이전
- 제외/스킵 최종 결정은 Pipeline Orchestrator가 수행
- root_id 생성 및 FileItem 주입 (WorkspaceManager.root_id 규칙과 동일, follow_symlinks 반영)
  - doc_id = f"{root_id}/{rel_path}"

### Sink (예시)
```
begin_batch(ctx) -> None
upsert(records, ctx) -> None
delete(doc_ids, ctx) -> None
end_batch(ctx) -> None
```

**Sink 구현 타입**
- `SqliteSink`: files/symbols/relations 업데이트
- `EngineSink`: embedded index upsert/delete

**Sink 규칙**
- `parse_status=skipped`는 meta row는 기록, body_text는 비움
- `parse_status=failed`는 meta row만 기록 (errors 포함)
- delete는 doc_id 기준 단일 규칙
- delete는 meta/symbols/relations/engine index 모두 제거(단일 delete 계약)

---

## 5) 마이그레이션 전략

### 단계적 적용
1. 기존 Indexer의 내부 로직을 Parser 인터페이스로 래핑
2. Pipeline 분리 (Collector/Parser/Sink)
3. Validator 추가
4. Sink 분리(embd/sqlite 동시 대응)

### 5.1 롤백 전략
- 단계별 플래그로 전환
- 문제 발생 시 기존 단일 파이프라인으로 즉시 복귀

---

## 6) 리스크
- 초기 리팩토링 비용
- 기존 인덱서 성능 회귀 가능성
- 파서 호환성 문제
- 파서 실패가 누적될 경우 성능 저하 가능

---

## 7) TODO
- [x] Parser 인터페이스 정의 확정(필드/우선순위/카테고리)
- [x] ParseResult/ValidationResult 스키마 확정
- [x] Collector/Sink 인터페이스 구체화 + 샘플 구현
- [x] Validator 규칙 목록화 + 최소 스키마
- [x] 파서 선택 규칙/폴백 정책 테스트 정의
- [ ] Pipeline Orchestrator 계약 테스트 연결

---

## 8) 테스트 케이스(파서 선택/폴백)

### 8.1 선택 규칙
- T1: `language` + `heuristic` 동시에 가능 → language 우선
- T2: 동일 카테고리 2개 (priority 10 vs 5) → 10 우선
- T3: `can_handle=false`면 우선순위 무시 → 다음 파서 선택

### 8.2 폴백 규칙
- T4: language 파서 실패 → 동일 카테고리 다음 파서로 전환
- T5: language 전체 실패 → heuristic 파서로 전환
- T6: heuristic 실패 → parse_status=failed, meta 유지

### 8.3 의미론 보장
- T7: `include_ext=[]` → 필터 미적용(모든 파일 처리)
- T8: `max_file_bytes=0` → 무제한 처리
- T9: parse_status=skipped → meta row 유지 확인
