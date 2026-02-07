# [02] 검색 엔진 분리 Dev-Ready Spec v1 (SSOT)

[ssot][scope][contract]
**신규 발견**: 본 문서는 구현 SSOT이며 충돌 시 최우선 적용
**영향**: 구현/테스트는 이 문서 기준으로 고정하고, 상세 논의는 참조 문서로만 유지
**다음 액션**: 참조: `plan-20260203-search-engine-spec.md`, `plan-20260203-search-engine-separation.md`, `plan-20260203-search-engine-review.md`, `plan-20260203-search-engine-decisions.md`

[mcp][interface][ext]
**신규 발견**: MCP 도구는 인터페이스 기반(Registry + ToolContext)으로 구현해 확장성을 확보
**영향**: 신규 도구 추가 시 server 코드 변경 최소화(등록만)
**다음 액션**: Tool 인터페이스( name, schema, execute(ctx,args)->ToolResult ), ToolRegistry, 공통 ToolContext(db/engine/roots/config/logger/clock/fs) 정의

[impl][perf][algo]
**신규 발견**: 구현은 성능 최우선으로 알고리즘/자료구조를 적극 활용해야 함
**영향**: 검색/필터링/정렬/캐시 경로에서 불필요한 선형 스캔 최소화
**다음 액션**: 도구별 핫패스에 적합한 자료구조/알고리즘 명시(아래)

[impl][perf][hotpaths]
**신규 발견**: 핫패스별 알고리즘/자료구조 가이드
**영향**: 엔진/SQLite/도구 계층에서 불필요한 비용 제거
**다음 액션**:
- search: top‑K는 min‑heap(K) + early‑exit, 정렬은 partial sort, recency는 precomputed buckets
- filters: root_ids/repo/file_types는 set membership, path_pattern은 compiled glob 캐시(LRU)
- pagination: offset 큰 경우 seek‑after( score, mtime, path ) 키 사용 고려
- caching: query→hits/meta LRU(짧은 TTL) + stats TTL cache 유지
- indexer: batching(commit_batch_size), dedup은 hash/set, large file sample head/tail
- locks: install/build file lock + pid check, backoff with jitter

[api][request][search]
**신규 발견**: SearchRequest 필드= query, limit, offset, repo, root_ids, file_types, path_pattern, exclude_patterns, snippet_lines, recency_boost, use_regex, case_sensitive, total_mode
**영향**: use_regex/case_sensitive는 엔진 미지원(호환 우선: 에러 전환 금지), total_mode는 요청 값 우선, recency_boost는 mtime 재랭킹, snippet_lines는 preview 기반 best-effort
**다음 액션**: total_mode=요청 값 우선(미지정 시 서버 힌트), approx는 total=-1(미계산)로 고정

[api][request][mapping]
**신규 발견**: MCP/HTTP search 입력은 root_ids/total_mode를 직접 수용
**영향**: 사용자가 root 범위와 total_mode를 명시적으로 제어 가능
**다음 액션**: total_mode 미지정은 서버 힌트 적용, 지정값은 우선 적용

[api][response][search]
**신규 발견**: SearchHit 필드= doc_id, repo, path, score, snippet, mtime, size, match_count, file_type, hit_reason, context_symbol, docstring, metadata
**영향**: 엔진 모드에서 docstring/metadata/context_symbol/hit_reason/match_count는 기본값(빈 문자열/0) 허용
**다음 액션**: path=doc_id=`root_id/rel_path`(“/” 구분자)로 고정, legacy path는 read/search만 허용

[api][response][search-hit]
**신규 발견**: path와 doc_id는 항상 `root_id/rel_path`로 동일
**영향**: 표시용 path는 SearchHit에 그대로 사용, legacy path는 read/search에서만 허용
**다음 액션**: rel_path 표준화 규칙을 indexer/engine 모두 동일 적용

[api][compat][legacy]
**신규 발견**: legacy path(root_id 없는 db_path)는 read/search만 허용
**영향**: 과거 테스트/샘플 DB는 동작 유지, 신규 write/index는 SSOT 강제
**다음 액션**: legacy path는 root boundary 예외임을 문서화

[search][filters][contract]
**신규 발견**: 필터 결합 규칙=카테고리 간 AND, 동일 카테고리 내 OR
**영향**: repo는 rel_path 첫 세그먼트(없으면 `__root__`), root_ids는 root_id exact 매칭
**다음 액션**: rel_path는 `root_id/` 접두가 있으면 제거, 없으면 path 그대로 사용; glob은 rel_path 기준 적용(메타 없으면 substring 포함), absolute pattern은 root 하위면 rel_path로 변환

[search][filters][root-boundary]
**신규 발견**: root boundary는 Collector 단계에서 제외 처리, Orchestrator는 재검증만 수행
**영향**: roots 밖 경로는 FileItem 미생성 (hard exclude)
**다음 액션**: root boundary 위반 시 ERR_ROOT_OUT_OF_SCOPE는 search에서만 반환

[search][filters][root_ids]
**신규 발견**: 요청 root_ids는 허용 roots와 교집합(없거나 빈 경우=허용 roots 전체)
**영향**: root boundary 위반 방지, 멀티-root에서 범위 지정 가능
**다음 액션**: 교집합이 비면 ERR_ROOT_OUT_OF_SCOPE 반환

[search][semantics][query]
**신규 발견**: 쿼리 의미=토큰 AND, "..." phrase, OR/regex/wildcard 미지원
**영향**: 쿼리 정규화는 NFKC + lower + 공백 정리(연속 공백 1개)로 고정
**다음 액션**: 미지원 옵션은 best-effort(무시/평문 처리)로 문서화

