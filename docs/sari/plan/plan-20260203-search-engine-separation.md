# [05] 검색 엔진 분리 설계 v1 (델타)

[arch][perf][memory]
**신규 발견**: Search/Storage 분리(검색 전용 embedded 엔진 + SQLite 저장/메타)로 검색 경로 decompress 제거; 근거: sqlite fts5/fts3, typesense, meilisearch, tantivy
**영향**: LIKE 폴백 제거는 SSOT 기준으로 유예(compat 우선), MCP는 라우팅/권한만 담당
**다음 액션**: SearchAdapter 인터페이스 정의 (dual-write는 deprecated)

[build][ops][ux]
**신규 발견**: 설치 UX는 wheel 자동 설치(설정만 추가 → lazy install/launch)로 유지
**영향**: 엔진 미설치/실패 시 제한 모드 또는 명확한 에러 정책 필요
**다음 액션**: 패키징 전략(플랫폼별 wheel) + 실패 fallback 정책 확정

[perf][memory][design]
**신규 발견**: 기본 메모리 상한 soft cap 확정 → `DECKARD_ENGINE_MEM_MB=512` (MiB), 우선순위 CLI>ENV>config>default
**영향**: 인덱싱/머지 속도는 상한에 의해 조정됨(캐시/버퍼/스레드 제한)
**다음 액션**: 엔진 설정 키(threads/index_mem/cache) 스펙 문서화

[migration][process][db]
**신규 발견**: Phase 기반 dual-write 전개는 **deprecated**
**영향**: SSOT는 한방 컷오버(단일 빌드 후 atomic switch)만 유지
**다음 액션**: Phase 문구는 유지하되 “legacy 참고”로 명시

[api][contract][design]
**신규 발견**: SearchAdapter v1 인터페이스 초안(ensure_engine, index_upsert, index_delete, search, health, stats, rebuild)
**영향**: MCP/Indexer/HTTP는 엔진 직접 접근 금지 → Adapter 경유로 통일
**다음 액션**: 인터페이스 스펙(입출력/에러코드) 문서화

[migration][rollback][process]
**신규 발견**: Phase1 dual-write는 deprecated (SSOT=한방 컷오버)
**영향**: dual-write 완료 조건 정의는 불필요
**다음 액션**: 컷오버 검증 지표만 유지

[arch][design][search]
**신규 발견**: “한방 컷오버” 방향 선택 → dual-write 생략, 단일 빌드 후 atomically switch
**영향**: 빌드 실패/품질 저하 시 즉시 rollback 필요(엔진 비활성화 플래그)
**다음 액션**: 컷오버 플래그/안전성(검증 지표) 기준 정의

[arch][component][design]
**신규 발견**: 구성요소 분리 필요(EngineManager/Adapter/IndexWriter/IndexReader/Health)
**영향**: MCP는 Adapter만 호출, 엔진 로딩/설치/복구는 Manager가 책임
**다음 액션**: 컴포넌트 책임/라이프사이클 도식화

[data][index][schema]
**신규 발견**: 엔진 인덱스 문서 필드 최소화( doc_id, repo, path, ext, lang, mtime, size, search_text )
**영향**: 원문/심볼은 SQLite에서만 제공 → 검색 경로에서 decompress 제거
**다음 액션**: doc_id 규칙(root_id/path) 확정 및 파서/인덱서 연동 규칙 정의

[build][packaging][ops]
**신규 발견**: 엔진은 Python wheel(embedded)로 자동 설치, MCP는 lazy install/launch
**영향**: 플랫폼별 wheel 빌드/배포 파이프라인 필요(캐시/서명 정책 포함)
**다음 액션**: wheel 채널/캐시 경로/오프라인 정책 문서화

[perf][memory][config]
**신규 발견**: 리소스 상한 확정(기본 `DECKARD_ENGINE_MEM_MB=512`, threads/index_mem/cache 분리 옵션 필요)
**영향**: 512MiB cap 기준으로 인덱싱 속도/머지 정책이 자동 조정되어야 함
**다음 액션**: 메모리/스레드 옵션 키 스펙 및 우선순위 정의

