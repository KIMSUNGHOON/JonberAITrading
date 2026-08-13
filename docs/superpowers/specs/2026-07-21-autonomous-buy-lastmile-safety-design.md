# 자율 BUY 라스트마일 안전 패치 — 설계

**작성일**: 2026-07-21
**아크**: 자율 BUY 실행경로 HIGH 버그 봉합 (H1 has_position fail-closed + H3 즉시체결 이중엔진 등록 + H2 사이징 캡 클램프)
**선행**: [[session-2026-07-21-discovery-manual-trigger]] — BUY 실행경로 감사 workflow(wf_df9e7bcc)가 사상 미발현 경로에서 HIGH 버그 3을 발견. 목표=버그 없는 상태에서 첫 자율 BUY를 신뢰성 있게 실증.

---

## 1. 문제 (workflow 감사 확정, file:line)

자율 매매에서 워치리스트 종목의 BUY 합의가 나면 `_handle_decision → check_autonomy → on_trade_approved → 체결 → 포지션 등록`으로 가야 하는데, **BUY 투표가 사상 0건**이라 이 라스트마일이 실전 발현된 적이 없다. 감사가 발견한 HIGH 버그:

- **H1 (has_position fail-open)**: `services/agent_chat/coordinator.py:1153-1176` `_fetch_market_context`가 Kiwoom `get_account_balance()` 실패 시 `except`에서 warning만 남기고 `has_position=False`·`available_cash=None`을 그대로 둔다. 계좌조회 장애(레이트리밋/토큰만료 — 실제 선례 있음) 순간, **보유 중인 종목도 has_position=False로 판정** → `vote_to_action(bullish, has_position=False)`가 ADD 대신 **BUY(중복 신규매수)** 반환.
- **M1 (H1과 동일 지점)**: 같은 except로 `available_cash=None` → moderator quantity 산정 불가(None) → 게이트가 `notional_cap: quantity 불명`으로 정상 합의를 폐기(`services/agent_chat/agents/moderator_agent.py:394-396`, `services/autonomy/gate.py:351-353`). 재시도/폴백 없음.
- **H3 (즉시체결 PositionManager 미등록)**: `services/trading/coordinator.py:962-976` 즉시체결 branch가 수동 `ManagedPosition(...)`+`self._add_position(position)`만 호출(=RiskMonitor+영속). **pending/partial branch(`:3240`)가 쓰는 `register_fill_as_position`을 호출하지 않아 agent-chat PositionManager에 미등록** → PM의 30s 손절/트레일링/전략재평가가 그 포지션엔 안 돎. "이중엔진"이 즉시체결엔 거짓.
- **H2 (사이징 캡 우회)**: `services/trading/coordinator.py:632-635` `quantity_override`가 `portfolio_agent.calculate_allocation`의 결과(allocation.quantity)를 **통째 덮어씀** → R-사이징·min_cash·max_stock 캡 우회, 게이트의 flat `notional_cap`만 실효 방어.

**정직한 판정**: BUY 실행 뒷half(주문→ka10076 체결→ManagedPosition→RiskMonitor 손절→SQLite 영속→재시작 복원)는 검증됨(000660 자동손절 선례). 앞half(합의→사이징→게이트→체결)는 위 버그로 첫 실전 BUY에서 오작동/누락 위험. workflow 최소기준: `/trading/start` 기동(완료) + **H1·H3 패치**.

---

## 2. 목표

자율 BUY 라스트마일의 HIGH 안전버그(H1·H3)와 인접 버그(M1·H2)를 봉합해, 첫 자율 BUY가 **(1)보유종목 중복매수 없이 (2)사이징 캡을 준수하며 (3)양 감시엔진에 등록되어 손절이 실제 작동**하도록 만든다. 그 위에서 통제된 방식으로 첫 자율 BUY를 실증한다.

**비목표**: consensus_threshold(0.75)·문턱·에이전트 보수성 등 판단 기준 완화(이 아크는 안전을 강화하지 완화하지 않는다). L1(entry_price=0 zerodiv)·L2(무조건 성공통지)·M2(/trading/start 전제)·M3(전략부재 시 포지션캡)는 후속 백로그(비차단).

