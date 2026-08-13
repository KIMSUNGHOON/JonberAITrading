# 보유 포지션 자율 관리 실사 (2026-07-14)

> 3-에이전트 READ-ONLY 실사 + 종합. 설계 제안(승인 전 구현 금지).

Spot-verification confirms all three investigators. The code says exactly what they reported. Here is the synthesis.

---

# 보유 포지션 자율 관리 실사 종합

세 실사자가 독립적으로 같은 결론에 도달했고, 내가 핵심 3개 지점(`position_manager.py:965-1003`, `analysis.py:44-132`, `decision_policy.py:13-15`)을 직접 읽어 재확인했습니다. 아래는 과장 없이 코드 그대로입니다.

## A. 두 질문 직답

### 질문 1 — "보유 포지션의 자율 ADD/REDUCE/SELL 판단이 지속 감시로 동작하는가?"

**상태: DEFENSIVE_ONLY (방어적 청산만 동작, proactive ADD/REDUCE는 미동작)**

당신의 기대 — "보유 포지션을 지속 관찰하다가 자율로 다음 액션(늘리기/줄이기/청산)을 결정·실행" — 은 **부분적으로만 맞고, 핵심 부분은 틀립니다.**

- **지속 감시는 실제로 돕니다.** RiskMonitor(1초)와 PositionManager(30초) 두 루프가 실제로 보유 포지션을 감시하고, 임계 이벤트가 나면 실제 LLM 에이전트 토론까지 열어 `session.decision`을 받아 `_apply_decision`으로 반영합니다. 여기까지는 살아 있습니다.
- **그러나 실행까지 완결되는 건 "전량 SELL(청산)" 하나뿐입니다.** `_apply_decision`(position_manager.py:965-1003)을 보면:
  - `SELL` → `_execute_close_position` → `check_autonomy` 게이트 통과 후 실제 브로커 매도. **정상 동작.**
  - `REDUCE`(부분 축소) → `self.update_position(quantity=new_quantity)`만 호출. **브로커에 매도 주문이 나가지 않습니다.** PositionManager의 내부 그림자 장부만 바뀌어, 다음 `sync_from_account`가 실제 잔고로 덮어쓸 때까지 상태가 어긋납니다. 이건 기능 공백이자 사실상 버그입니다.
  - `ADD`(추가 매수) → `HOLD`와 **완전히 동일한 분기**로 묶여 손절/익절 값만 갱신할 뿐, 매수 주문 코드가 파일 전체에 **존재하지 않습니다.** "늘려라"는 토론 결과는 조용히 HOLD로 격하됩니다.
- **감시 트리거 자체가 방어용입니다.** PositionManager가 토론을 여는 계기는 손절/익절 근접·도달, ±수익률(±10%/-5%), 트레일링 스탑, 장기보유뿐입니다. "지금 이 종목을 전략적으로 재평가해서 더 살까/줄일까"를 주기적으로 판단하는 트리거는 없습니다.

정리하면, **지속 감시 → 자율 청산(SELL)은 됩니다. 지속 감시 → 자율 ADD/REDUCE는 안 됩니다.** 코드가 그 결정을 산출하고 토론까지 하더라도, 실행 단계에서 조용히 버려지거나 장부만 틀어집니다.

> 참고: 코드베이스에 ADD/REDUCE **실주문 능력 자체는 존재합니다** — LangGraph 분석 그래프의 `kr_stock_nodes/execution.py`가 KiwoomExecutionAdapter로 실제 발주하고 체결 확인까지 합니다. 문제는 **이 경로를 보유 종목에 대해 자동으로 다시 띄우는 스케줄러가 없다는 것**입니다. 즉 능력은 있으나 "지속 감시"와 배선이 끊겨 있습니다.

### 질문 2 — "이미 포지션 있는 종목 재분석을 계속 요청할 수 있다(중복·낭비)"

**당신 관찰이 맞습니다.**

`POST /analysis/start`(analysis.py:44-132)는 호출될 때마다 무조건 `session_id = str(uuid.uuid4())`를 새로 발급하고 그래프를 새로 돌립니다. **같은 종목 진행 중 세션이 있는지, 이미 보유 중인지 전혀 확인하지 않습니다.** 유일한 제한은 `analysis_limiter`의 **전역 동시 실행 개수** 세마포어뿐 — 티커 단위 dedup이 아닙니다.

티커 단위 가드는 딱 두 곳에만 있고, 둘 다 이 경로를 커버하지 못합니다:
- agent-chat 수동 토론(`start_manual_discussion`, coordinator.py:860-861): `ticker in _active_rooms`면 ValueError. 단순 동시성 가드일 뿐이고 별개 서브시스템입니다.
- watch-list 발굴 루프(`_was_recently_discussed`, 30분): 미보유 후보 전용입니다.