[index][policy][data]
**신규 발견**: 모든 파일에 path_text 인덱싱(doc_id + rel_path), parse_ok 파일만 body_text 인덱싱
**영향**: 경로 검색은 항상 가능(사용자는 root_id 없이도 검색 가능), 본문 검색은 parse_ok에 한정
**다음 액션**: path_text 구성=doc_id + " " + rel_path, index_text cap=4MiB, 초과 시 head 2MiB + tail 2MiB 샘플

[index][policy][content-empty]
**신규 발견**: content empty & non-binary는 parse_status=skipped, parse_reason=no_parse
**영향**: meta row 유지, body_text 비움
**다음 액션**: Validator 규칙에 no_parse 허용 추가

[data][id][root]
**신규 발견**: root_id는 root path 정규화(follow_symlinks 설정 반영) 기준으로 생성
**영향**: follow_symlinks 변경 시 root_id/roots_hash가 변경되어 리빌드 필요
**다음 액션**: root_id 산출 규칙을 config_hash 항목에 포함

[data][id][doc]
**신규 발견**: doc_id는 `root_id/rel_path` 형식으로 고정
**영향**: SearchHit.path도 동일 형식 사용
**다음 액션**: legacy path는 read/search만 허용, index write는 SSOT 형식만

[index][scope][ops]
**신규 발견**: 엔진 인덱스는 roots 해시 단위로 분리 (roots_hash=sorted root_ids만)
**영향**: exclude/include/size/follow_symlinks/tokenizer/engine_version 변경은 config_hash 불일치로 rebuild 필요
**다음 액션**: 인덱스 경로= `~/.local/share/sari/index/<roots_hash>`

[index][sync][process]
**신규 발견**: 엔진 인덱스는 인덱서 파이프라인과 동기 갱신(단일 소스)
**영향**: SQLite 저장/메타와 동시 업데이트, 엔진 미설치+AUTO_INSTALL=0이면 갱신 스킵
**다음 액션**: 인덱서 비활성 시 engine_ready=false로 노출

[engine][lifecycle][install]
**신규 발견**: auto-install은 첫 검색/재빌드 요청 시 isolated venv에 수행
**영향**: `DECKARD_ENGINE_AUTO_INSTALL=0` 또는 오프라인이면 ERR_ENGINE_NOT_INSTALLED
**다음 액션**: 수동 설치 경로=`sari --cmd engine install` 추가

[concurrency][locks][ops]
**신규 발견**: 엔진 install/build는 전용 lock으로 직렬화
**영향**: 다중 프로세스에서 중복 설치/빌드 방지
**다음 액션**: lock 파일= `~/.cache/sari/engine/install.lock`, `.../build.lock`

[status][meta][contract]
**신규 발견**: SearchResponse meta의 engine/index_version은 “실제 사용값”으로 고정
**영향**: total_mode=approx이면 total=-1, engine_version/config_hash 불일치로 engine_ready=false → ERR_ENGINE_UNAVAILABLE
**다음 액션**: index_version.json={version, build_ts, doc_count, engine_version, config_hash}, status/doctor는 reason+hint 출력

[status][meta][reason]
**신규 발견**: engine_ready=false 사유 템플릿 고정
**영향**: 운영 복구 경로 명확화
**다음 액션**: reason={NOT_INSTALLED|INDEX_MISSING|CONFIG_MISMATCH|ENGINE_MISMATCH|ROLLBACK_MODE}, hint="sari --cmd engine rebuild" 또는 install 안내

[cutover][rollback][process]
**신규 발견**: 한방 컷오버=build-temp→validate→atomic rename→restart
**영향**: rollback=sqlite 모드는 sqlite FTS 재빌드 필요 시 완료 전 검색 제한(경고 문구 고정)
**다음 액션**: overlap 비교는 “호환 쿼리만” 수행

[memory][perf][config]
**신규 발견**: MEM_MB/INDEX_MEM_MB 단위는 MiB로 해석
**영향**: clamp 규칙= index_mem<=engine_mem/2, threads<=min(2,cpu)
**다음 액션**: default=engine_mem 512MiB, index_mem 256MiB, threads 2

[compat][naming][deckard]
**신규 발견**: deckard 모듈/엔트리포인트는 호환용으로만 유지
**영향**: 외부 표기는 sari로 통일, 향후 버전에서 제거 예정
**다음 액션**: README/로그에 deprecation 문구 유지

[lang][tokenizer][index]
**신규 발견**: 언어 감지= CJK 코드포인트 존재 시 lang=cjk, 그 외 latin
**영향**: tokenizer= cjk→lindera, latin→unicode61 유사
**다음 액션**: lang 미탐지 시 latin fallback

[paging][order][contract]
**신규 발견**: 페이지네이션 정렬= score desc → mtime desc → path asc
**영향**: offset 기반 결과 중복/누락 최소화
**다음 액션**: 엔진 결과 정렬을 이 기준으로 고정

[pre-impl][checklist]
**신규 발견**: 구현 전 필수 체크 항목
**영향**: 구현 착수 전 설계 누락 방지
**다음 액션**:
- doc_id/root_id 규칙 SSOT 일치 확인
- ERR_ENGINE_* 템플릿 반영 여부 확인
- tokenizer 번들 정책 반영 여부 확인
- package pin(`sari-search`) 정책 반영 여부 확인
- cutover 지표 수치 고정 확인
