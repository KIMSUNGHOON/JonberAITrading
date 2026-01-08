# Work Status - JonberAITrading

> Last Updated: 2026-01-03
> Branch: `claude/read-trading-prompt-dgm5U`

---

## 🔥 현재 우선순위

| Priority | 작업 | 상태 | 설명 |
|----------|------|------|------|
| **P0** | Agent Group Chat Frontend | ✅ 완료 | 기본 UI + 시장 상태 UI 개선 |
| P1 | 장중 테스트 | ⏳ 대기 | 호가/체결/손절익절 검증 |
| **P2** | WebSocket 체결 알림 | ✅ 완료 | 실시간 체결 알림 구현 |
| P3 | Live Trading 전환 | ⏳ 대기 | 모의투자 검증 후 |
| P4 | 코드 품질 개선 | 🟢 낮음 | Pydantic deprecated 수정 |
| **Docs** | ReadTheDocs 문서화 | ✅ 완료 | MkDocs + Material 테마 |

---

## 📋 P0: Agent Group Chat Frontend

**현재 상태:** 기본 UI 구현 완료 (진행중)

#### 완료된 컴포넌트
- [x] API 클라이언트 함수 (agent-chat 엔드포인트)
- [x] AgentChatDashboard - Coordinator 상태, 시작/중지
- [x] ChatSessionList - 진행 중/완료된 토론 목록
- [x] ChatSessionViewer - Agent 간 대화 표시 (WebSocket 실시간 + Polling 폴백)
- [x] Sidebar/Navigation에 Agent Chat 메뉴 추가
- [x] useAgentChatWebSocket hook - 실시간 업데이트
- [x] PositionMonitor - 포지션 모니터링 및 이벤트 표시

#### 추가 필요 작업
- [ ] AgentChatSettings - 상세 설정 UI

#### 파일 구조
```
frontend/src/components/agent-chat/
├── index.ts                   # 컴포넌트 export
├── AgentChatDashboard.tsx     # 메인 대시보드, 시작/중지
├── ChatSessionList.tsx        # 세션 목록
├── ChatSessionViewer.tsx      # 토론 내용 뷰어 (WebSocket 실시간)
└── PositionMonitor.tsx        # 포지션 모니터링 및 이벤트

frontend/src/hooks/
└── useAgentChatWebSocket.ts   # WebSocket 연결 관리 hook
```

---

## ✅ 완료된 작업 (Git History 기준)

### 2026-01-03

#### ReadTheDocs 문서화

**구현 내역:**
- MkDocs + Material 테마 설정
- ReadTheDocs 배포 설정 (.readthedocs.yaml)
- 전체 문서 구조화 및 23개 문서 작성

| 카테고리 | 문서 |
|----------|------|
| Getting Started | installation, quick-start, configuration |
| Architecture | overview, agents, trading-system |
| User Guide | analysis, trading, agent-chat, notifications |
| API Reference | overview, analysis, trading, websocket, kiwoom |
| Development | contributing, testing, roadmap |
| 기타 | changelog |

**파일 구조:**
```
mkdocs.yml                    # MkDocs 설정
.readthedocs.yaml             # ReadTheDocs 설정
docs/
├── index.md                  # 홈페이지
├── requirements.txt          # 문서 빌드 의존성
├── getting-started/          # 시작 가이드
├── architecture/             # 아키텍처
├── user-guide/               # 사용자 가이드
├── api/                      # API 레퍼런스
├── development/              # 개발자 가이드
└── changelog.md              # 변경 이력
```

---

#### P2 WebSocket 체결 알림

**구현 내역:**
- 실시간 체결 알림 WebSocket 시스템 구현
- Telegram 알림과 병행 동작

