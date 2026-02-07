# Sari (사리) 레포지토리 분석 보고서

**작성일**: 2026년 2월 7일
**대상**: `sari` 레포지토리 핵심 구조 및 동작 원리

## 1. 개요
**Sari**는 고성능 로컬 코드 검색 에이전트로, [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)를 기반으로 동작합니다. 대규모 코드베이스를 로컬에서 인덱싱하고, AI 어시스턴트가 효율적으로 코드를 탐색할 수 있도록 다양한 도구를 제공합니다.

## 2. 핵심 아키텍처

### 2.1 Core (인덱싱 및 검색 엔진)
- **Indexer (`sari/core/indexer`)**:
    - `ProcessPoolExecutor`를 사용한 멀티프로세스 병렬 인덱싱.
    - `ParserFactory`를 통해 언어별 AST(Abstract Syntax Tree) 심볼 추출.
    - 파일 변경 감지(Watcher)를 통한 증분 인덱싱 지원.
- **Search Engine (`sari/core/search_engine.py`)**:
    - **하이브리드 검색**: Tantivy(고성능 전문 검색 엔진)와 SQLite FTS5(내장 검색)를 조합.
    - **순위화(Ranking)**: 최근 작업 파일(L2 Cache), 키워드 매칭, 심볼 구조를 고려한 점수 정규화 및 정렬.
- **Database (`sari/core/db`)**:
    - SQLite WAL(Write-Ahead Logging) 모드를 사용한 고성능 동시성 제어.
    - 파일 내용 zlib 압축 저장으로 디스크 공간 최적화.
    - 심볼, 호출 그래프(Call Graph), 스니펫, 컨텍스트 등 풍부한 스키마 지원.

### 2.2 MCP (인터페이스 레이어)
- **Server (`sari/mcp/server.py`)**:
    - stdio 및 TCP 전송 방식 지원.
    - 데몬(Daemon) 모드를 통한 클라이언트 로딩 속도 향상(Thin-adapter 모드).
    - 정책 엔진(Policy Engine)을 통한 도구 실행 권한 제어.
- **Tools (`sari/mcp/tools`)**:
    - `search`, `list_files`, `read_file`: 기본 탐색.
    - `search_symbols`, `read_symbol`: 정밀 코드 분석.
    - `call_graph`, `get_callers`: 구조적 의존성 파악.
    - `save_snippet`, `archive_context`: 지식 및 컨텍스트 관리.

## 3. 주요 기능 및 특징

| 기능 | 설명 |
|------|------|
| **고정밀 심볼 추출** | Tree-sitter 등을 활용하여 클래스, 함수, 변수 등의 구조적 정보 추출. |
| **호출 그래프** | 심볼 간의 관계를 추적하여 상향/하향 의존성 분석 지원. |
| **지식 캡처** | `archive_context`를 통해 도메인 지식과 관련 파일을 연결하여 저장. |
| **로컬 보안** | 모든 인덱싱 데이터와 로그가 사용자 로컬 환경(`~/.local/share/sari`)에 보관됨. |
| **확장성** | `cjk`(한중일 형태소 분석), `treesitter`, `full`(Tantivy) 등 옵션 설치 지원. |

## 4. 데이터 흐름
1. **스캔/인덱싱**: `Indexer`가 워크스페이스를 스캔하고 파서를 통해 정보를 추출하여 SQLite DB에 저장.
2. **MCP 요청**: AI 클라이언트가 `stdio` 또는 `HTTP`를 통해 `LocalSearchMCPServer`에 도구 실행 요청.
3. **도구 실행**: `ToolRegistry`에서 해당 도구를 찾아 `SearchEngine` 또는 `DB`를 조회.
4. **응답 반환**: 조회된 결과를 JSON-RPC 형식으로 클라이언트에 전달.

## 5. 결론
Sari는 단순한 텍스트 검색을 넘어 코드의 구조적 이해(AST, Call Graph)와 사용자 컨텍스트 관리(Snippet, Context)를 결합한 종합적인 코드 인텔리전스 도구입니다. 특히 로컬 데몬과 하이브리드 검색 엔진을 통해 속도와 보안을 동시에 확보하고 있습니다.
