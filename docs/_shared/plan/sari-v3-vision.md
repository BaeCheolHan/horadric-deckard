# Sari v3: CodeMRI & Super Sari Vision

## 1. 개요 (Overview)
사리(sari) v3는 기존의 **광속 탐색(SQLite FTS5)** 성능을 유지하면서, 세레나(Serena)의 **심층 의미 분석(LSP)** 지능을 흡수하여 에이전트(LLM)에게 가장 완벽한 코드 맥락을 제공하는 것을 목표로 한다. 단순한 검색기를 넘어 코드의 혈류를 짚어내는 **CodeMRI** 기능을 핵심 가치로 삼는다.

## 2. 핵심 개선 전략 (Core Pillars)

### A. 하이브리드 지능 엔진 (Hybrid Intelligence)
*   **L1 - Static Index (Fast)**: 기존 SQLite 기반의 고속 텍스트 검색 유지.
*   **L2 - Semantic Layer (Smart)**: 인덱싱 시점에 LSP 서버를 일시 가동하여 함수의 정밀한 경계(Line:Col), 상속 관계, 어노테이션 정보를 추출하여 DB에 "캐싱".
*   **On-demand MRI**: 복잡한 호출 트리나 데이터 흐름 분석이 필요할 때만 실시간 LSP 질의 수행.

### B. PACK2 프로토콜 (Token Efficiency)
*   **인코딩 폐지**: 토큰을 낭비하는 URL 인코딩(%20 등)을 100% 제거.
*   **Raw Frame 전송**: `<<<<RAW` / `RAW>>>>` 와 같은 커스텀 델리미터를 사용하여 소스 코드를 있는 그대로 에이전트에게 직배송.
*   **델타 전송**: 중복되는 맥락은 제외하고 변화된 정보와 핵심 코드 조각만 압축하여 전달.

### C. 계층적 심볼 관리 (Hierarchical Symbol Address)
*   **NamePath 시스템**: `Class/Method[Index]` 형태의 주소 체계를 도입하여 중복 이름 및 오버로딩 완벽 구분.
*   **Relationship Mapping**: "누가 누구를 부르는가"를 넘어 "누가 누구의 부모인가", "어떤 인터페이스의 구현체인가"를 인덱스 레벨에서 연결.

## 3. 핵심 신기능: CodeMRI
*   **Logic Bloodflow**: 특정 API나 함수를 찍으면 `Controller -> Service -> Repository -> DB`까지 이어지는 전체 데이터 흐름을 재귀적으로 추적하여 시각화.
*   **Framework Awareness**: Spring Boot의 `@GetMapping`, `@Service`, React의 `useMemo` 등을 단순 텍스트가 아닌 '기능적 심볼'로 인식.

## 4. 개발 로드맵 (Roadmap)

### Phase 1: 기반 다지기 (안정성 및 효율화)
*   [ ] `sari/mcp/tools/_util.py` 내 인코딩 로직 제거 (Raw Text 지원)
*   [ ] 가상 경로(`root-xxxx/`) 제거 및 워크스페이스 상대 경로 표준화
*   [ ] 설치 및 업데이트 스크립트(`install.sh`) 통합 및 `doctor` 자동화

### Phase 2: 지능 이식 (LSP & Tree-sitter)
*   [ ] 가벼운 파서(Tree-sitter) 또는 LSP 클라이언트 모듈 사리 코어에 통합
*   [ ] 인덱서(`indexer.py`)에 정확한 심볼 범위(Range) 및 어노테이션 추출 로직 추가
*   [ ] NamePath 기반의 고유 심볼 ID 체계 구축

### Phase 3: CodeMRI 구현
*   [ ] 재귀적 호출 추적 (`get_callers --deep`) 기능 개발
*   [ ] 데이터 흐름 추적 및 텍스트 기반 그래프 출력 엔진 개발

---
*작성일: 2026년 2월 4일*
*작성자: Sari-Agent (Inspired by the Creator)*
