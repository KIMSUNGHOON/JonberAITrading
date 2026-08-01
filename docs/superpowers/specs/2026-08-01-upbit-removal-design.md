# Upbit(코인) 스택 제거 설계

**작성일**: 2026-08-01
**상태**: 승인됨 (설계 확정, 구현 대기)
**선례**: R2 US/yfinance 스택 제거 (2026-07-11) — `9effca3` 동결 → `3cf6743` 백엔드 → `570f5e1` 프론트

## 문제

Upbit 코인 스택이 **한 번도 쓰인 적 없는 채로** 코드베이스의 상당 부분을 차지하고 있다.
API 키에 현재 IP가 등록돼 있지 않아 조회는 401로 실패하고, 그 실패가 화면과 콘솔에
상시 노출된다. 유지비만 있고 산출이 없다.

## 실측

### 코인 전용 코드 ≈ 10,760 LOC

| 영역 | LOC |
|---|---|
| `backend/services/upbit` + `backend/app/api/routes/coin` | 3,269 |
| `backend/app/api/schemas/coin.py` + `backend/agents/graph/coin_*.py` | 2,533 |
| 백엔드 코인 테스트 7파일 | 3,362 |
| `frontend/src/components/coin` 외 코인 전용 파일 | 1,596 |

흩어진 참조: `upbit`를 언급하는 백엔드 파일 37개, `coin`/`upbit`를 언급하는 프론트 파일 68개,
`MarketType.COIN` 참조 28곳.

### 데이터는 전부 비어 있다

`coin_positions` 0행, `coin_trades` 0행, `coin_realized_pnl` 0행, `sessions` 0행.
**코인 매매는 한 번도 일어나지 않았고, 저장된 값 중 `coin`·`stock`을 들고 있는 행도 없다.**
따라서 열거형에서 멤버를 빼도 깨질 기존 레코드가 없다.

### 라이브 매매 경로의 코인 결합은 0이다

이것이 이 아크의 위험도를 결정한다.

```
0   services/trading/coordinator.py
0   services/agent_chat/coordinator.py
0   services/agent_chat/position_manager.py
2   agents/graph/graph_factory.py
13  services/session_manager.py
3   app/api/routes/websocket.py
3   services/autonomy/gate.py
```

실제 주문·손절·포지션 관리 경로는 코인을 아예 모른다. 결합은 위 네 파일에 갇혀 있다.
`services/trading/market_hours.py`의 `MarketType.CRYPTO`·`NYSE`는 **자기 파일 밖 사용처가 0**이라
이미 죽은 코드다.

`autonomy/gate.py`가 유일하게 라이브 안전 경로에 걸린다 — `market == "coin"` 분기 3곳이며,
그중 하나는 코인 브레이커가 애초에 비활성이라는 주석을 달고 0을 반환한다
(`coin_trades`에 pnl 컬럼이 없어서). 즉 제거해도 잃는 방어가 없다.

## 원칙

**동결은 되돌릴 수 있게, 제거는 되돌릴 필요 없게.**

다만 동결을 *관측 기간*으로 쓰지는 않는다. 이 시스템은 장외에 완전 idle이라
주말 내내 동결 상태로 둬도 감시·토론·손절이 한 번도 돌지 않는다 — 라이브 경로에 대해
아무것도 증명하지 못하는 관측은 근거 없는 안심일 뿐이다.
**동결은 커밋 경계(되돌림 단위)로만 남기고, 세 단계를 주말에 모두 배포한다.**
검증은 월요일 개장이 맡는다.

## 범위

### 1단계 — 동결

**코인 구현 코드는 그대로 두고 진입점만 끊는다.** 삭제는 배선 3곳에 한정한다.

- `backend/app/main.py`의 `_API_ROUTERS`에서 `(coin.router, "coin", "Coin")` 한 줄 제거 →
  `/api/coin/*`·`/api/v1/coin/*`가 404가 된다. `routes/coin/` 자체는 남는다.
- `frontend/src/components/terminal/TerminalShell.tsx:36-38`의 `MARKETS`에서
  `{ id: 'coin', label: 'COIN' }` 제거 → 상단 시장 토글에서 COIN이 사라진다.
- `frontend/src/pages/PositionsPage.tsx`의 Crypto Positions 섹션과
  `CoinMarketDashboard` 렌더를 제거한다.

`components/coin/`·`services/upbit/`·코인 그래프는 이 단계에서 손대지 않는다.
코인 폴링이 멈추므로 **Upbit 401 콘솔 에러가 사라진다.**