[mcp][contract][api]
**신규 발견**: MCP/HTTP 검색 경로는 엔진 단일 경로(SSOT: sqlite 기본 유지, embedded opt-in)
**영향**: LIKE/FTS 제거는 보류, 실패 시 명시적 에러코드
**다음 액션**: 새로운 에러코드/상태 필드 정의 및 status 출력 항목 확정

[api][contract][search]
**신규 발견**: SearchAdapter I/O 스펙 필요(입력: query/filters/limit/offset; 출력: hits/meta; 에러코드)
**영향**: MCP/HTTP는 Adapter 결과 포맷에 의존 → 호환성 고정 필요
**다음 액션**: 오류 코드 세트(ERR_ENGINE_NOT_INSTALLED/ERR_ENGINE_INIT/ERR_ENGINE_INDEX) 정의

[arch][design][lifecycle]
**신규 발견**: EngineManager 라이프사이클은 SSOT 규칙에 따름
**영향**: ensure_installed→ensure_ready→search, 실패 시 ERR_ENGINE_* 템플릿 적용
**다음 액션**: SSOT 문서 링크로 대체

[config][memory][perf]
**신규 발견**: 메모리/스레드 옵션 키는 SSOT 확정값 사용
**영향**: engine_mem 512MiB, index_mem 256MiB, threads=2 기본
**다음 액션**: SSOT 기준으로만 유지

[data][id][contract]
**신규 발견**: doc_id 규칙은 SSOT에서 고정됨
**영향**: doc_id = root_id/rel_path
**다음 액션**: 별도 정의 불필요

[cutover][process][rollback]
**신규 발견**: 한방 컷오버는 “엔진 인덱스 완전 구축 + 원자적 스왑”이 필수
**영향**: 구축 실패 시 기존 인덱스/SQLite 경로로 즉시 롤백 필요
**다음 액션**: build-temp → validate → rename 스텝 정의 + 롤백 플래그 지정

[tests][perf][quality]
**신규 발견**: 컷오버 기준은 SSOT 수치로 고정
**영향**: Top10 overlap ≥0.7, P95 ≤200ms@50k docs, build error=0
**다음 액션**: 쿼리 세트 경로만 유지

[packaging][ops][build]
**신규 발견**: auto-install 캐시 경로는 SSOT 기준으로 고정
**영향**: `~/.cache/sari/engine`, `~/.local/share/sari/index` 사용
**다음 액션**: 경로 표만 유지

[migration][process][design]
**신규 발견**: dual-write/Phase 전개는 한방 컷오버 결정으로 폐기(legacy)
**영향**: 단계적 전환 문구는 혼선 유발 → 컷오버 절차만 유지
**다음 액션**: 관련 문구를 “deprecated”로 명시하고 컷오버 절차로 통일

[ops][paths][design]
**신규 발견**: cache/index 경로는 `~/.cache/sari/engine`, `~/.local/share/sari/index`로 통일(legacy sari 경로 폐기)
**영향**: 설치/삭제/운영 경로 혼선 제거
**다음 액션**: 관련 문서에 deprecated 표기 반영

[review][process][contract]
**신규 발견**: 리뷰 로그에 컷오버/rollback, Phase 잔존, 스코프 정의 등 모순 항목 정리 → `plan-20260203-search-engine-review.md`
**영향**: 구현 전 계약/절차의 합의가 필요, 미합의 시 일정 지연 위험
**다음 액션**: 리뷰 로그 항목을 분리/컷오버 설계에 반영해 결정 고정

[ssot][design][contract]
**신규 발견**: Dev-Ready SSOT 문서 확정 → `plan-20260203-search-engine-devready.md`
**영향**: 분리 설계 문서는 배경/근거 역할로 한정
**다음 액션**: 충돌 항목은 SSOT 기준으로 정리
