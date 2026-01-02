# Project Roadmap

프로젝트 로드맵

---

## 현재 상태

> Last Updated: 2026-01-03

**Phase**: Production Ready (Beta)

---

## 완료된 기능

### Core Trading Platform

| 기능 | Coin (Upbit) | Korea Stock (Kiwoom) |
|------|--------------|----------------------|
| Market Data API | ✅ | ✅ |
| Analysis Pipeline (LangGraph) | ✅ | ✅ |
| Real-time WebSocket | ✅ | ✅ |
| Multi-session Support | ✅ | ✅ |
| Trade Execution | ✅ | ✅ |
| Position Management | ✅ | ✅ |
| HITL Approval Flow | ✅ | ✅ |

### Agent System

- ✅ Technical Analyst Agent
- ✅ Fundamental Analyst Agent
- ✅ Sentiment Analyst Agent
- ✅ Risk Assessor Agent
- ✅ Synthesis Agent
- ✅ Agent Group Chat (Backend + Frontend)
- ✅ Position Manager

### Trading System

- ✅ Execution Coordinator
- ✅ Portfolio Agent
- ✅ Order Agent
- ✅ Risk Monitor (Stop-Loss/Take-Profit)
- ✅ Trade Queue Management
- ✅ Market Hours Service

### Notifications

- ✅ Telegram Integration
- ✅ WebSocket Trade Notifications
- ✅ Real-time Toast UI

### UI/UX

- ✅ Analysis Dashboard
- ✅ Trading Dashboard
- ✅ Agent Chat Dashboard
- ✅ AgentWorkflowGraph Visualization
- ✅ Market Status Banner
- ✅ Watch List Widget
- ✅ Background Scanner Widget
- ✅ i18n (Korean/English)

---

## 진행 중

### P1: 장중 테스트 (운영 검증)

**상태**: 대기 (장 시간 필요)

| 항목 | 현재 상태 |
|------|-----------|
| 호가 조회 API | 장마감으로 미검증 |
| 매수/매도 주문 실행 | 코드 검증만 완료 |
| 체결 확인 | 실거래 테스트 필요 |
| Stop-Loss/Take-Profit 트리거 | 실시간 테스트 필요 |

---

## 계획된 기능

### P3: Live Trading 전환

**상태**: 대기 (모의투자 검증 후)

**전환 절차**:
```bash
# .env 파일
KIWOOM_IS_MOCK=false  # 실거래 활성화
```

**체크리스트**:
- [ ] 모의투자 10회+ 매매 성공
- [ ] Stop-Loss/Take-Profit 자동실행 검증
- [ ] 예외 상황 처리 확인

---

### P4: 코드 품질 개선

**상태**: 낮은 우선순위

**작업 항목**:
- [ ] Pydantic V2 ConfigDict 마이그레이션
- [ ] datetime.utcnow() → datetime.now(UTC)
- [ ] regex → pattern 변경

---

### P5: OpenDART 전자공시 연동

**상태**: 보류 (API 키 발급 대기)

**계획 기능**:
- [ ] OpenDART API 클라이언트
- [ ] 재무제표 데이터 조회
- [ ] 공시 알림 기능
- [ ] Fundamental Analysis 강화

---

## 향후 로드맵

### Phase 1: 안정화 (현재)

- 운영 테스트 완료
- 버그 수정
- 성능 최적화

### Phase 2: 기능 확장

- 미국 주식 지원
- 백테스팅 시스템
- 포트폴리오 리밸런싱

### Phase 3: 고급 기능

- 멀티 계좌 지원
- 전략 마켓플레이스
- 모바일 앱

---

## 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|------|------|-----------|
| 0.1.0 | 2025-12-28 | 초기 릴리즈 |
| 0.2.0 | 2025-12-29 | Kiwoom API 연동 |
| 0.3.0 | 2025-12-30 | Auto-Trading 기반 |
| 0.4.0 | 2025-12-31 | Telegram, Watch List, Scanner |
| 0.5.0 | 2026-01-02 | Agent Group Chat |
| 0.6.0 | 2026-01-03 | WebSocket 알림, 문서화 |

---

## 기여 방법

자세한 기여 가이드는 [Contributing](contributing.md)을 참조하세요.