검증: 라이브 KR 경로 무영향, 재시작 후 로그에 `no_authorization_ip` 0건.

### 2단계 — 백엔드 제거

삭제: `backend/services/upbit/`, `backend/app/api/routes/coin/`,
`backend/app/api/schemas/coin.py`, `backend/agents/graph/coin_trading_graph.py`,
`coin_state.py`, `coin_nodes.py`, 코인 테스트 7파일.

`services/session_manager.py`의 `MarketType`에서 **`COIN`과 `STOCK`을 함께 제거**해
`KIWOOM` 하나만 남긴다. `STOCK`은 R2가 US 스택을 걷어내며 남긴 잔재다.

결합 정리: `graph_factory.py`(코인 그래프 선택), `session_manager.py`,
`app/api/routes/websocket.py`, `services/autonomy/gate.py`(`market == "coin"` 분기 3곳).

`services/trading/market_hours.py`의 `MarketType.CRYPTO`·`NYSE`도 제거한다 — 사용처 0.

`storage_service.py`에서 코인 테이블의 `CREATE TABLE`과 접근자를 제거한다.
**기존 빈 테이블은 DROP하지 않고 그대로 둔다** — 라이브 DB에 마이그레이션을 돌리는 위험이
0행 테이블 3개를 없애는 값어치보다 크다. 재생성만 막으면 충분하다.

### 3단계 — 프론트 제거

삭제: `frontend/src/components/coin/` 8파일, `frontend/src/hooks/useCoinTicker.ts`,
`frontend/src/components/dashboard/CoinMarketDashboard.tsx`.

스토어의 코인 슬라이스와 `activeMarket` 기반 위임(`store/index.ts:1689-1701`)을 걷어낸다.

`frontend/src/types/index.ts`의 `MarketType`은 `'coin' | 'kiwoom'`에서 **`'kiwoom'` 단일
유니온**이 된다. `market` 파라미터와 라우트 모양은 그대로 유지한다 — 추상화를 붕괴시키지 않는다.

## 명시적 제외

**US 크로스마켓 신호(`US_SIGNAL_*`)** — 이름만 비슷할 뿐, 간밤 미 반도체 시세(SMH/MU/NVDA)로
국내 AI 밸류체인을 판단하는 별개 기능이고 지금도 살아 있다. **건드리지 않는다.**

**`.env`의 `UPBIT_ACCESS_KEY`·`UPBIT_SECRET_KEY`** — 사용자 소유 gitignored 파일이라
직접 수정하지 않는다. 3단계 완료 후 수동 제거를 안내한다. `.env.example`에서는 제거한다.

**기존 빈 `coin_*` 테이블** — 남긴다(위 참조).

**`market` 파라미터·라우트 시그니처의 단일화** — `MarketType`을 한 멤버로 줄이되
파라미터 자체는 유지한다. 붕괴시키면 거의 모든 라우트·스토어·컴포넌트를 건드려야 해
범위와 라이브 위험이 함께 커진다.

## 검증

| 대상 | 검증 |
|---|---|
| 1단계 라우트 | `/api/coin/*`가 404, `/api/trading/*`·`/api/kr_stocks/*`는 정상 |
| 1단계 콘솔 | 재시작 후 `no_authorization_ip` 로그 0건 |
| 2단계 열거형 | `MarketType`에 `KIWOOM`만 남고, import 실패·`AttributeError` 0 |
| 2단계 브레이커 | `autonomy/gate.py`의 KR 경로(일일 손실·포지션 수)가 코인 분기 제거 후에도 동일하게 동작 |
| 2단계 DB | 기존 `coin_*` 테이블은 그대로 있고, 새 DB에서는 생성되지 않는다 |
| 3단계 타입 | `npx tsc --noEmit` 0 오류 |
| 전 단계 | 백엔드·프론트 전체 스위트. 실패는 개수가 아니라 **분기점에서 개별 재현**으로 사전 존재를 증명한다 |
| 라이브 | 월요일 개장 후 KR 매매 루프(감시·토론·손절) 정상 동작 |

## 배포 창

세 단계를 **각각 별도 커밋**으로 남기되(되돌림 단위), 배포는 **월요일 개장 전 1회**다.
지금은 토요일이라 장중도 EOD 발굴 창(15:30~16:35)도 아니다.
문제가 생기면 3단계 전체가 아니라 해당 커밋만 되돌린다.
