# yfin-java-lite 프로젝트 심층 분석 보고서

**날짜**: 2026년 1월 31일
**분석 대상**: yfin-java-lite (WebFlux 기반 금융 데이터 서버)

## 1. 개요 및 아키텍처
`yfin-java-lite`는 Yahoo Finance를 주 데이터 소스로, KIS(한국투자증권) WebSocket을 실시간 소스로 사용하는 고성능 비동기 금융 데이터 API 서버입니다.

- **Stack**: Spring Boot 3.3.2 (WebFlux), Java 17, Gradle
- **Persistence**: MongoDB Reactive (뉴스, 기업 개요 등 영속화)
- **Caching**: Caffeine (L1), Redis (L2 & Token Management)
- **Networking**: Netty (Reactor Netty), WebClient

## 2. 핵심 컴포넌트 상세 분석

### 2.1 실시간 시세 스트리밍 (`QuoteWebSocketHandler`)
실시간 주식 시세를 클라이언트에게 푸시하는 핵심 컴포넌트입니다.

- **Hybrid Sourcing**: KIS(국내/해외)와 Finnhub(해외) 두 가지 소스를 병합(`Flux.merge`)하여 제공합니다.
- **Multiplexing (Fan-out)**:
    - `KisWebSocketManager`가 KIS 서버와 **단일 WebSocket 연결**을 유지합니다.
    - 여러 클라이언트가 동일 종목을 요청해도, KIS 서버로는 단 한 번의 구독 요청만 전송됩니다.
    - 수신된 데이터는 서버 내부에서 각 클라이언트 세션(`WebSocketSession`)으로 분배됩니다.
- **Resilience**:
    - `distinctUntilChanged`: 가격이나 등락률 변화가 있을 때만 이벤트를 전송하여 대역폭 절약.
    - **Heartbeat**: 15초마다 `{"hb":1}` 메시지를 전송하여 연결 상태 확인.
    - **Symbol Normalization**: `TickerResolver`를 통해 입력된 티커(예: `005930`)를 거래소 표준 형식(예: `005930.KS`)으로 자동 변환.

### 2.2 시세 조회 서비스 (`QuoteService`)
REST API(`/quote`, `/quotes`) 요청을 처리하며, 스크래핑 탐지 회피를 위한 정교한 로직이 포함되어 있습니다.

- **Multi-Level Caching**:
    - **Redis (Level 2)**: `quotes:{symbols}` 키로 캐싱. TTL은 45초로 짧게 설정되어 실시간성 유지.
- **Batching & Jitter**:
    - 다건 조회 시 **8개 단위로 배치(Batch) 분할**하여 요청.
    - `ThreadLocalRandom`을 사용한 **Jitter(120~320ms)**를 두어 기계적인 요청 패턴을 숨김 (Yahoo 차단 회피).
- **Fallback Strategy (Circuit Breaker)**:
    - Yahoo API 호출 실패(429/403 등) 시, 즉시 `AlphaVantage` 또는 `Finnhub`으로 폴백.
    - **Load Balancing**: 폴백 시 심볼의 해시값(`hashCode()`)에 따라 트래픽을 Finnhub과 AlphaVantage로 50:50 분산.
    - **Enrichment**: Yahoo 응답에 배당 정보가 누락된 경우, `quoteSummary` API나 `DividendsService`(과거 배당 내역 기반 추산)를 추가 호출하여 데이터를 보강.

### 2.3 데이터 영속성 및 기타
- **NewsAggregator**: Google, Naver, Yonhap 등 이기종 뉴스 소스를 통합하여 MongoDB에 저장(`NewsRepository`).
- **Reactive Pattern**: 프로젝트 전체가 `Mono`/`Flux` 체인으로 구성되어 있어, 스레드 차단 없이 높은 동시성을 처리함.

## 3. 코드 패턴 및 특징
- **방어적 프로그래밍**: 외부 API 의존도가 높기 때문에 `timeout`, `onErrorResume`, `switchIfEmpty` 등의 Reactor 연산자가 매우 적극적으로 사용됨.
- **Graceful Shutdown**: WebSocket 연결 종료 시 KIS 서버에 구독 해제(`tr_type=2`)를 명시적으로 요청하여 좀비 구독 방지.
- **DTO Mapping**: 외부 API(Yahoo, Finnhub 등)의 서로 다른 JSON 구조를 `QuoteDto`라는 통일된 모델로 매핑하여 일관된 응답 보장.

## 4. 향후 개선 포인트
- **테스트 격리**: 외부 API 호출이 많은 구조상 `WireMock` 등을 활용한 통합 테스트 환경 구성 권장.
- **모니터링**: Fallback 발생 빈도, API Latency 등을 추적할 수 있는 Metrics(Micrometer) 도입 필요.
- **동적 설정**: Jitter 범위나 배당 보강 로직 등을 런타임에 조정할 수 있도록 Config Server 도입 고려.