# [04] 검색 엔진 분리 상세 스펙 v1 (델타)

[compat][override]
**신규 발견**: 호환성 우선 정책으로 일부 스펙을 유예(확정)
**영향**: total_mode exact→approx 강제 전환 제거, use_regex/case_sensitive 에러 전환 금지, 기본 엔진 sqlite 유지(embedded는 opt-in)
**다음 액션**: embedded 모드 제약은 엔진 내부 best-effort 처리로 고정

[api][contract][search]
**신규 발견**: SearchRequest 필드 확정( query, limit, offset, repo, root_ids, file_types, path_pattern, exclude_patterns, snippet_lines, recency_boost, use_regex, case_sensitive, total_mode )
**영향**: use_regex/case_sensitive는 엔진 미지원(호환 우선: 에러 전환 금지), total_mode는 요청 값 우선, recency_boost는 mtime 재랭킹, snippet_lines는 preview 기반 best-effort
**다음 액션**: MCP/HTTP 요청 매핑 표 정의( total_mode=요청 값 우선, 미지정은 서버 힌트 )

[api][request][mapping]
**신규 발견**: MCP/HTTP search 입력은 root_ids/total_mode를 직접 수용
**영향**: 사용자가 root 범위와 total_mode를 명시적으로 제어 가능
**다음 액션**: total_mode 미지정은 서버 힌트 적용, 지정값은 우선 적용

[api][contract][search]
**신규 발견**: SearchHit 필드 확정( doc_id, repo, path, score, snippet, mtime, size, match_count, file_type, hit_reason, context_symbol, docstring, metadata )
**영향**: snippet은 엔진 인덱스에서 생성, 기본 정렬은 score desc → mtime desc → path asc
**다음 액션**: path=doc_id=`root_id/rel_path`(“/” 구분자)로 고정

[api][compat][legacy]
**신규 발견**: legacy path(root_id 없는 db_path)는 read/search만 허용
**영향**: 과거 테스트/샘플 DB는 동작 유지, 신규 write/index는 SSOT 강제
**다음 액션**: legacy path는 root boundary 예외임을 문서화

[api][contract][errors]
**신규 발견**: 엔진 전용 에러코드 고정
**영향**: PACK1/JSON 공통 에러코드로 통일
**다음 액션**: `ERR_ENGINE_NOT_INSTALLED`, `ERR_ENGINE_INIT`, `ERR_ENGINE_QUERY`, `ERR_ENGINE_INDEX`, `ERR_ENGINE_UNAVAILABLE(ready=false)`, `ERR_ENGINE_REBUILD` 확정

[config][contract][runtime]
**신규 발견**: 엔진 모드/상한 ENV 스펙 고정
**영향**: 운영/롤백은 ENV로 제어
**다음 액션**: `DECKARD_ENGINE_MODE=embedded|sqlite`, `DECKARD_ENGINE_MEM_MB=512`, `DECKARD_ENGINE_INDEX_MEM_MB=256`, `DECKARD_ENGINE_THREADS=2`, `DECKARD_ENGINE_AUTO_INSTALL=1`

[data][id][contract]
**신규 발견**: doc_id 규칙 확정( `root_id/relative_path` ), path는 root-relative + “/” 구분자
**영향**: 검색→원문 매핑이 단일 규칙으로 고정됨
**다음 액션**: normalize 규칙(절대경로→root_id+rel) 문서화

[data][id][root]
**신규 발견**: root_id는 root path 정규화(follow_symlinks 설정 반영) 기준으로 생성
**영향**: follow_symlinks 변경 시 root_id/roots_hash 변경 → 리빌드 필요
**다음 액션**: root_id 산출 규칙을 config_hash 항목에 포함

[build][packaging][ops]
**신규 발견**: 자동 설치 패키지 이름/버전 고정 필요
**영향**: 재현 가능한 설치/업데이트 보장
**다음 액션**: 패키지명 `sari-search`로 고정, version pin은 `sari` 버전과 동일(major/minor 동일, patch 허용)

