# Sari v3 Technical Specification: The "Super Sari" Architecture

## 1. Vision: "The Omniscient Code Observer"
단순한 검색 엔진을 넘어, 코드의 정적 맥락(FTS5)과 동적 지능(LSP/Tree-sitter)을 결합하여 에이전트에게 최소한의 비용(Token)으로 최대한의 통찰(MRI)을 제공하는 소프트웨어 엔지니어링 전용 OS로 진화한다.

## 2. 하이브리드 엔진 아키텍처 (Layered Intelligence)

### L1: Discovery Layer (SQLite FTS5)
*   **역할**: 전 프로젝트의 고속 텍스트 검색 및 파일 위치 파악.
*   **특징**: 기동 즉시 사용 가능. 20개 MSA 프로젝트의 수만 개 파일을 0.1초 내 탐색.

### L2: Metadata Layer (Tree-sitter)
*   **역할**: 함수의 경계(Range), 파라미터, 어노테이션(@) 정보의 상시 보유.
*   **특징**: 인덱싱 시점에 가벼운 파서를 통해 DB에 캐싱. LSP 없이도 "똑똑한 검색" 수행.

### L3: MRI Layer (On-demand LSP)
*   **역할**: 심층 호출 트리(Deep Call-Graph) 분석 및 데이터 흐름 추적.
*   **특징**: 요청이 있는 순간에만 활성화되는 서버 풀링 방식.

## 3. 무결점 동기화 전략 (JIT Indexing)
LLM의 통지 누락이나 사용자의 외부 편집에 상관없이 데이터 정합성을 100% 유지한다.

*   **Selective JIT Validation**: 모든 도구(`read_symbol`, `get_callers` 등)는 응답 전 검색 결과 상위 $K$개 파일에 대해 `os.stat()`을 수행한다.
*   **Implicit Re-indexing**: `mtime`이 DB의 `last_indexed_at`과 다를 경우, 응답 직전에 해당 파일만 즉시 재분석하여 DB를 동기화한다.
*   **Performance**: 수만 개 파일이 아닌 "현재 다루는 소수 파일"만 체크하므로 I/O 부하가 거의 없다.

## 4. PACK2 프로토콜 (The Token-Tax Reform)
URL 인코딩 오버헤드를 완전히 제거하여 토큰 효율을 3배 이상 향상시킨다.

*   **Raw Frame Delimiter**: 인코딩 대신 `<<<<RAW:[length]>>>>` 와 같은 커스텀 프레임을 사용하여 소스 코드를 있는 그대로 전송한다.
*   **Logical Path Strip**: 에이전트에게 전달되는 모든 경로는 가상 경로(`root-xxxx/`)를 제거한 **워크스페이스 상대 경로**로 표준화한다.

## 5. 리소스 및 메모리 관리 (MSA Scale-out)
20개 이상의 대규모 프로젝트 환경에서도 시스템 부하를 최소화한다.

*   **LSP Server Pooling**: 활성화된 프로젝트 범위를 감지하여 동시 실행 LSP 개수를 제한한다 (Default: 3개).
*   **Idle Reaper**: 5분간 활동이 없는 LSP 서버 프로세스는 사리 데몬이 자동으로 종료하여 RAM을 반환한다.
*   **Lazy Loading**: 최초 인덱싱 시에는 L1/L2 정보만 구축하며, L3 MRI 데이터는 에이전트가 해당 지점을 탐색할 때 비동기로 채워 넣는다.

## 6. 개발 로드맵 (Action Items)

### Phase 1: 기반 인프라 개조 (현재 착수 가능)
*   `_util.py` 내 PACK2 프로토콜 (인코딩 제거) 구현.
*   가상 경로 매핑 및 표준화 로직 적용.
*   DB 스키마에 `mtime`, `hash`, `symbol_range` 컬럼 추가.

### Phase 2: 지능 주입 및 JIT 구현
*   Tree-sitter 라이브러리 통합 및 L2 메타데이터 추출기 개발.
*   도구 호출 시 `os.stat` 기반의 JIT Validation 로직 삽입.

### Phase 3: CodeMRI 완성
*   재귀적 호출 트리 분석 및 텍스트 그래프 렌더러 개발.
*   LSP 서버 풀링 및 라이프사이클 관리 모듈 개발.

---
*Last Updated: 2026-02-04*
*Architect: Sari-Agent (Co-authored by The Creator)*
