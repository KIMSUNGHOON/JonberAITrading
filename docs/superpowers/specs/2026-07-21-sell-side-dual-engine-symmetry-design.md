# SELL측 이중엔진 대칭 — 설계

**작성일**: 2026-07-21
**아크**: coordinator-경로 SELL 체결 시 PositionManager 동기(제거/차감) — H3(BUY 등록 이중엔진)의 매도측 짝
**선행**: [[session-2026-07-21-discovery-manual-trigger]] — H3 라이브 실증(통제 테스트 BUY) 청산 과정에서 발견. SELL 후 coordinator 0인데 PositionManager count 1 잔존(수동 `/agent-chat/positions/sync` 필요)으로 실측 확정.

---

## 1. 문제 (라이브 실측 + 코드 확정)

`register_fill_as_position`(position_registration.py:25, 양 감시 엔진 공용 ADD 헬퍼)은 BUY 체결을 **coordinator._add_position(RiskMonitor) + PositionManager.add_position/update_position** 양쪽에 등록한다(H3로 즉시체결도 이 경로). 그러나 **제거/차감 짝이 없다**:

- coordinator-경로 SELL(queue/on_trade_approved → `_apply_sell_fill` → `_apply_sell_position_delta`, 또는 `_poll_tracked_fills`의 SELL 델타 → 같은 `_apply_sell_position_delta`)은 `services/trading/coordinator.py:1557-1561`에서 **coordinator/RiskMonitor에서만** 제거(`_remove_position`)/차감(`position.quantity -= quantity`)하고 **PositionManager는 건드리지 않는다**.
- 결과: SELL 후 PM에 **stale 포지션 잔존**(라이브 실측: coordinator 0, PM count 1). PM의 감시 루프가 이미 청산된 유령 포지션을 계속 감시·관리 대상으로 본다.

즉 이중엔진이 **등록은 대칭(H3), 해제는 비대칭**이다. (연관: R5-P4 매도 체결 배선 백로그.)

**PM측 가용 메서드(확정)**: `PositionManager.remove_position(ticker) -> bool`(멱등: 미보유면 False, 예외 없음), `update_position(ticker, quantity=..., ...)`(절대값 할당). 둘 다 **sync**. `get_chat_coordinator_sync()`(coordinator.py:1613)는 싱글턴만 반환(이벤트루프 연산 없음 → 러닝 루프에서 안전 호출 가능). `_apply_sell_position_delta`도 **sync** 메서드.

---

## 2. 목표

coordinator-경로 SELL 체결(전량/부분)이 coordinator/RiskMonitor를 갱신할 때 **PositionManager도 동일하게 동기**(전량=제거, 부분=잔량으로 갱신)돼, 이중엔진이 **등록·해제 양쪽 대칭**이 된다. 수동 `/positions/sync` 없이 SELL 후 양 엔진이 정합.

**비목표**: PM의 자체 청산 경로(`_close_position`) 변경(이미 PM+coordinator 양쪽 처리), account 스냅샷 staleness(별개), R5-P4의 다른 매도 배선 항목.

---

## 3. 설계

### 신규 헬퍼 `mirror_sell_to_position_manager` (`services/trading/position_registration.py`)

`register_fill_as_position`(등록)의 제거/차감 짝. **sync**(호출부 `_apply_sell_position_delta`가 sync·PM 메서드가 sync이므로):

```python
def mirror_sell_to_position_manager(ticker: str, remaining_quantity: int) -> None:
    """SELL 체결의 PositionManager 미러 — register_fill_as_position(등록)의
    제거/차감 짝. remaining_quantity<=0 → PM.remove_position(전량 청산);
    >0 → PM.update_position(quantity=remaining, 절대값 할당=coordinator 권위
    잔량으로 PM 재동기). PM 미기동(position_manager is None)/미보유면 no-op.
    best-effort never-raise: coordinator 측 재조정은 이미 완료됐으므로 PM
    미러 실패가 SELL 처리를 막으면 안 된다(register_fill_as_position의 PM
    미러가 best-effort인 것과 대칭)."""
    try:
        from services.agent_chat.coordinator import get_chat_coordinator_sync
        pm = get_chat_coordinator_sync().position_manager
        if pm is None:
            return
        if remaining_quantity <= 0:
            pm.remove_position(ticker)
        else:
            pm.update_position(ticker, quantity=remaining_quantity)
    except Exception as e:
        logger.warning(
            "mirror_sell_to_position_manager_failed", ticker=ticker, error=str(e)
        )
```