[mcp][status][contract]
**신규 발견**: status 출력에 엔진 상태 포함 필요
**영향**: 운영 진단/디버깅 가능
**다음 액션**: `engine_mode`, `engine_ready`, `engine_version`, `index_docs`, `index_size_bytes`, `last_build_ts` 필드 정의

[mcp][status][reason]
**신규 발견**: engine_ready=false 사유 템플릿 고정
**영향**: 복구 경로 명확화
**다음 액션**: reason={NOT_INSTALLED|INDEX_MISSING|CONFIG_MISMATCH|ENGINE_MISMATCH|ROLLBACK_MODE}, hint="sari --cmd engine rebuild" 또는 install 안내

[mcp][interface][ext]
**신규 발견**: MCP 도구는 인터페이스 기반(Registry + ToolContext)으로 구현
**영향**: 신규 기능 추가 시 server 수정 없이 등록만으로 확장 가능
**다음 액션**: Tool 인터페이스( name, schema, execute(ctx,args)->ToolResult ), ToolRegistry, ToolContext(db/engine/roots/config/logger/clock/fs) 정의

[api][contract][search]
**신규 발견**: SearchResponse meta 필드 확정( total, total_mode, engine, latency_ms, index_version )
**영향**: total_mode=approx면 total=-1
**다음 액션**: PACK1 meta 라인/JSON 키 매핑표 작성

[arch][design][engine]
**신규 발견**: 엔진 기본 선택=sqlite, embedded는 opt-in
**영향**: 기본 경로는 sqlite 유지, embedded는 선택적 성능 모드
**다음 액션**: wheel 빌드 파이프라인( mac/win/linux )은 opt-in 기준으로 설계

[design][tokenizer][cjk]
**신규 발견**: 토크나이저 기본=script 감지 + CJK는 lindera, Latin은 unicode61 유사
**영향**: CJK 1~2글자 쿼리 품질 확보, 토큰 폭증 억제
**다음 액션**: lindera 사전은 wheel에 포함(다운로드 금지), 누락 시 latin fallback

[search][contract][semantics]
**신규 발견**: 쿼리 기본 semantics=AND(토큰 모두), 쌍따옴표는 phrase
**영향**: 기존 SQLite 검색과 결과 차이 발생 가능(문서화 필요)
**다음 액션**: query parser 스펙/예외 케이스 표 작성

[search][filters][contract]
**신규 발견**: 필터 매핑 규칙 고정(repo, root_ids, file_types, path_pattern, exclude_patterns)
**영향**: 엔진 결과가 root boundary/filters를 직접 반영해야 함
**다음 액션**: SearchOptions → 엔진 쿼리 변환 규칙 명시(SSOT 기준)

[index][text][policy]
**신규 발견**: path_text는 모든 파일에 인덱싱(doc_id + rel_path), body_text는 parse_ok만 인덱싱
**영향**: 경로 검색은 항상 가능(사용자는 root_id 없이도 검색 가능), 본문 검색은 parse_ok에 한정
**다음 액션**: path_text 구성=doc_id + " " + rel_path, index_text 생성 규칙(정규화/최대 길이) 정의

[search][filters][contract]
**신규 발견**: 필터 매핑 확정 → repo=rel_path 첫 세그먼트(없으면 `__root__`), root_ids=root_id exact, file_types=suffix OR, path_pattern/exclude_patterns=glob(root-relative, 메타 없으면 substring)
**영향**: 엔진 쿼리는 SQLite와 동일한 필터 의미를 유지
**다음 액션**: rel_path는 `root_id/` 접두가 있으면 제거, 없으면 path 그대로 사용; absolute pattern은 root 하위면 rel_path로 변환

[search][filters][root_ids]
**신규 발견**: 요청 root_ids는 허용 roots와 교집합 적용, 미지정 시 허용 roots 전체
**영향**: root boundary 준수하면서 멀티-root 범위 선택 가능
**다음 액션**: 교집합이 비면 ERR_ROOT_OUT_OF_SCOPE 반환

[search][semantics][contract]
**신규 발견**: 쿼리 파서 확정 → 토큰 AND, phrase("...") 지원, OR/regex/wildcard 미지원
**영향**: 미지원 옵션은 best-effort(무시/평문 처리)
**다음 액션**: 문서/메시지에 best-effort 처리 명시

