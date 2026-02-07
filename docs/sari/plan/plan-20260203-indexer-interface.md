# [08] Indexer Interface Design v1 (Draft)
[indexer][interface][design]

[context]
목표: 인덱서/파서 구조를 인터페이스화해 언어 확장과 기능 추가를 안전하게 만들고, 기존 동작/스펙을 유지한다.

[constraints]
- 기존 동작 유지: include_ext, include_files, max_file_bytes, parse/ast status 의미는 변경하지 않는다.
- root boundary, legacy path 예외, SSOT 포트 전략/entrypoint 규칙은 그대로 유지한다.
- DB 스키마 파괴/마이그레이션 금지.

[current]
- 파서가 `app/indexer.py` 내부에 동봉되어 있고, `ParserFactory`가 확장 포인트 역할을 한다.
- 인덱서가 스캔/필터/파싱/AST/DB/엔진 동기 갱신까지 모두 수행한다.
- 언어 추가 시 `indexer.py` 수정이 필수라 확장 비용이 높다.

[problems]
- 파서/인덱서 결합도가 높아, 기능 추가 시 회귀 위험이 큼.
- 테스트 분리 어려움(파서 단위 테스트가 indexer 종속).
- 신규 언어/기능 추가가 구조적으로 느리고 위험.

[goals]
- 파서와 인덱서의 책임 분리.
- 언어별 파서를 등록/해제 가능한 registry 구조.
- 파싱 파이프라인 확장(전처리/후처리/메타 생성) 가능.
- 기존 결과 포맷/스펙 유지(동작 호환).
- Parser 선택 규칙의 결정적(deterministic) 동작 보장.
- 실패 격리: 파서 실패가 인덱싱 전체를 중단하지 않도록.

[non-goals]
- DB/엔진 교체.
- 파싱 알고리즘 전면 재작성.
- API/도구의 응답 포맷 변경.

[proposal]

## 1) Core Interfaces

### Parser
```
interface Parser:
  id: str
  supported_exts: set[str]
  priority: int
  category: language|heuristic
  can_handle(ctx: ParseContext) -> bool
  parse(ctx: ParseContext) -> ParseResult
```

### ParseContext
```
path, rel_path, root_id
content, size, mtime
config, flags
language_hint (optional)
content_hash (optional)
decode_policy (strong|ignore)
sampled (bool)
```

### ParseResult
```
symbols: list[Symbol]
relations: list[Relation]
metadata: dict
parse_status: ok|skipped|failed
parse_reason: none|binary|minified|too_large|excluded|error
ast_status: ok|skipped|failed
ast_reason: none|no_parse|too_large|excluded|error
sampled: bool
content_bytes: int
```

### ParserRegistry
```
register(parser)
get_parser_for_path(path, ctx) -> Parser
get_parsers_for_ext(ext) -> list[Parser]
fallback_parser (optional)
```

## 2) Pipeline

### Stages
- PreprocessStage: decode/normalize/sample
- ParseStage: parser.parse(ctx)
- PostprocessStage: normalize symbols, attach metadata
- EmitStage: DB/Engine sink payload 생성
 - ValidateStage: ParseResult schema validation

### Extensions
- new parser = register only
- new feature = stage 추가

## 3) Sinks

### DBSink
```
upsert(files, symbols, relations)
delete(paths)
```

### EngineSink
```
upsert(engine_docs)
delete(doc_ids)
```

## 4) Selection Rules (deterministic)
- Phase-1: ext → candidate parsers (registry)
- Phase-2: can_handle(ctx) true 우선
- priority 높은 순
- category: language > heuristic
- 동점 시 등록 순서
- 실패 시 fallback parser

## 5) Compatibility Rules (must keep)
- include_ext empty = no filter
- include_files는 최우선 allow-list (exclude 규칙보다 우선)
- return None = 진짜 제외
- parse_status=skipped라도 meta row는 남김
- max_file_bytes=0 => 제한 없음
- parse/ast status는 기존 값 집합 유지
- root_id/rel_path/doc_id 규칙 유지
 - parse_reason=excluded는 **soft exclude(메타 유지 정책)**에서만 사용 (allow_metadata_only_ok=true)

## 6) Migration Plan
1. ParserRegistry 도입 (기존 ParserFactory 래핑)
2. 기존 파서 클래스를 `app/parsers/`로 분리
3. Indexer에서 registry 호출로 치환
4. Pipeline 스텁 추가(기본 no-op)
5. Parser별 단위 테스트 추가
6. 단계별 롤백 플래그 추가(레거시 파서 강제)
7. Parser/Policy 분리(정책 객체는 파서 외부에서 주입)

[open-questions]
- 언어 자동 감지: 확장 단계에서만 추가.
- 외부 플러그인 로딩: MVP 범위 제외.
 - AST parse timeout: v1은 기본 비활성, 언어별 옵션은 추후 확장.
 - 대용량 파일 샘플링: parse_limit_bytes 기준 head/tail 샘플(각 50%) 고정.
 - Policy 객체 형태: include/exclude/limit/flags 스냅샷(immutable)로 고정.

[review][conflicts]
- 파서 분리 시 import 경로/상대 import 혼선 가능성 → `app/parsers/__init__.py`에서 공개 API 고정
- 파서 선택 기준 충돌(확장자 vs can_parse) → Registry 우선순위 규칙 고정 필요
- parse_status/ast_status 의미 혼동 위험 → 기존 enum/상태 문자열 그대로 유지
- include_ext empty 의미 변경 금지 → 필터 로직은 현재 동작 유지
- hard exclude vs meta row 유지 혼동 위험 → return None은 hard exclude로 고정
- legacy path read/search 예외 유지 필요 → 파서 레이어에서 path 변환 금지
- 파서 오류가 인덱싱 전체 실패로 전파될 위험 → Parser error isolation 필요

[decisions]
- ParserRegistry 우선순위: `priority` 높은 파서 우선, 동점이면 등록 순서
- can_handle는 경량 체크만 허용(파일 전체 재파싱 금지)
- ParseResult는 기존 DB 스키마와 1:1 매핑 유지
- Pipeline Stage는 기본 no-op로 시작, 기능 추가 시에만 활성화
- ParserRegistry는 동기적, thread-safe 필요 없음(초기 등록 고정)
- 파서 실패 시 ParseResult.error로 치환(예외 전파 금지)
- Parser는 상태 비저장(순수 함수)로 제한

[review][risks]
- 파서 분리로 인해 tests/fixtures 경로 변화 가능
- 언어 확장 시 성능 회귀 가능 → Parser별 timeout/샘플 제한 필요
- Registry 오동작 시 전체 파싱 실패 가능 → fallback parser 유지
- 파서별 can_handle 오작동 시 선택 오류 → can_handle는 경량 체크만 허용
- ParseResult 확장 필드 누락 시 DB/엔진 payload 불일치 위험

[review][mitigations]
- Registry 기본값: 기존 ParserFactory 동작을 그대로 래핑
- 파서별 unit tests 추가(핵심 언어 5개)
- 실패 시 GenericRegexParser fallback 유지
- ParseResult schema validation(필수 필드 존재) 추가
- 파서 실패율/에러 원인 telemetry
- Parser/Policy 분리로 규칙 변경 시 파서 수정 최소화

[checklist]
- [ ] ParserRegistry 인터페이스 정의
- [ ] Parser/ParseContext/ParseResult 타입 정의
- [ ] Indexer → Registry 호출로 변경
- [ ] Pipeline 스텁 추가
- [ ] 기존 파서 분리 및 등록
- [ ] fallback/telemetry/validation 추가
- [ ] Policy 객체 정의 및 주입
