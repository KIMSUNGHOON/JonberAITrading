# R5-P0: 자동매매 안전 수정 (2026-07-13)

자동매매 모델 감사(`2026-07-12-autotrade-model-audit.md`)의 **실주문 차단급** 발견 중
Phase C(장중 스모크) 이전 필수 수정분. "자율 매수는 강하고 자율 방어는 약하다"는
패턴에서 방향 반전·게이트 우회·큐 수량 유실 세 결함을 봉합한다. B5(현금 10000% 이중
곱)는 R5-P2 `2a4f385`에서 이미 해결됨(백엔드가 % 반환 — FE ×100 제거)이라 제외.

TDD: 6개 테스트 선작성(RED 4 + 가드 2) → 구현(GREEN) → 회귀 → 적대적 리뷰.
테스트: `backend/tests/test_services/test_r5_p0_autotrade_safety.py`

## A1 — ADD 결정이 SELL 주문으로 반전

**근본 원인**: `on_trade_approved`의 side 매핑 3개 사이트가
`OrderSide.BUY if action == "BUY" else OrderSide.SELL`. `action`이 "ADD"면
"BUY"가 아니므로 **SELL로 반전** → 자율 추가매수가 청산으로 실행.
호출 경로: `agent_chat/coordinator.py:471`(DecisionAction.ADD→"ADD") →
`on_trade_approved(action="ADD")` → line 348.

**수정**: 단일 진실 소스 헬퍼 도입.
```python
_BUY_SIDE_ACTIONS = {"BUY", "ADD"}
def _order_side_for_action(action: str) -> OrderSide:
    return OrderSide.BUY if action in _BUY_SIDE_ACTIONS else OrderSide.SELL
```
게이트의 `POSITION_INCREASING_ACTIONS`와 의미적으로 일치(side·cap 논리 정합).
3개 사이트(큐잉 반환 316, 일일한도 반환 336, 실행 348) 모두 교체. ADD→BUY가 되면
체결 후 `_add_position`(평단 average-in)이 올바르게 실행됨.

## A2 — PositionManager 청산이 autonomy 게이트 우회

**근본 원인**: `PositionManager._execute_close_position`가
`trading_coord._close_position()` 직행. 오펜시브 매수 경로
(`agent_chat/coordinator.py:_handle_decision`)는 `check_autonomy`를 통과하지만
방어(청산) 경로는 게이트 없이 발주. 4개 호출(stop_loss/take_profit 자동청산 +
agent_decision SELL/REDUCE-full-close)이 이 단일 초크포인트를 지남.

**수정**: `_execute_close_position`가 브로커 호출 전
`check_autonomy("kiwoom", action="SELL", ...)`를 먼저 검사.
- 거부 시: 발주하지 않고 return, **포지션은 감시 유지**(수동 조치 가능),
  best-effort 텔레그램 통지(`_notify_close_gate_denied`).
- 허용 시: 기존대로 청산 + 감시 해제.

**의도된 동작 변화(한계, R5-P4 후보)**: 게이트의 daily-loss 브레이커(step 4)는
SELL에도 적용되므로, 당일 실현손실 한도 초과 시 자율 손절/익절도 차단된다
("로봇 정지 → 사람 호출" 철학). 방어 SELL을 브레이커에서 예외 처리할지는 R5-P0
범위 밖(감사 C5 "브레이커는 실현손익만"과 연결). market="kiwoom" 하드코딩은
오펜시브 경로와 동일(agent-chat=KR 전용).

**리뷰가 잡은 후속 수정(통지 스로틀)**: 적대적 리뷰(2 CONFIRMED)가 확증 —
auto_execute 모드에서 `STOP_LOSS_HIT`/`TAKE_PROFIT_HIT`는 de-dup되지 않아 매
감시 주기 재발화하고, 게이트가 지속 거부하면 포지션이 감시에 남아
`_notify_close_gate_denied`가 매 주기(기본 30s) 텔레그램을 보낸다(게이트 자신의
`_notify_breaker`는 하루 1회 스로틀). 수정: `MonitoredPosition.close_gate_denied_notified`
플래그로 **거부 에피소드당 1회만** 통지, 게이트가 다시 허용하면 래치 해제.
청산 재시도 자체는 유지(게이트 재개 시 자동 청산 복구). 반복 게이트 체크의
브로커 호출 churn은 R5-P0 범위 밖 효율 nit로 잔존.

## A5 — 큐잉된 자율 BUY/ADD의 수량 유실

**근본 원인**: `add_to_queue`에 `quantity` 파라미터 없음 →
`QueuedTrade.quantity=None`. `process_trade_queue`의 실행 시점 재게이트가
`check_autonomy(quantity=None)` → gate step 6
`if quantity is None: _deny("notional_cap", "quantity/entry_price unknown")` →
**모든 자율 BUY/ADD 100% 취소**.

**수정**: `add_to_queue(..., quantity: Optional[int] = None)` 추가 →
`QueuedTrade.quantity`에 저장. `on_trade_approved` 큐잉 분기에서
`quantity=quantity_override` 전달. 재게이트가 실제 수량으로 notional cap 평가.

**완결성**: `on_trade_approved(autonomous=True)`는 오직 챗 코디네이터
(`agent_chat/coordinator.py:478`)에서만 호출됨(분석 auto-approve injector는
LangGraph 실행자를 쓰므로 이 큐를 거치지 않음). 오펜시브 게이트가 None-수량
BUY/ADD를 사전 차단하므로, 큐잉되는 자율 BUY/ADD는 항상 수량이 있음.
비자율 WATCH→큐 변환은 quantity 생략(기본 None) — 실행 시 할당 계산이라 무해.

## 검증

- 신규 테스트 7/7 (A1: ADD→BUY / REDUCE→SELL, A5: add_to_queue 저장 /
  재게이트 수량 보존, A2: 거부 시 미실행+감시유지 / 허용 시 청산 /
  거부 반복 시 1회 통지).
- 회귀: autonomy_gate + agent_chat 188 pass, position_manager+models 50 pass,
  영향 test_api 25 pass, test_services 전체 581 pass(+pre-existing kiwoom
  cache/rate-limiter 3건 — 변경 stash로 pre-existing 확인).
- 적대적 리뷰 워크플로(4차원 리뷰 → 발견 반박 검증): 6건 raise → 2 CONFIRMED
  (동일 근본원인=통지 스팸, 봉합) + 4 REFUTED(의도된 설계/pre-existing/도달불가).

## 잔여(R5-P1 이후)

A3 체결 확인 루프, A4 영속화(큐/스탑/포지션 → SQLite), 개장 큐 자동 처리
스케줄러, 매도 실패 시 포지션 유지, 브레이커 미실현 손실/방어-SELL 예외(R5-P4).