**결론: 이미 포지션이 있어도, 아무 검사 없이 새 진입 분석 세션이 그대로 돌아갑니다. 중복·낭비 관찰은 사실입니다.**

---

## B. 실제 아키텍처 — 보이는 것 vs 실제

핵심은 **"진입(watch-list)"과 "관리(held-position)"가 서로 다른 저장소·스케줄·실행경로를 가진 완전히 분리된 두 시스템**이고, 게다가 **관리 쪽에도 두 개의 서로 단절된 세계**가 있다는 점입니다.

```
[진입 파이프라인]  watch-list (미보유 WATCH 후보)
   WatchedStock 저장소
   ChatCoordinator._check_watch_list  ── 5분 APScheduler
        └─ _detect_opportunity → 토론 → _handle_decision
             └─ check_autonomy → on_trade_approved → 실제 BUY 실행  ✅ 완결

[관리 파이프라인]  held-position (계좌 실보유분)   ← 진입과 완전 별개 저장소
   MonitoredPosition 저장소 (sync_from_account으로 시딩)
   │
   ├── RiskMonitor  ── 1초 루프
   │      손절/익절 근접만 감시 → AGENT_AUTO면 즉시 SELL, 아니면 알림
   │      (ADD/REDUCE 개념 자체가 WatchConfig에 없음)
   │
   └── PositionManager  ── 30초 루프
          방어 이벤트(손절/익절/±수익률/트레일링/장기보유) 감지
             └─ _trigger_discussion (포지션당 5회·30분 스로틀)
                  └─ start_manual_discussion(wait=True) → 실제 LLM 토론
                       └─ _apply_decision  ← ★여기서 끊긴다★
                            ├─ SELL       → _execute_close_position → 실주문 ✅
                            ├─ REDUCE(부분) → update_position만 (장부만, 주문 X) ❌
                            └─ ADD/HOLD   → 스탑값만 갱신 (매수 X)          ❌

[고립된 능력]  LangGraph 분석 그래프 execution.py
   ADD/REDUCE 실주문(KiwoomExecutionAdapter, 체결확인) 능력 있음
   → 그러나 /analysis/start(수동) 또는 60초 인젝터 승인 때만 도달
   → 어떤 스케줄러도 보유 종목에 대해 이 그래프를 자동 재기동하지 않음  ⚠️단절
```

**끊기는 지점 세 곳:**
1. **`_apply_decision`의 ADD/REDUCE 분기** — 결정은 도착하지만 실행이 없다(위 ★).
2. **부분매도 실행 경로 부재** — `trading/coordinator._close_position`(1403-1426)은 `quantity=position.quantity`로 하드코딩된 전량 청산 전용. 부분 REDUCE를 발주할 호출부가 애초에 없다.
3. **관리 파이프라인 ↔ 분석 그래프 단절** — 진짜 ADD/REDUCE 실행 능력은 분석 그래프에 있는데, 30초 관리 루프는 자기만의 `_apply_decision`을 쓰며 그 능력을 호출하지 않는다.

**추가 분리:** 보유 포지션은 watch-list에 자동 등록되지 않고(`WATCH`는 미보유 상태에서만 feasible — `decision_policy.py:14-15`), watch-list 종목이 체결돼도 실시간으로 PositionManager에 편입되지 않습니다(다음 `sync_from_account` 때나 반영). 두 세계는 상태를 각자 굴립니다.

---

## C. 갭과 개선 방향 (설계 제안 — 승인 전 구현 금지)

"제대로 된 자동매매"가 되려면, **보유 포지션이 주기적으로 전략 재평가되어 ADD/REDUCE/HOLD/SELL을 자율 결정하고, 그 결정이 실제 발주까지 완결**되어야 합니다. 현재는 결정은 나오는데 실행이 SELL 하나로 좁혀져 있습니다.

### P0 — 정합성 응급 조치 (규모: 소, 반나절)
지금 이 두 분기는 **가만히 두면 능동적으로 해롭습니다.**
- **부분 REDUCE의 조용한 desync 차단.** 부분 축소가 실주문 없이 내부 장부만 바꾸는 건 "포지션 상태에 대한 거짓말"입니다. 실행 경로가 생기기 전까지는 이 분기를 (a) 실행 불가로 명시적 로그+알림 처리하고 장부를 건드리지 않게 하거나, (b) 안전하게 전량 청산으로 축소하는 방향 중 택일. **최소한 지금처럼 조용히 틀어지게 두면 안 됩니다.**
- **ADD-as-HOLD 격하도 침묵하지 말 것.** ADD 결정이 HOLD로 삼켜질 때 최소한 "추가매수 미지원으로 보류됨" 알림이 나가야 사용자가 시스템을 오해하지 않습니다.

이건 새 기능이 아니라 **기존 버그성 침묵을 정직하게 만드는 것**이라, 자율 매매를 안 켜더라도 먼저 해야 합니다.