---

## 3. 설계

### H1(+M1) — 계좌조회 실패 시 coordinator 권위상태 폴백 (`agent_chat/coordinator.py:1153-1176`)

`_fetch_market_context`의 Kiwoom 계좌조회 `except` 블록에서, warning만 남기고 fail-open하는 대신 **ExecutionCoordinator의 권위 in-memory 상태로 폴백**한다:

- `from app.dependencies import get_trading_coordinator`(이 모듈이 이미 :582,:866에서 쓰는 관용구) → `trading_coord = await get_trading_coordinator()`.
- **has_position**: `trading_coord._state.positions`(list[ManagedPosition])에서 `p.ticker == ticker` 검색 → 있으면 `has_position=True`, `position_quantity=p.quantity`, `position_avg_price=p.avg_price`, `position_pnl_pct=p.unrealized_pnl_pct`.
- **available_cash/total_portfolio**: `trading_coord._state.account`(AccountInfo)에서 `available_cash=acct.available_cash`, `total_portfolio=acct.total_equity`.
- Kiwoom 성공 시엔 기존대로 Kiwoom 값 사용(폴백은 실패 경로에서만). 폴백도 실패(사실상 in-memory라 불가)하면 has_position/available_cash를 **신규 BUY가 성립하지 않는 안전값**으로 둔다: available_cash=None 유지 시 게이트가 어차피 BUY를 거부(fail-closed 자연 성립) — 즉 "모르면 안 산다".
- 로그: 폴백 사용 시 `market_context_account_fallback`(ticker, has_position, source='coordinator_state')로 관측성 확보.

**효과**: H1(보유종목 중복 BUY) 봉합 — 계좌조회 실패해도 coordinator가 추적하는 포지션으로 has_position 정확 판정 → bullish는 ADD로 라우팅. M1(정상합의 폐기) 봉합 — available_cash 폴백으로 quantity 산정 가능. **한계(수용)**: coordinator가 추적하지 않는 외부생성 포지션은 폴백도 모름(자율 시스템이 전 포지션을 생성하므로 실질 무해).

### H3 — 즉시체결 이중엔진 등록 (`trading/coordinator.py:962-976`)

즉시체결 branch(`result.filled_quantity > 0 and side == OrderSide.BUY`)의 수동 `ManagedPosition(...)`+`self._add_position(position)`을 **pending branch(:3240)와 동일한 `register_fill_as_position(self, ...)` 호출로 교체**:

```python
await register_fill_as_position(
    self,
    ticker=ticker,
    stock_name=stock_name or ticker,
    quantity=result.filled_quantity,   # 증분 체결 수량(헬퍼 계약)
    avg_price=result.avg_price,
    stop_loss=stop_loss,
    take_profit=take_profit,
    session_id=session_id,
    source="placement_fill",
    stop_loss_mode=self.risk_params.stop_loss_mode,
    risk_score=risk_score,
)
```

`register_fill_as_position`은 `coordinator._add_position`(RiskMonitor+영속, 기존과 동일) **+ PositionManager 미러 등록(best-effort, never-raise, PM 미기동이면 스킵)**을 모두 수행한다 → 즉시체결에도 이중엔진 실현.

**검증 필수(구현/리뷰)**: (a) 교체 후 `position` 지역변수를 이후 코드(활동로그 등)가 참조하지 않는지 — 참조하면 `register_fill_as_position`가 등록한 포지션을 재조회하거나 활동로그를 filled_quantity 기반으로 유지. (b) 즉시체결분이 `_poll_tracked_fills` 재폴 대상이 아님을 확인(이중등록 방지) — 현재도 `_add_position`을 즉시체결에서 호출하는데 이중이 안 나는 것과 동일 근거.

### H2 — quantity_override 캡 클램프 (`trading/coordinator.py:632-635`)

```python
if quantity_override and quantity_override > 0:
    allocation.quantity = quantity_override        # ← 캡 우회
    allocation.estimated_amount = quantity_override * entry_price
```

