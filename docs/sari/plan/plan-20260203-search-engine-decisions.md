# [03] 검색 엔진 분리 결정 테이블 v1

[decision][filters][contract]
**신규 발견**: SQLite 필터 경로 기준은 rel_path로 전환(compat: db_path도 병행 매칭)
**영향**: 엔진/SQLite 결과 정합성 개선, 기존 테스트 영향 최소화
**다음 액션**: _matches_path_pattern/_matches_exclude_patterns에 rel_path 변환 추가

[decision][compat][data]
**신규 발견**: legacy path(db_path 없이 저장) 허용=읽기만(새 인덱싱은 root_id 포함)
**영향**: 기존 테스트/샘플 DB는 계속 동작, 신규 데이터는 SSOT 규칙 준수
**다음 액션**: read/search 결과는 doc_id 있으면 doc_id, 없으면 기존 path 유지(legacy는 root boundary 예외)

[decision][rollback][ops]
**신규 발견**: rollback=sqlite는 “필요 시 재빌드”이며 재빌드 전 검색은 제한(경고 포함)
**영향**: 즉시 복귀는 가능하지만 결과 품질은 재빌드 전까지 약화
**다음 액션**: doctor/status에 rollback 상태/필요 조치 명시

[decision][search][meta]
**신규 발견**: total_mode=approx는 “카운트 미계산”으로 정의하고 total=-1 고정
**영향**: 클라이언트는 정확한 total을 기대하지 않도록 안내 필요
**다음 액션**: search 응답 meta와 경고 문구에 반영

[decision][compat][paths]
**신규 발견**: legacy path(root_id 없는 path)는 read/search만 허용, write/index는 root_id 포함만 허용
**영향**: 기존 테스트/샘플 DB는 동작 유지, 신규 데이터는 SSOT 규칙 보장
**다음 액션**: resolve_db_path는 root_id 없는 path도 허용(읽기), 인덱서/업서트는 root_id 강제

[decision][rollback][ux]
**신규 발견**: rollback=sqlite 상태 메시지: “SQLite FTS 재빌드 필요, 완료 전 검색 제한” 고정
**영향**: 사용자에게 즉시 행동 지침 제공
**다음 액션**: doctor/status 출력 템플릿에 문구 추가

[decision][ops][ux]
**신규 발견**: engine_ready=false 시 status/doctor에 reason+hint 출력(예: config_hash mismatch, engine_version mismatch)
**영향**: 복구 경로 명확화(재빌드 유도)
**다음 액션**: 메시지 템플릿에 “run `sari --cmd engine rebuild`” 포함

[decision][ops][reason]
**신규 발견**: engine_ready=false reason 코드를 고정
**영향**: 클라이언트/운영 로그의 일관성 확보
**다음 액션**: reason={NOT_INSTALLED|INDEX_MISSING|CONFIG_MISMATCH|ENGINE_MISMATCH|ROLLBACK_MODE}, hint는 rebuild/install 안내

[decision][engine][package]
**신규 발견**: 엔진 패키지명/버전 핀 고정
**영향**: 재현 가능한 설치/업데이트 보장
**다음 액션**: 패키지명=`sari-search`, 버전 핀은 `sari`와 major/minor 동일

[decision][tokenizer][bundle]
**신규 발견**: CJK 토크나이저 사전 배포 정책 고정
**영향**: 오프라인 환경 안정성 확보
**다음 액션**: lindera 사전은 wheel에 포함, 누락 시 latin fallback

[decision][cutover][metrics]
**신규 발견**: 컷오버 기준 수치 고정
**영향**: 배포/롤백 기준 명확화
**다음 액션**: Top10 overlap ≥0.7, P95 ≤200ms@50k docs, build error=0

[decision][errors][template]
**신규 발견**: 엔진 자동 설치 실패 메시지 템플릿 고정
**영향**: 클라이언트/운영 메시지 일관성
**다음 액션**: ERR_ENGINE_NOT_INSTALLED/ERR_ENGINE_UNAVAILABLE 문구 확정

[decision][data][root_id]
**신규 발견**: root_id는 root path 정규화(follow_symlinks 설정 반영) 기준으로 생성
**영향**: follow_symlinks 변경 시 root_id/roots_hash 변경 → 리빌드 필요
**다음 액션**: root_id 산출 규칙을 config_hash 항목에 포함

[decision][filters][root_ids]
**신규 발견**: 요청 root_ids는 허용 roots와 교집합, 미지정 시 허용 roots 전체
**영향**: root boundary 유지 + 멀티-root 범위 지정
**다음 액션**: 교집합이 비면 ERR_ROOT_OUT_OF_SCOPE 반환

[decision][search][total_mode]
**신규 발견**: total_mode 요청 값 우선(미지정 시 서버 힌트), approx는 total=-1
**영향**: total_mode 혼선 제거, 성능 비용 통제
**다음 액션**: total_mode=approx일 때만 total=-1 고정

[decision][index][path_text]
**신규 발견**: path_text=doc_id + rel_path (root_id 없이도 경로 검색 가능)
**영향**: 경로 검색 UX 개선, 멀티-root 충돌 회피
**다음 액션**: path_text 생성 규칙을 인덱서/엔진에 동일 적용

[decision][filters][path_pattern]
**신규 발견**: path_pattern/exclude_patterns는 rel_path 기준, absolute pattern은 root 하위면 rel_path로 변환
**영향**: 엔진/SQLite/레거시 결과 정합성 개선
**다음 액션**: 변환 실패 시 no-match 처리
