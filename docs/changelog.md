# Changelog

JonberAI Trading 변경 이력

---

## [Unreleased]

### Added
- ReadTheDocs 문서화 시스템 구축
- MkDocs Material 테마 적용

---

## [2026-01-03]

### Added
- **P2: WebSocket 체결 알림** (`bdc6fbf`)
  - `/ws/trade-notifications` WebSocket 엔드포인트
  - `TradeNotificationManager` 알림 구독자 관리
  - `useTradeNotifications` React hook
  - `TradeNotificationToast` 실시간 토스트 UI
  - Telegram과 병행 알림 시스템

- **P0.2: 장 마감 시 UI/UX 개선** (`9a94516`)
  - `GET /api/trading/market-status` API
  - `MarketStatusBanner` 컴포넌트
  - `useMarketHours` hook
  - `ApprovalDialog` 장 마감 경고
  - `TradeQueueWidget` 실행 시간 표시

### Changed
- 문서 구조 정리 및 현행화

---

## [2026-01-02]

### Added
- **P0: Agent Group Chat Frontend** (`81c7742`, `617b5ff`, `6a3acc4`)
  - `AgentChatDashboard` 메인 대시보드
  - `ChatSessionList` 세션 목록
  - `ChatSessionViewer` 토론 내용 뷰어
  - `PositionMonitor` 포지션 모니터링
  - `useAgentChatWebSocket` 실시간 업데이트 hook
  - API 클라이언트 함수 22개 추가

- **P0.1: AgentWorkflowGraph** (`d9be1ef`)
  - 수직 흐름 그래프 레이아웃
  - `AgentNode` 클릭 가능한 노드
  - `AgentDetailModal` 세부 정보 모달
  - CSS 기반 커넥터

- **P0.1.1: Trade Queue 중복 종목 처리**
  - 한국어 에러 메시지
  - FAILED 상태 UI 개선
  - Dismiss 버튼 추가

---

## [2025-12-31]

### Added
- **Agent Group Chat Backend** (`9ff318a`)
  - 완전한 Backend API 구현 (142개 테스트 통과)
  - `ChatRoom`, `Coordinator`, `PositionManager`
  - 5개 전문 Agent (Technical, Fundamental, Sentiment, Risk, Moderator)

- **Telegram 알림 서비스** (`7dab9a1`)
  - 거래 제안/체결/거부 알림
  - 포지션 업데이트 알림
  - 손절/익절 도달 알림
  - 4000자 초과 메시지 자동 분할

- **Watch List 기능**
  - WATCH 액션 타입
  - Watch → Trade Queue 변환

- **Background Scanner**
  - KOSPI/KOSDAQ 전종목 스캔
  - BUY/WATCH/AVOID 필터링

- **다국어 지원 (i18n)** (`5260074`)
  - 한/영 다국어 지원
  - `LanguageProvider`, `useTranslation` hook

### Changed
- TradeAction 타입 확장 (ADD, REDUCE, WATCH, AVOID)
- 코드 리팩토링: kr_stock_nodes 모듈화

---

## [2025-12-30]

### Added
- **Auto-Trading 기본 구조** (`9b7d7c6`)
  - `Portfolio Agent`
  - `Order Agent`
  - `Risk Monitor`
  - `TradingStatusWidget`
  - `Execution Coordinator`

- **News API 연동** (`b6365f2`)
  - Naver 뉴스 API (100건 조회)
  - Sentiment Analysis 통합

---

## [2025-12-29]

### Added
- **Kiwoom 한국 주식 연동** (`218fe94`)
  - Kiwoom OpenAPI+ 클라이언트
  - 모의투자/실거래 전환 지원
  - 278개 API 테스트 통과

- **기술 지표 시스템** (`e2c1f72`)
  - RSI, MACD, Stochastic, Bollinger Bands
  - 분석 데이터 저장

---

## [2025-12-28]

### Added
- 초기 프로젝트 구조
- FastAPI Backend
- React Frontend
- LangGraph Agent 워크플로우
- HITL Approval 워크플로우
- WebSocket 실시간 스트리밍

---

## 버전 관리

이 프로젝트는 [Semantic Versioning](https://semver.org/)을 따릅니다.

- **Major**: 호환되지 않는 API 변경
- **Minor**: 새로운 기능 추가 (하위 호환)
- **Patch**: 버그 수정

---

## 기여자

- KIMSUNGHOON - 프로젝트 리더
- Claude Opus 4.5 - AI 페어 프로그래머