를, **allocation의 캡(calculate_allocation이 산정한 상한)으로 클램프**한다: `clamped = min(quantity_override, allocation.quantity)`(allocation.quantity가 캡 역할). override가 캡 이하면 그대로, 초과면 캡으로 제한. estimated_amount·rationale도 clamped 기준으로 갱신하고, 클램프 발생 시 로그. → 모더레이터 사이징 의도 존중하되 R-사이징/min_cash/max_stock 캡 준수. (calculate_allocation이 quantity=0을 반환하는 경우=진입 불가이므로 override도 0으로 클램프되어 발주 안 됨 — 안전.)

---

## 4. Global Constraints (모든 태스크 공통)

- **안전 강화 방향만**: 판단 문턱(consensus 0.75)·게이트·에이전트 보수성은 건드리지 않는다. 이 아크는 fail-open→fail-closed, 캡 우회→캡 준수, 단일엔진→이중엔진으로 **더 안전**하게만 바꾼다.
- **fail-closed 원칙**: 상태(has_position/cash)를 모르면 신규 BUY가 성립하지 않는 쪽으로 귀결.
- **never-raise 유지**: 폴백·등록 실패는 로그만, 예외 전파 금지(register_fill_as_position는 이미 never-raise).
- **이중엔진 대칭**: 즉시체결 등록이 pending체결 등록과 동일 의미(register_fill_as_position 공용).
- **실 LLM/네트워크 금지**: 테스트는 Kiwoom client·PositionManager를 스텁/mock.
- **paper 전용**: 라이브 실증은 paper 모드(paper_only 게이트가 강제).

## 5. 테스트

- **H1**: `_fetch_market_context`에서 Kiwoom `get_account_balance`가 예외 → `trading_coord._state.positions`에 해당 ticker 있으면 has_position=True·수량/평단 반영, account에서 available_cash 폴백. ticker 미보유면 has_position=False + available_cash는 coordinator account 값. (실 네트워크 없이 client·trading_coord 스텁.)
- **M1**: 위 폴백으로 available_cash가 None이 아니게 되어 이후 quantity 산정이 가능함(모더레이터 경로 단위 또는 컨텍스트 값 검증).
- **H3**: 즉시체결 branch가 `register_fill_as_position`을 호출(호출 인자 검증) → coordinator._add_position + PositionManager.update_position 양쪽 등록. PM 미기동 시 스킵·never-raise. 이중등록 없음.
- **H2**: quantity_override > allocation.quantity(캡) → clamped=cap. override ≤ cap → override 그대로. allocation.quantity==0 → clamped 0(발주 안 됨).
- **회귀**: 기존 agent_chat/trading/execution 스위트 green. 특히 pending체결 등록·기존 즉시체결 RiskMonitor 등록·정상 계좌조회 경로 불변.

## 6. 배포 후 실증 (운용)

1. 재배포(재시작) 후 **통제 테스트 BUY**: `/trading/queue/add`로 소액(1주 규모) paper BUY 주입 → process → 즉시체결 → **H3 검증**: RiskMonitor(기존) + PositionManager(신규) 양쪽에 포지션 등록됨을 `/agent-chat/positions`(PM)와 `/trading/positions`(coordinator)로 교차 확인. 이후 청산(정리).
2. **segment1(실제 4에이전트 BUY 합의)**: 강한 후보 자연 출현 또는 seeded 강한 paper 후보로 워치→토론→BUY 합의→(패치된)사이징→체결→이중엔진 포지션 종단 실증. 첫 진짜 자율 BUY = 이 순간. (에이전트 보수성은 불변이므로 강한 후보 필요.)

## 7. 파일 요약

- `services/agent_chat/coordinator.py` — `_fetch_market_context`(1153-1176, H1/M1 폴백).
- `services/trading/coordinator.py` — 즉시체결 branch(962-976, H3 register_fill_as_position 교체) + quantity_override(632-635, H2 클램프).
- 테스트: `tests/test_services/test_agent_chat/*`(H1/M1 컨텍스트), `tests/test_services/*`(H3 등록·H2 클램프).

관련: [[session-2026-07-21-discovery-manual-trigger]]