[index][text][policy]
**신규 발견**: index_text 정규화 규칙 확정(NFKC, lower, 연속 공백 1개)
**영향**: 검색/랭킹 결과 안정화
**다음 액션**: 정규화 유틸 정의

[index][text][policy]
**신규 발견**: index_text 최대 길이 `DECKARD_ENGINE_MAX_DOC_BYTES=4MB` (parse 상한과 별도)
**영향**: 메모리/디스크 상한 제어 가능
**다음 액션**: 초과 시 head/tail 샘플로 대체

[search][snippet][contract]
**신규 발견**: snippet은 engine stored preview로 생성(기본 8KB head/tail)
**영향**: 검색 경로에서 decompress 제거 유지
**다음 액션**: `DECKARD_ENGINE_PREVIEW_BYTES=8192` 설정 추가

[config][memory][perf]
**신규 발견**: 기본 threads=2, index_mem=256MiB (engine_mem=512MiB 상한 내)
**영향**: 인덱싱/머지 성능과 메모리 피크 균형
**다음 액션**: 상한 충돌 시 자동 clamp 규칙 정의

[cutover][process][validation]
**신규 발견**: 컷오버 절차 확정( build-temp → validate → atomic rename → restart )
**영향**: 실패 시 기존 인덱스 유지, rollback 플래그로 즉시 복귀
**다음 액션**: validate 항목/스코어링 정의

[cutover][process][validation]
**신규 발견**: 컷오버 기준 확정(Top10 overlap ≥0.7, P95 ≤200ms@50k docs, build error=0)
**영향**: 기준 미달이면 배포 차단/롤백
**다음 액션**: 벤치 데이터셋/쿼리 세트 정의(경로만 고정)

[packaging][install][ux]
**신규 발견**: auto-install venv 경로 `~/.local/share/sari/engine/.venv`
**영향**: 사용자 설정만으로 설치/실행 달성
**다음 액션**: wheel 캐시/버전 pin 규칙 구현

[rollback][ops][config]
**신규 발견**: rollback 플래그는 `DECKARD_ENGINE_MODE=sqlite`로 단일화
**영향**: 실패 시 즉시 복귀 가능, 기본은 sqlite
**다음 액션**: install/doctor/status에 rollback 플래그 노출

[ops][paths][design]
**신규 발견**: 엔진/레지스트리/로그/인덱스 경로 베이스를 `~/.local/share/sari`로 통일
**영향**: uninstall/purge 및 트러블슈팅 단순화
**다음 액션**: OS별 경로 매핑표 추가

[packaging][install][ux]
**신규 발견**: 자동 설치는 “첫 검색/재빌드/인덱서 갱신 요청 시 pip install (isolated venv)”로 정의
**영향**: 사용자 설정만으로 설치/실행 달성, 실패 시 ERR_ENGINE_NOT_INSTALLED
**다음 액션**: `DECKARD_ENGINE_AUTO_INSTALL=1/0`, offline 모드 규칙 추가

[ops][compat][paths]
**신규 발견**: SSOT config 경로는 기존 `~/.config/sari` 유지(호환), 데이터/로그/엔진은 sari로 통일
**영향**: 설정 호환성 유지 + 운영 경로 단순화
**다음 액션**: config/데이터 경로 표에 명시

[packaging][install][ux]
**신규 발견**: auto-install 실패/오프라인 → ERR_ENGINE_NOT_INSTALLED + hint 반환(자동 재시도 없음)
**영향**: 실패 상황이 명확히 드러나고, 사용자 제어 가능
**다음 액션**: 에러 메시지 템플릿 정의(아래)

[errors][template][engine]
**신규 발견**: 엔진 자동 설치 실패 템플릿 고정
**영향**: 클라이언트 일관 처리 가능
**다음 액션**:
- `ERR_ENGINE_NOT_INSTALLED`: "engine not installed (auto-install failed or disabled). run: sari --cmd engine install"
- `ERR_ENGINE_UNAVAILABLE`: "engine not ready (reason=<reason>). run: sari --cmd engine rebuild"