| 컴포넌트 | 설명 |
|----------|------|
| `/ws/trade-notifications` | WebSocket 엔드포인트 |
| `TradeNotificationManager` | 알림 구독자 관리 |
| `broadcast_trade_executed()` | 체결 알림 브로드캐스트 |
| `broadcast_trade_queued()` | 대기열 추가 알림 |
| `broadcast_trade_rejected()` | 거부 알림 |
| `broadcast_watch_added()` | 관심종목 추가 알림 |
| `useTradeNotifications` hook | 프론트엔드 WebSocket 연결 |
| `TradeNotificationToast` | 실시간 알림 UI 컴포넌트 |

**파일 구조:**
```
backend/app/api/routes/websocket.py     # TradeNotificationManager + 엔드포인트
backend/app/api/routes/approval.py      # WebSocket 브로드캐스트 호출
frontend/src/hooks/useTradeNotifications.ts  # WebSocket hook (신규)
frontend/src/components/ui/TradeNotificationToast.tsx  # Toast UI (신규)
frontend/src/App.tsx                    # 전역 알림 통합
```

---

#### P0.2 장 마감 시 매매 과정 UI/UX 개선

**문제점:**
- 장 마감 시 TradeQueue/Approval에서 매매 실행 시점이 불명확
- 사용자가 현재 장 상태를 알기 어려움

**구현 내역:**

| 컴포넌트 | 설명 |
|----------|------|
| `GET /api/trading/market-status` | 시장 상태 API + countdown_seconds |
| `useMarketHours` hook | 실시간 카운트다운 관리 |
| `MarketStatusBanner` | 장 상태 + 카운트다운 배너 |
| `ApprovalDialog` 개선 | 장 마감 시 경고 + 예상 실행 시간 |
| `TradeQueueWidget` 개선 | 장 상태 표시 + 실행 순서/시간 |

**파일 구조:**
```
backend/app/api/routes/trading.py      # GET /market-status 추가
frontend/src/hooks/useMarketHours.ts   # 시장 상태 hook (신규)
frontend/src/components/trading/MarketStatusBanner.tsx  # 시장 상태 배너 (신규)
frontend/src/components/approval/ApprovalDialog.tsx    # 장 마감 경고 추가
frontend/src/components/trading/TradeQueueWidget.tsx   # 실행 시간 표시
frontend/src/types/index.ts            # MarketStatus 타입 추가
frontend/src/api/client.ts             # getMarketStatus() 추가
```

---

### 2026-01-02

#### P0 Agent Group Chat Frontend (구현중)

**Frontend UI 구현:**
- AgentChatDashboard - Coordinator 제어 (시작/중지), 설정, 활성 토론 표시
- ChatSessionList - 세션 목록 (상태, 결정, 합의도 표시)
- ChatSessionViewer - 세션 상세 (메시지, 투표, 결정)
- API 클라이언트 함수 22개 추가 (agent-chat 엔드포인트)
- Sidebar 네비게이션 추가

```
frontend/src/api/client.ts  # API 클라이언트 함수 추가
frontend/src/types/index.ts  # Agent Chat 타입 정의
frontend/src/store/index.ts  # currentView에 'agent-chat' 추가
frontend/src/utils/translations.ts  # 번역 키 추가
```

---

#### `d9be1ef` P0.1 AgentWorkflowGraph + P0.1.1 Trade Queue 중복 종목 처리 개선

**P0.1 AgentWorkflowGraph UI 구현:**
- AgentWorkflowGraph 컴포넌트 - 수직 흐름 그래프 레이아웃
- AgentNode - 클릭 가능한 개별 Agent 노드
- AgentDetailModal - 세부 정보 모달 (거래상세, 분석요약, 결과)
- CSS 기반 커넥터 - Agent 간 연결선 및 애니메이션
- TradingDashboard 통합 - 뷰 토글 기능 (Workflow/Grid)

**P0.1.1 Trade Queue 중복 종목 처리 개선:**
- portfolio_agent.py: 기존 포지션 보유 시 한국어 에러 메시지
- coordinator.py: get_trade_queue(include_all), dismiss_trade() 추가
- trading.py API: /queue?include_all, /queue/{id}/dismiss 엔드포인트
- TradeQueueWidget.tsx: FAILED 상태 UI 개선, Dismiss 버튼