### P1 — 부분매도 실행 경로 (규모: 중)
`ExecutionCoordinator`에 **수량 지정 부분 매도**를 추가하고 REDUCE 분기를 여기에 배선. 기존 `_execute_close_position`이 `check_autonomy(SELL)` 게이트를 타듯, 부분매도도 동일 게이트를 타야 합니다. 이게 되면 REDUCE가 실제 계좌에 반영됩니다.

### P2 — ADD(추가 매수) 실행 + 사이징 (규모: 중~대)
PositionManager 관리 경로에 매수 실행을 추가하되 **반드시 `check_autonomy(BUY)` + notional 캡 + 브레이커 게이트**를 통과시켜야 합니다(진입 경로 `on_trade_approved`와 동일 수준). 규모가 커지는 이유는 **포지션 사이징 정책**이 비자명하기 때문입니다 — 얼마를 더 살지 결정하는 로직이 지금 어디에도 없습니다. 이건 설계 결정이 선행돼야 합니다.

### P3 — 보유 포지션 주기적 전략 재평가 루프 (규모: 대 — 진짜 "자동매매" 본체)
현재 30초 루프는 방어 이벤트에만 반응합니다. "지금 이 종목을 다시 판단"하는 능동 재평가가 없습니다. 두 방향:
- **(권장) 관리 루프가 분석 그래프를 재사용** — 보유 종목에 대해 주기적으로(예: N분 또는 유의미한 가격/거래량 변화 시) position-aware 분석 그래프를 재기동하고, 그 결과 ADD/REDUCE/HOLD/SELL을 **이미 존재하는 execution.py 실행 경로**로 흘려보냅니다. 능력은 이미 있으니 배선 문제이지만, 재기동 스케줄러·중복 억제·비용 관리가 얽혀 규모가 큽니다.
- (대안) 별도 STRATEGIC_REEVAL 이벤트 타입을 만들고 `_apply_decision`을 P1/P2 실행 경로와 통합.

이게 없으면 "보유 포지션 지속 관찰 → 자율 다음 액션"이라는 당신의 원래 요구는 근본적으로 충족되지 않습니다. P1/P2는 실행 배관이고, P3가 실제로 "판단"을 만드는 부분입니다.

### P4 — 재분석 중복 가드 + 관리 모드 라우팅 (규모: 소~중)
- `/analysis/start`에서 **해당 종목 보유 여부를 조회** → 보유 중이면 새 진입 분석 대신 "관리 모드(재평가)"로 라우팅하거나, 최소한 사용자에게 "이미 보유 중 — 관리 파이프라인이 담당" 안내.
- **티커 단위 진행중 세션 가드** 추가(전역 개수 상한만으로는 동일 종목 중복이 안 막힘). agent-chat의 `_active_rooms` 패턴을 분석 파이프라인에도 이식하면 됩니다.

### 기존 안전장치와의 정합
제안 전부가 기존 fail-closed 체계와 **모순 없이** 얹힙니다:
- 새 ADD(BUY)·부분 REDUCE(SELL) 실행은 **전부 `check_autonomy` 게이트를 반드시 경유** — master gate(AUTONOMY_ENABLED), 마켓 모드, paper 하드코딩, 브레이커, notional 캡이 그대로 적용됩니다. 지금 SELL 청산이 이미 그렇게 하고 있으니 같은 패턴을 따르면 됩니다.
- 60초 유예 인젝터(제안 ID 피닝, 수동 우선)와도 정합 — P3에서 재평가 그래프가 새 제안을 만들면 인젝터가 자동승인 흐름을 그대로 태웁니다.
- 손절/익절 방어(RiskMonitor)는 **건드리지 말 것** — 이건 이미 올바르게 동작하는 최후 안전망이고, 새 능동 로직과 독립적으로 유지돼야 합니다.

### 우선순위 요약
| 우선 | 항목 | 규모 | 성격 |
|---|---|---|---|
| P0 | REDUCE desync/ADD 침묵 정직화 | 소 | 버그 봉합(선행 필수) |
| P1 | 부분매도 실행 경로 | 중 | 실행 배관 |
| P2 | ADD 매수 실행 + 사이징 정책 | 중~대 | 실행 배관 + 정책 결정 |
| P3 | 보유 포지션 주기적 전략 재평가 | 대 | **기능 본체** |
| P4 | 재분석 dedup + 관리모드 라우팅 | 소~중 | 낭비 차단 |

**한 줄 결론:** 당신 판단은 두 가지 다 정확합니다. 지속 감시는 손절익절 방어만 자율 실행하고 능동 ADD/REDUCE는 실행에 도달하지 못하며(오히려 부분 REDUCE는 조용히 장부를 틀어뜨림), 보유 종목 재분석 중복 가드는 실제로 없습니다.