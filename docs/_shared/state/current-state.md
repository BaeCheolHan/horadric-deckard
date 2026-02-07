# StockManager 프로젝트 분석 요약

## 프로젝트 구조
- **Back-end**: `StockManager-v-1.0` (Spring Boot, Java 17)
- **Front-end**: `stock-manager-front` (Vue.js 3, Vuetify)
- **Library**: `yfin-java-lite` (Yahoo Finance 연동)

## 주요 기능
- 주식/배당금 통합 관리 및 시각화
- 한국투자증권(KIS) API를 통한 실시간 시세 및 거래 연동
- 소셜 로그인 및 개인화 설정

## 기술 부채 및 특이사항
- `StockManager-private` 레포지토리에 민감한 설정이 분리되어 있음
- Querydsl 빌드 결과물(Q클래스)이 `bin/` 디렉토리에 포함되어 있음