### `_apply_sell_position_delta` 호출부 배선 (`services/trading/coordinator.py:1557-1561`)

coordinator 측 제거/차감 **직후** PM 미러:

```python
        if quantity >= position.quantity:
            self._remove_position(ticker)
            mirror_sell_to_position_manager(ticker, 0)          # 전량 → PM 제거
        else:
            position.quantity -= quantity
            position.last_updated = datetime.now()
            mirror_sell_to_position_manager(ticker, position.quantity)  # 부분 → 잔량으로 PM 갱신
```

import: `from .position_registration import mirror_sell_to_position_manager`(register_fill_as_position 옆, coordinator.py:45).

**한 지점 수정으로 모든 coordinator SELL 경로 커버**: `_apply_sell_position_delta`는 즉시 SELL(`_apply_sell_fill` ← on_trade_approved)과 tracked SELL 델타(`_poll_tracked_fills`) 둘 다의 공용 choke point이므로, 여기 한 번 배선하면 두 경로 모두 대칭이 된다(H3가 즉시+부분체결을 함께 고친 것과 동형).

---

## 4. Global Constraints (모든 태스크 공통)

- **대칭성**: SELL 미러가 register_fill_as_position(ADD 미러)와 대칭 — 같은 모듈·같은 best-effort/never-raise/PM-미기동-skip 계약.
- **never-raise**: PM 미러 실패는 로그만, SELL 처리(coordinator 재조정·원장·실현손익)를 절대 막지 않는다.
- **멱등·자가교정**: `remove_position` 멱등(PM 자체청산이 먼저 제거해도 무해), `update_position`은 절대값 할당(PM 잔량이 어긋나도 coordinator 권위 잔량으로 자가 교정).
- **coordinator 측 로직 불변**: `_remove_position`/차감/실현손익/원장 기록은 그대로 — PM 미러만 추가한다.
- **실 LLM/네트워크 금지**: 테스트는 PM/chat_coordinator 스텁.

## 5. 테스트

- **전량 SELL**: `_apply_sell_position_delta`(quantity >= position.quantity)가 `_remove_position` + `mirror_sell_to_position_manager(ticker, 0)`을 호출 → PM.remove_position(ticker) 호출됨(mock 검증).
- **부분 SELL**: quantity < position.quantity → coordinator 잔량 차감 + `mirror(ticker, remaining)` → PM.update_position(ticker, quantity=remaining) 호출됨.
- **PM 미기동**: position_manager is None → no-op(예외 없음).
- **멱등**: PM에 해당 ticker 없음(이미 제거) → remove_position False 반환, 예외 없음, SELL 처리 정상 완료.
- **never-raise**: PM 미러가 예외를 던져도 `_apply_sell_position_delta`가 정상 반환(coordinator 재조정 완료).
- **회귀**: 기존 trading/execution/sell-fill 스위트 green(_apply_sell_fill·_poll_tracked_fills·실현손익·원장 불변).

## 6. 배포 후 실증 (운용)

재배포(재시작) 후 통제 buy/sell 반복: BUY(즉시체결) → 양 엔진 등록 → SELL → **수동 `/positions/sync` 없이** coordinator 0 **AND** PositionManager 0 확인(라이브 대칭 실증).

## 7. 파일 요약

- `services/trading/position_registration.py` — `mirror_sell_to_position_manager` 신규(register_fill_as_position 옆).
- `services/trading/coordinator.py:1557-1561` — `_apply_sell_position_delta` 두 분기에 미러 호출 + import.
- 테스트: `tests/test_services/test_trading/test_position_registration.py` 또는 `test_sell_fill_tracking.py`(_apply_sell_position_delta 경로 픽스처 재사용).

관련: [[session-2026-07-21-discovery-manual-trigger]]
