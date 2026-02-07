# Sari v3: The Final Masterpiece (Super Sari & CodeMRI)

## 1. 개요
Sari v3는 대규모 MSA 환경에서 에이전트의 인지 능력을 극대화하는 **"소프트웨어 엔지니어링 전용 OS"**를 지향한다. 본 설계는 성능, 비용, 지능의 완벽한 균형과 시스템의 영구적 지속 가능성을 목표로 한다.

## 2. PACK2: Raw-Frame & Security
*   **Byte-Length Protocol**: URL 인코딩을 폐지하고 `<<<<RAW:[byte_len]>>>>` 프레임을 사용한다. 길이는 UTF-8 바이트 기준으로 명시하여 다국어 깨짐을 방지한다.
*   **End-of-Frame Marker**: 블록 끝에 고유 마커를 두어 LLM이 데이터 경계를 물리적으로 확정하게 한다.
*   **Secret Shield**: 전송 직전 API Key, Password 등 민감 정보를 자동으로 마스킹(`****`) 처리한다.
*   **Context-Aware Path**: 가상 경로를 제거하고 현재 작업 맥락에 최적화된 **논리적 상대 경로**를 제공한다.

## 3. 3-Tier 하이브리드 엔진 & 지능 계층화
1.  **Tier 1 (FTS5)**: 전역 텍스트 검색 레이어.
2.  **Tier 2 (Static)**: Tree-sitter 기반 심볼 분석.
    *   **Dual-Indexing**: [Raw + Tokenized] 듀얼 인덱싱으로 정밀 검색 가중치 최적화.
    *   **Generator-based Parsing**: 한 번에 하나의 파일만 분석하여 메모리 단편화 방지.
3.  **Tier 3 (Dynamic)**: On-demand LSP. 
    *   **LSP Isolation**: 프로젝트별로 LSP 인스턴스를 격리하여 대규모 워크스페이스에서의 충돌을 방지하는 **Virtual Root Orchestrator**를 운영한다.
    *   **SSOT Hierarchy**: 데이터 충돌 시 LSP의 결과를 최우선(Source of Truth)으로 하며, Tree-sitter는 보조 지표로 활용하는 엄격한 우선순위를 적용한다.

## 4. CodeMRI: 로직 혈류 및 계층 추적
*   **Persistent Edge Table**: 심볼 간의 연결 고리를 DB화하여 콜드 스타트 시의 성능 저하를 방지한다.
*   **Recursive SQL Trace**: **`WITH RECURSIVE`** 쿼리를 통해 DB 레벨에서 1차 혈류 추적을 수행하여 대규모 호출 그래프 분석 속도를 극대화한다.
*   **Cycle Detection**: 순환 참조 발생 시 **Tarjan 알고리즘**을 적용하여 무한 루프를 방지하고 그래프를 평면화한다.

## 5. JIT(Just-In-Time) 및 자가 정비 아키텍처
*   **IJS (Implicit JIT Sync)**: 모든 질의 시점에 `os.stat`을 체크하여 변경된 파일만 즉시 부분 재인덱싱한다.
*   **Atomic Verification Delay**: 파일 시스템의 유령 이벤트를 방어하기 위해 변경 감지 시 미세한 **안정화 지연(Settling Time)** 후 검증을 수행한다.
*   **Self-Maintenance**: **`Incremental Vacuum`**을 활성화하고 유휴 시간에 정기적인 DB 최적화를 수행하여 인덱스 노화 및 파편화를 방지한다.
*   **WAL Checkpoint Tuning**: 별도 스레드에서 Passive Checkpoint를 수행하여 대규모 인덱싱 시 응답 Stall을 차단한다.

## 6. 리스크 관리 (Risks & Mitigations)
*   **환경 파편화**: 설치 전 로컬 런타임 버전을 선제적으로 체크한다.
*   **리소스 폭주**: 동시 실행 LSP 서버를 제한하고, 유휴 시 강제 종료(Idle Reaper)한다.
*   **신뢰성**: 추적이 불확실한 지점은 "안개 구간(Low Confidence)"으로 표시하여 에이전트의 오판을 방지한다.

---
*Last Refined: 2026-02-04*
*Architect: Sari-Agent (Inspired by The Creator's God-level Detail)*

---
*Last Refined: 2026-02-04*
*Architect: Sari-Agent (Inspired by The Creator's Extreme Precision)*

---
*Last Updated: 2026-02-04*
*Focus: Internal Infrastructure Audit & Optimization*

---
*Last Refined: 2026-02-04*
*Architect: Sari-Agent (Inspired by The Creator's Smile)*
