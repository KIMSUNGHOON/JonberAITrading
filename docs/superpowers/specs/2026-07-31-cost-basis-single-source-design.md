# 원가(cost basis) 단일화 설계 — 브로커를 진실로

**작성일**: 2026-07-31
**상태**: 구현 완료 (배포 대기 — 장 마감 후, 15:30~16:35 EOD 창 제외)

## 문제

같은 포지션의 원가(`avg_price`)가 세 벌 존재하고, 그중 둘은 갱신되지 않는다.

브로커(키움 kt00004 `avg_prc`)만이 실제 체결 가중평균과 일치한다. 2026-07-31 실측:

| 종목 | 브로커 | PositionManager | coordinator | 실제 체결 VWAP |
|---|---|---|---|---|
| 089860 롯데렌탈 | 38,091 | 37,950 (−0.370%) | 37,950.99 (−0.368%) | 38,090.79 ✓브로커 |
| 317400 자이에스앤디 | 5,843 | 5,850 (+0.120%) | 5,844.99 (+0.034%) | 5,843.33 ✓브로커 |

**이것은 표시 문제가 아니다.** `PositionManager.avg_price`는 손절·익절 거리 산정의 기준선이고
`_apply_take_profit_lock_in` 등이 그 위에서 돈다. 원가가 낮게 고정되면 손절가도 낮게 잡혀
**실제 손실 허용폭이 설계보다 커진다.**

### 원인 — 두 갈래

**1. reconciler가 수량만 고치고 원가를 방치한다.**
`services/trading/reconciler.py:315-345`의 `_fix_quantities`는 브로커와 수량이 어긋나면
`coordinator_pos.quantity = broker_qty`(:322)와 `current_price`(:328)를 맞추고
`pm.update_position(ticker, quantity=broker_qty)`를 부른다. **`avg_price`는 어느 쪽도 넘기지 않는다.**
그래서 148주어치 원가가 185주에 그대로 적용되는 상태가 관측됐다. 브로커가 정답이라는 원칙은
이미 수량에 적용돼 있고, 원가만 예외로 남아 있다.

**2. 체결 미러의 merge 분기가 원가를 갱신하지 않는다.**
`services/trading/position_registration.py:113-133`은 기존 포지션에 체결을 병합할 때
`quantity=existing.quantity + quantity`만 넘기고 `avg_price`를 넘기지 않는다. 그래서 PM 평단이
**첫 체결 트랜치에 영구 동결**된다.

`PositionManager.update_position`은 `avg_price` 파라미터를 이미 갖고 있으며, 그 docstring이
현 상태를 정확히 기술한다 — *"only ever recomputed by an ADD's weighted-average merge
(`_execute_add_position`). **No other caller passes it.**"* (`position_manager.py` 참조)
즉 API는 있고 호출자가 없다.

## 원칙

**브로커가 원가의 단일 진실이다.** 수량은 이미 그 원칙을 따르므로 원가만 예외로 둘 근거가 없다.

다만 체결 시점에는 브로커 조회가 없다. 그래서 두 층으로 나눈다.

| 층 | 시점 | 값 | 역할 |
|---|---|---|---|
| 즉시 | 체결 미러 | 로컬 가중평균 | 다음 reconcile까지의 근사 |
| 최종 | reconcile | 브로커 `avg_buy_prc` | 진실 |

로컬 가중평균은 `_execute_add_position`(`position_manager.py:2073-2080`)이 이미 쓰는 식과 같다:

```
new_avg = (old_qty × old_avg + fill_qty × fill_price) / (old_qty + fill_qty)
```

## 범위

### C1. reconciler가 원가도 맞춘다

`_fix_quantities`가 수량 불일치를 고칠 때 `avg_price`도 브로커 `holding.avg_buy_prc`로 맞춘다.
coordinator와 PM 양쪽 모두.

**수량이 일치해도 원가가 어긋날 수 있다.** 현재 이 함수는 `quantity != broker_qty`일 때만
진입하는데, 오늘 실측된 089860·317400은 **수량이 맞는 상태에서 원가만 어긋나 있었다.**
따라서 원가 비교를 독립 조건으로 추가한다 — 수량 일치 여부와 무관하게 원가 편차가 임계를
넘으면 교정한다.

임계는 **0.1%**로 둔다. 브로커 `avg_buy_prc`가 `int`라 주당 최대 0.5원의 절삭 오차가 있고
(`services/kiwoom/models.py:202`), 그것을 불일치로 오판하지 않기 위해서다.

함수명이 실제 동작(수량+원가)과 어긋나므로 그에 맞게 조정한다.

### C2. 체결 미러가 가중평균을 넘긴다

`position_registration.py`의 merge 분기가 `avg_price`를 계산해 넘긴다. 위 가중평균 식을 쓴다.

**`stop_loss`/`take_profit`의 coalesce 규칙은 그대로 둔다** — 기존 값이 있으면 덮어쓰지 않는
현 동작이 옳고, 이 아크의 소급 원칙(손절가 불변)과도 일치한다.

**`entry_decision_id`도 그대로 둔다.** merge 분기에서 절대 건드리지 않는 불변식이 이미
문서화돼 있다(고아 채택 포지션이 무관 세션에 오귀속되는 것을 막기 위함).

### C3. 원가 정합성 감시

내부 `avg_price`가 브로커 대비 **0.1% 이상** 벌어지거나 수량이 다르면 로그와 Telegram 통지를 낸다.

**손익이 아니라 원가만 감시한다.** 브로커 손익과 내부 손익의 절대차는 모의투자 수수료율
차이(브로커 0.90% 왕복 vs 앱 모델 0.27%)로 **상시** 벌어지므로, 손익을 감시하면 영구 오탐이 된다.
원가는 정의가 하나뿐이라 어긋나면 그 자체가 결함이다.

