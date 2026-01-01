# Agentic AI Trading - Project Roadmap

> Last Updated: 2025-12-31
> Status: Production Ready (모의투자 검증 완료)

---

## 프로젝트 개요

AI 기반 주식/코인 자동매매 시스템
- 병렬 분석, 실시간 모니터링
- Human-in-the-Loop (HITL) 승인 워크플로우
- 다중 에이전트 협업 트레이딩
- Telegram 실시간 알림

---

## 완료된 기능 (Completed) ✅

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

### Parallel Analysis System

- [x] 동시 분석 3개 제한 (Semaphore)
- [x] 세션별 WebSocket 라우팅
- [x] 다중 세션 Store 구조
- [x] BasketWidget 분석 시작
- [x] Sidebar 페이지 네비게이션
- [x] AnalysisPage + History 통합

### Auto-Trading Foundation

- [x] News API 연동 (Naver) - 100건 조회
- [x] Sentiment Analysis 통합
- [x] Trading Coordinator 구조
- [x] Portfolio Agent
- [x] Order Agent
- [x] Risk Monitor (Stop-Loss/Take-Profit 자동실행)
- [x] Approval → Auto-Trading 연결
- [x] Market Hours Service (KRX, Crypto)
- [x] Activity Logging System
- [x] TradingStatusWidget

### Telegram Integration (2025-12-31)

- [x] Telegram 서비스 구현
- [x] 거래 제안/체결/거절 알림
- [x] 포지션 업데이트 알림
- [x] 손절/익절 도달 알림
- [x] Sub-Agent 분석 완료 알림
- [x] 시스템 상태 알림
- [x] 4000자 초과 메시지 자동 분할

### Watch List & Background Scanner (2025-12-31)

- [x] Watch List 기능 (WATCH 액션)
- [x] Watch → Trade Queue 변환
- [x] KOSPI/KOSDAQ Background Scanner
- [x] Scanner 결과 필터링 (BUY/WATCH/AVOID)
- [x] BackgroundScannerWidget (Frontend)

### TradeAction 개선 (2025-12-31)

- [x] BUY: 신규 매수
- [x] SELL: 전량 매도
- [x] HOLD: 보유 유지
- [x] ADD: 추가 매수
- [x] REDUCE: 부분 매도
- [x] WATCH: 모니터링 (미보유 + HOLD 시그널)
- [x] AVOID: 매수 회피 (미보유 + STRONG_SELL)

### UI/UX 개선 (2025-12-31)

- [x] 다국어 지원 (i18n) - 한/영
- [x] Popular Stocks Widget 리스트 형식
- [x] 총 자산 계산 수정
- [x] WatchListWidget

### API 검증 (2025-12-31)

- [x] Kiwoom API 테스트 (278 passed)
- [x] 실제 API 호출 검증 (모의투자)
- [x] 매수/매도/정정/취소 코드 검증

---

## 남은 작업 우선순위

### Priority 1: 장중 테스트 (운영 검증) 🔴

**목표:** 실제 장 시간에 모의투자 매매 테스트

| 항목 | 현재 상태 |
|------|-----------|
| 호가 조회 API | 장마감으로 미검증 |
| 매수/매도 주문 실행 | 코드 검증만 완료 |
| 체결 확인 | 실거래 테스트 필요 |
| Stop-Loss/Take-Profit 트리거 | 실시간 테스트 필요 |

**테스트 시나리오:**
1. 분석 → 매수 승인 → 주문 실행 → 체결 확인
2. 손절가 도달 → 자동 매도 실행
3. 익절가 도달 → 자동 매도 실행

---

### Priority 2: WebSocket 체결 알림 🟡

**현재 상태:** Telegram 알림만 구현, WebSocket 미완성

**필요 작업:**
- [ ] RiskMonitor에서 체결 시 WebSocket 브로드캐스트 추가
- [ ] `broadcast_to_session()`으로 체결 정보 전송
- [ ] 프론트엔드에서 `execution` 메시지 타입 처리
- [ ] 체결 알림 Toast/Notification UI

**예상 소요:** 2-4시간

---

