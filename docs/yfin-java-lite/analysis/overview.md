# yfin-java-lite 분석 보고서

## 1. 프로젝트 개요
**yfin-java-lite**는 Yahoo Finance 데이터를 기반으로 시세, 차트, 배당, 옵션 정보를 제공하는 경량 Spring Boot 서버입니다. 
Reactive Stack(WebFlux)을 기반으로 하여 고성능 비동기 처리를 지원하며, 한국투자증권(KIS) WebSocket을 연동하여 실시간 시세 스트리밍 기능을 제공합니다.

## 2. 기술 스택
- **Language**: Java 17
- **Framework**: Spring Boot 3.3.2 (WebFlux)
- **Database**:
  - Redis (Reactive): KIS WebSocket 토큰 및 데이터 캐싱
  - MongoDB (Reactive): (선택사항) 데이터 영속화
- **Caching**: Caffeine (Local Cache) + Redis (Distributed)
- **Build Tool**: Gradle
- **Key Libraries**: Lombok, SpringDoc (Swagger)

## 3. 프로젝트 구조
- **Root Package**: `com.example.yfin`
- **Entry Point**: `YfinJavaLiteApplication.java`

### 주요 패키지 구성
| 패키지 | 설명 |
|--------|------|
| `config` | Spring 설정 (WebClient, Redis, Mongo 등) |
| `controller` | (Root에 위치) `ApiController`, `StreamController` 등 REST 엔드포인트 |
| `service` | 비즈니스 로직 (Yahoo API 호출, 데이터 가공) |
| `kis` | 한국투자증권 WebSocket 연동 및 토큰 관리 |
| `realtime` | 실시간 데이터 스트리밍 처리 |
| `http` | 외부 API 통신 (WebClient) |
| `model` | DTO 및 도메인 객체 |
| `repo` | Repository 레이어 |
| `util` | 유틸리티 클래스 |

## 4. 주요 기능
1.  **Yahoo Finance Proxy**: 시세, 차트, 배당, 옵션 등 Yahoo Finance 데이터를 JSON 형태로 제공.
2.  **실시간 스트리밍**: SSE(Server-Sent Events) 및 WebSocket을 통해 실시간 주가 데이터 전송.
3.  **하이브리드 아키텍처**:
    - 일반 데이터: Yahoo Finance API (Polling/Request)
    - 실시간 데이터: KIS WebSocket (Push)
4.  **멀티 레벨 캐싱**: Caffeine(메모리) -> Redis -> Source 순의 조회 전략 추정.

## 5. 빌드 및 실행
- **빌드**: `./gradlew clean bootJar`
- **실행**: `java -jar build/libs/yfin-java-lite-0.1.0.jar`
- **설정**: `application.yml` 및 `StockManager-private` 서브모듈의 보안 설정 사용.