```
frontend/src/components/trading/AgentWorkflowGraph/
├── index.tsx, AgentNode.tsx, AgentDetailModal.tsx, types.ts
backend/services/trading/
├── portfolio_agent.py, coordinator.py
```

---

#### `9ff318a` Phase 6-8: 코드 리팩토링 및 API 버전 관리

**Agent Group Chat Backend (전체 구현):**
```
backend/services/agent_chat/
├── models.py              # AgentMessage, ChatSession, Vote, TradeDecision
├── agents/                # Technical, Fundamental, Sentiment, Risk, Moderator
├── chat_room.py           # 토론 세션 관리
├── coordinator.py         # Watch List 모니터링, 기회 감지
└── position_manager.py    # 포지션 모니터링, 손절/익절 감지

backend/app/api/routes/agent_chat.py  # API 엔드포인트 (1,016줄)
backend/tests/test_services/test_agent_chat/  # 142개 테스트
```

**Agent Group Chat API:**
| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/agent-chat/status` | GET | Coordinator 상태 |
| `/api/agent-chat/start` | POST | 시작 |
| `/api/agent-chat/stop` | POST | 중지 |
| `/api/agent-chat/discuss` | POST | 수동 토론 |
| `/api/agent-chat/sessions` | GET | 세션 히스토리 |
| `/api/agent-chat/positions` | GET | 포지션 목록 |
| `/api/agent-chat/ws/{id}` | WS | 실시간 스트림 |

**코드 리팩토링:**
- kr_stock_nodes 패키지 모듈화 (1,445줄 → 7개 파일)
- 통합 분석 엔드포인트 (`/api/v1/unified-analysis`)
- API 버전 관리 (`/api/v1/*`)

---

### 2025-12-31

#### `5260074` Phase 4: 국제화 (i18n) 지원
- 한/영 다국어 지원
- LanguageProvider, useTranslation hook
- 번역 파일 (ko.json, en.json)

#### `c197aaf` Phase F: 분석 데이터 저장 구조 개선
- AnalysisStorage 클래스
- 분석 결과 영구 저장

#### `e15784b` Phase E: Watch List UI
- WatchListWidget 컴포넌트
- Watch → Trade Queue 변환

#### `7dab9a1` Telegram, Watch List, Background Scanner
- Telegram 알림 서비스 구현
- Watch List 기능 (WATCH 액션)
- KOSPI/KOSDAQ Background Scanner

---

### 2025-12-30

#### `9b7d7c6` Auto-Trading 기본 구조
- Portfolio Agent, Order Agent, Risk Monitor
- TradingStatusWidget
- Execution Coordinator

#### `b6365f2` News API + Auto-Trading 계획
- Naver 뉴스 API 연동 (100건 조회)
- Sentiment Analysis 통합

---

### 2025-12-29

#### `218fe94` Kiwoom 한국 주식 연동
- Kiwoom API 클라이언트
- 모의투자/실거래 전환 지원
- 278개 API 테스트 통과

#### `e2c1f72` Phase 9-10: 기술 지표 시스템
- 기술 지표 계산 시스템
- 분석 데이터 저장

---

## 📚 관련 문서

| 문서 | 설명 |
|------|------|
| `CLAUDE.md` | Claude Code 개발 지침 |
| `mkdocs.yml` | ReadTheDocs 문서 설정 |
| `docs/index.md` | 문서 홈페이지 |
| `docs/getting-started/` | 설치 및 시작 가이드 |
| `docs/architecture/` | 시스템 아키텍처 |
| `docs/user-guide/` | 사용자 가이드 |
| `docs/api/` | API 레퍼런스 |
| `docs/development/` | 개발자 가이드 |

---

## 🔧 환경 설정

```bash
# Backend
conda activate agentic-trading
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev

# LLM (Ollama)
ollama serve && ollama pull deepseek-r1:14b
```