통지는 이번 아크에서 만든 never-raise 패턴을 따르고, 종목당 1회로 래치한다
(`liquidity_cap_blocked_notified`와 같은 형태) — reconcile은 주기적으로 돌므로 래치가 없으면
같은 불일치를 반복 발송한다.

> **구현 시 정정(Task 4)**: 위 문장의 "종목당 1회"와 "`liquidity_cap_blocked_notified`와
> 같은 형태"는 서로 모순이었다 — 인용된 전례(`liquidity_cap_blocked_notified`,
> `close_gate_denied_notified`)는 모두 가드 조건을 통과하면(문제가 해소되면) 플래그를
> 되돌려 재발 시 다시 통지한다. 즉 "영구 1회"가 아니라 "에피소드당 1회"다. 사람 파트너가
> **에피소드당 1회**로 확정했다 — `_COST_DRIFT_NOTIFIED` 래치는 원가 편차가 임계 이내로
> 확인되는 순간 해당 티커를 discard하고, 그 뒤 새로운 편차가 다시 임계를 넘으면 재통지한다.
> `services/trading/reconciler.py`의 `_fix_positions`/`_alert_cost_basis_drift` 참조.

## 소급 적용 — 원가만, 손절가는 불변

기존 포지션의 `avg_price`는 즉시 교정한다. **이미 설정된 손절·익절가는 재계산하지 않는다.**

운용 중인 포지션의 방어선을 자동으로 움직이는 것은 예측 불가능한 부작용을 낳는다. 손절
단조성 가드(낮추지 않기)가 이미 있어 교정 방향도 일관되지 않는다 — 오늘 실측만 봐도
089860은 손절이 올라가고(더 빨리 발동) 317400은 내려간다(더 늦게 발동).

**다음 진입부터 올바른 원가로 산출된다.**

> **구현 시 정정(최종 리뷰 item5)**: "손절가는 불변"은 **직접 대입에 한해서만** 정확하다.
> `PositionManager._apply_take_profit_lock_in`(position_manager.py:1020-1046)은
> `lock_in = 0.7·avg_price + 0.3·take_profit`로 락인 스탑을 계산하므로, 원가 교정이
> `avg_price`를 올리면 다음 틱에 락인 스탑도 교정폭의 0.7배만큼 간접적으로 올라간다
> (089860 실측: 원가 +141원 → 스탑 약 +99원, +0.26%). `max(current_stop, lock_in_price)`와
> `_stops_sane` 가드 때문에 이 간접 이동은 **올라가기만 하고 내려가지는 않는다** — 손절
> 단조성 가드와 같은 방향이라 원가 교정이 방어선을 약화시키는 경로는 없다. 다만 따름정리:
> 체결/reconcile 이중계산 창에서 원가가 일시적으로 과대해졌다가 나중에 재교정되더라도,
> 그 사이에 락인이 이미 `max()`로 반영해버린 스탑은 되돌릴 수 없다 — 일시적 오버슈트가
> 영구적인 스탑 상향으로 남는다.

## 검증

| 대상 | 검증 |
|---|---|
| C1 수량+원가 | 브로커 185주/38,091 vs 내부 148주/37,950 → reconcile 후 양쪽 다 브로커 값 |
| C1 수량 일치·원가 불일치 | 수량이 같고 원가만 0.37% 어긋난 상태(오늘 실측)에서도 교정된다 |
| C1 임계 미만 | 0.05% 편차는 교정하지 않는다(브로커 int 절삭 오차 흡수) |
| C2 가중평균 | 20주@10,000 보유 + 28주@11,000 체결 → 평단 10,583.33 |
| C2 coalesce 불변 | 기존 stop_loss가 있으면 덮어쓰지 않는다 |
| C2 entry_decision_id 불변 | merge 분기가 건드리지 않는다 |
| C3 감시 | 0.1% 초과 시 통지 1회, 반복 reconcile에도 재발송 없음 |
| C3 오탐 없음 | 손익 차이만으로는 통지하지 않는다 |
| 소급 | 원가 교정 후에도 기존 stop_loss/take_profit이 그대로다 |

## 명시적 제외

**계좌 스냅샷 동결** — `stock_value`·`total_equity`·`cash`가 하루 종일 얼어붙는다
(오늘 실측 4,668,220 vs 실제 11,967,013, **2.5배**). `_refresh_account_info`가
`start()`와 매매 시점에만 불리는 구조이고, 원가 문제와 원인이 다르다. 별도 아크.

**`/api/kr_stocks/accounts`의 gross/net 혼용** — `total_profit_loss`(GROSS)와
`holdings[].profit_loss` 합(NET)이 107,577원 어긋난다. 표시 아크에서 다룬다.

**NAV 손익 표시** — 이 아크의 후속이다. 표시용 단일 진실 소스는 이미 판정됐다:
`GET /api/trading/operations?market=kiwoom`의 `holding[].pnl`(세후). 원가가 정리되면
그 위에 표시를 올린다.

**PM `stock_name`에 티커가 들어가는 문제** — 089860이 `"089860"`으로 표시된다.
같은 파일(`position_registration.py`)이 원인이지만 표시 결함이라 이 아크의 안전 목적과
분리한다.

## 배포 창

라이브가 실 포지션 2종을 감시 중이다. 원가 교정은 손절가를 바꾸지 않으므로 장중 배포도
이론상 안전하지만, reconcile이 포지션 상태를 건드리므로 **장 마감 후** 배포한다.
15:30~16:35 EOD 발굴 창은 피한다.