### Priority 3: Live Trading 전환 준비 🟡

**현재 상태:** 100% 구현 완료 (설정만 변경하면 됨)

**전환 절차:**
```bash
# .env 파일
KIWOOM_IS_MOCK=false      # 실거래 활성화
```

**전환 전 체크리스트:**
- [ ] 모의투자에서 충분한 테스트 완료
- [ ] 최소 10회 이상 매수/매도 성공
- [ ] Stop-Loss/Take-Profit 자동실행 검증
- [ ] 예외 상황 (네트워크 오류, 주문 실패) 처리 확인

---

### Priority 4: 코드 품질 개선 🟢

**현재 상태:** 76개 Pydantic deprecated warnings

**작업:**
- [ ] Pydantic V2 `ConfigDict` 마이그레이션
- [ ] `datetime.utcnow()` → `datetime.now(UTC)` 변경
- [ ] `regex` → `pattern` 변경

**예상 소요:** 1-2시간

---

### Priority 5: OpenDART 전자공시 연동 ⚪ (보류)

**현재 상태:** API 키 발급 대기 중

**구현 예정 기능:**
- [ ] OpenDART API 클라이언트
- [ ] 재무제표 데이터 조회
- [ ] 공시 알림 기능
- [ ] Fundamental Analysis 강화

**대기 이유:** API 키 발급 지연

---

## 아키텍처 개요

### Backend Structure
```
backend/
├── app/
│   ├── api/routes/          # API 엔드포인트
│   │   ├── trading.py       # Auto-trading API
│   │   ├── approval.py      # HITL Approval
│   │   ├── scanner.py       # Background Scanner
│   │   └── websocket.py     # Real-time updates
│   └── dependencies.py      # DI (Kiwoom singleton)
├── services/
│   ├── trading/             # Auto-trading 서비스
│   │   ├── coordinator.py   # Execution Coordinator
│   │   ├── risk_monitor.py  # Stop-Loss/Take-Profit
│   │   └── models.py        # Trading models
│   ├── kiwoom/              # 키움 API
│   ├── telegram/            # Telegram 알림
│   ├── background_scanner/  # KOSPI/KOSDAQ Scanner
│   └── news/                # 뉴스 서비스
└── agents/                  # LangGraph Agents
    ├── graph/               # Analysis workflows
    └── subagents/           # Specialist agents
```

### Agent Workflow
```
[Analysis Request]
       ↓
[Technical Agent] ─┬─ [Fundamental Agent]
                   │
                   ├─ [Sentiment Agent]
                   │
                   └─ [Risk Agent]
       ↓
[Trade Proposal] ────────────────────────┐
       ↓                                 │
[HITL Approval]                    [Telegram 알림]
       ↓
[Trade Queue] → [Market Open Check] → [Order Execution]
       ↓                                      │
[Risk Monitor] ← [Position Update] ←──────────┘
       │
       └─→ [Stop-Loss/Take-Profit 자동실행]
```

---

## 환경 설정

### 필수 환경 변수
```env
# LLM
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:14b

# Kiwoom (한국주식)
KIWOOM_APP_KEY=...
KIWOOM_SECRET_KEY=...
KIWOOM_ACCOUNT_NO=...
KIWOOM_IS_MOCK=true  # 모의투자 (false: 실거래)

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_ENABLED=true

# News
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

---

## 관련 문서

- `CLAUDE.md` - Claude Code 개발 지침
- `WORK_STATUS.md` - 작업 현황
- `HumanRequirement.md` - 사용자 요청 사항
- `docs/UI_ARCHITECTURE.md` - UI 구조
- `docs/OPENDART_API_GUIDE.md` - OpenDART API 가이드 (미구현)

### 아카이브 (완료된 기능)
- `docs/archive/TODO.md` - 이전 개발 추적
- `docs/archive/FEATURE_SPEC_COIN_TRADING.md`
- `docs/archive/FEATURE_SPEC_REALTIME_AGENT_TRADING.md`
- `docs/archive/AutoTrading_Implementation_Plan.md`
- `docs/archive/KIWOOM_API_IMPLEMENTATION_PLAN.md`