[ops][cli][contract]
**신규 발견**: 엔진 관리 명령 확정 → `sari --cmd engine status|rebuild|verify`
**영향**: 컷오버/복구/진단 경로 표준화
**다음 액션**: CLI 매핑/출력 스펙 추가

[ops][paths][design]
**신규 발견**: OS별 경로 매핑(Windows: %LOCALAPPDATA%\\sari, mac/linux: ~/.local/share/sari)
**영향**: 설치/로그/인덱스/레지스트리 위치 일관성 확보
**다음 액션**: install/doctor/status 출력 경로 표준화

[ops][cache][runtime]
**신규 발견**: 엔진 cache/index 경로 확정 → `~/.cache/sari/engine`, `~/.local/share/sari/index/<roots_hash>`
**영향**: roots_hash=sorted root_ids만 사용, 인덱스는 roots 조합별 분리
**다음 액션**: uninstall --purge 대상 경로 목록 업데이트

[api][contract][search]
**신규 발견**: PACK1 meta 키 확정 → `m:total`, `m:total_mode`, `m:engine`, `m:latency_ms`, `m:index_version`
**영향**: PACK1/JSON 응답 일관성 확보
**다음 액션**: mcp/tools/search 결과 포맷 반영

[cutover][process][validation]
**신규 발견**: validation 항목 확정( doc_count=SQLite parse_ok, index_size>0, sample_query_set 통과 )
**영향**: 컷오버 실패 시 즉시 롤백
**다음 액션**: sample_query_set 위치/포맷 정의

[tests][perf][quality]
**신규 발견**: 쿼리 세트 포맷 확정 → `docs/sari/plan/search-queries.txt` (1줄 1쿼리, UTF-8)
**영향**: 재현 가능한 품질/성능 검증
**다음 액션**: 초기 쿼리 세트 50(ASCII)+50(CJK) 수집

[index][build][process]
**신규 발견**: index_version 파일 포맷 확정(JSON: version, build_ts, doc_count, engine_version, config_hash)
**영향**: config_hash는 exclude/include/size/follow_symlinks/tokenizer/engine_version 포함
**다음 액션**: build/verify 단계에 기록/검증 추가

[errors][contract][ux]
**신규 발견**: ERR_ENGINE_NOT_INSTALLED 메시지 템플릿 확정(“auto-install 실패/비활성; engine rebuild 안내”)
**영향**: 사용자 진단/복구 경로 명확화
**다음 액션**: 에러 메시지/힌트 문구 일괄 정의

[api][contract][search]
**신규 발견**: SearchRequest에 `exclude_patterns` 포함(경로 필터로 해석)
**영향**: MCP/HTTP 기존 옵션과 의미 일치
**다음 액션**: 요청 매핑표에 exclude_patterns 추가

[api][contract][search]
**신규 발견**: `case_sensitive=true`는 엔진 모드에서 미지원(호환 우선: 에러 전환 금지)
**영향**: lowercasing 인덱스와의 충돌 제거
**다음 액션**: 문서에 “best-effort/무시 가능”로 명시

[review][design][contract]
**신규 발견**: 리뷰 로그에 스펙 모순/결정 공백 목록 정리 → `plan-20260203-search-engine-review.md`
**영향**: SearchRequest/Hit 호환, root_ids 의미, 인덱싱 정책, 필터 결합/정렬 확정 전 구현 리스크 높음
**다음 액션**: 리뷰 로그 항목을 스펙 본문에 반영하고 결정을 고정

[ssot][design][contract]
**신규 발견**: Dev-Ready SSOT 문서 확정 → `plan-20260203-search-engine-devready.md`
**영향**: 본 문서는 배경/근거용, 충돌 시 SSOT가 우선
**다음 액션**: 스펙 항목 중 충돌/중복을 SSOT 기준으로 정리, 결정 테이블(`plan-20260203-search-engine-decisions.md`) 참고
[migration][process][design]
**신규 발견**: dual-write/Phase 전개는 한방 컷오버 결정으로 폐기(legacy)
**영향**: Phase 문구는 deprecated, 컷오버 절차만 유지
**다음 액션**: 관련 섹션에 “deprecated” 주석 추가
