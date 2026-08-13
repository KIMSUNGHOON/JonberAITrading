# F3: 사후 체결 추적 + 브로커-로컬 정합 — 설계

- **날짜**: 2026-07-13 (C1 운용일, OPERATIONS 보드·F-wave 직후)
- **상태**: 설계 승인됨 (사용자, 2026-07-13 — 접근안 A + 감시 양쪽 등록 + 고아 ±8% 결정 포함)
- **위치**: C2 자율 전환 전 필수 아크

## 1. 문제 (라이브 실증)

2026-07-13 11:18, 사용자 큐 전환 매수(삼성전자 144주 @260,000 3분할 + SK하이닉스 19주 @1,909,000)가 지정가 미달로 발주 시점 체결 0 → 코디네이터는 (올바르게) 포지션 미등록, 큐 항목은 completed 종결 → **이후 시장가 하락으로 전량 체결됐지만 아무도 감지하지 못함** → 손절/익절 감시 없는 보유 2종목(≈₩7,370만)이 브로커에만 존재. 스탑은 수동 API 호출로 응급 등록했으나 PositionManager가 인메모리라 재시작마다 소실.

## 2. 근본 원인 (코드 확인 완료)

| # | 갭 | 근거 |
|---|---|---|
| 1 | OrderAgent는 체결 확인(ka10076, 3회/0.5s) 후 0-fill이면 `status="pending"` 반환 — **그 이후를 아무도 추적 안 함** | order_agent.py:391-419, 434-477 |
| 2 | **그래프 실행 노드는 발주=체결 가정** — ka10076 미호출, 요청 수량으로 `active_position` 생성(그래프 state에만 존재, 어느 감시 엔진에도 미등록) → 유령 포지션의 원천 | agents/graph/kr_stock_nodes/execution.py:249-341 |
| 3 | 큐 완료 판정이 실체결이 아닌 계획 수량(`allocation.quantity`) 기준 | coordinator.py:1346-1350 |
| 4 | PositionManager: 영속 없음 + 브로커 재동기화 없음(start 시 1회 `sync_from_account`뿐) + 브로커 동기 포지션은 stop_loss=None | position_manager.py:1017-1059 |
| 5 | 두 감시 엔진(RiskMonitor 1s / PositionManager 30s)이 레지스트리 공유 없이 같은 종목 이중 감시·이중 매도 가능 | 탐색 리포트 §2c |
| 6 | ka10075/ka10076 응답에 날짜 필드 없음(`ord_dt=""`/`ccld_dt=""`) → 일자 경계는 로컬 관리 필수 | client.py:830, 983-999 |

## 3. 사용자 결정

1. **감시 등록**: 사후 체결 포지션은 **양쪽 엔진 모두** 등록(코디네이터 RiskMonitor + PositionManager) — R3 "양 엔진 유지"와 일관. RiskMonitor=(게이트 허용 시) 자동 방어 집행, PositionManager=토론/통지 트리거. 리컨실러가 둘의 정합 유지.
2. **고아 포지션**(유래 기록 없는 브로커 보유): **기본 ±8% 스탑 자동 등록 + 텔레그램 통지**. `RiskParameters`에 `default_stop_loss_pct: float = 8.0`, `default_take_profit_pct: float = 8.0` 신설(현재 per-position 기본 스탑 필드 부재 — 탐색 §6).
3. **아키텍처**: **A안 — PendingOrderTracker + 리컨실러** (B 리컨실러 단독은 주문 단위 정밀도 부족, C WS 체결 이벤트는 미검증 컴포넌트라 R5-P4 후보로 보류).

## 4. 컴포넌트 설계

### 4.1 PendingOrderTracker (`services/trading/` 신규 모듈, 코디네이터 소유)

**TrackedOrder** (Pydantic): `ord_no`(조인 키 — FilledOrder.ord_no와 매칭, 탐색 §5 확인), `ticker`, `stock_name`, `side`, `total_quantity`, `filled_quantity`(누적), `limit_price`, `stop_loss`, `take_profit`(의도된 값 — 제안/큐에서), `source_queue_id`, `source_session_id`, `placed_at`, `trade_date`(로컬 일자 — 갭 6), `status`(TRACKING/FILLED/EXPIRED/CANCELLED).

**등록 경로 (2경로 + 제외 1)**:
- 코디네이터 `on_trade_approved`/큐 실행: OrderAgent `OrderResult.status in ("pending","partial")` → 잔량 추적 등록 (기존 filled>0 분기의 포지션 등록은 유지 — 부분체결 시 체결분 등록+잔량 추적).
- 그래프 실행 노드(§4.2)에서 0-fill/부분 잔량 인계.
- (수동 REST 주문은 등록 안 함 — 리컨실러가 커버, §4.3.)

**폴링 사이클**: 코디네이터의 기존 30s 스케줄러 사이클에 합류. TRACKING 주문이 있을 때만 `get_filled_orders(use_cache=False)` 1회 호출 → `ord_no` 매칭, `ccld_qty` 합산으로 신규 체결분 산출:
- 신규 체결분 > 0 → 코디네이터 `_add_position`(ManagedPosition, 스탑 포함, 평균가는 체결가 가중) + RiskMonitor + **PositionManager add/update**(동일 스탑) + 텔레그램 통지("사후 체결: {name} {qty}주 @{price}, 손절 {sl} 감시 시작") + 해당 큐 항목 사후 주석(error_message 필드가 아닌 reason 덧붙임 — 큐 status 어휘는 불변, 범위 밖 §7).
- 전량 체결 → status=FILLED, 추적 종료.
- **장 마감 감지 시**(기존 `_check_queue_on_market_open`과 동일한 KRX 시간 유틸의 open→closed 엣지): 당일 `trade_date`의 TRACKING 잔량 → status=EXPIRED + 통지(KRX 지정가는 당일 유효 — 브로커 신호 부재로 로컬 판정).

**영속**: R5-P1 blob(`trading:coordinator_state`)에 `tracked_orders` 배열 추가 직렬화. `_restore_state`에서 복원(FILLED/EXPIRED 제외 TRACKING만 재개, 날짜 바뀐 TRACKING은 EXPIRED 처리). `_schedule_persist` 트리거에 추적 상태 변화 추가.

### 4.2 그래프 실행 노드 체결 확인 (유령 포지션 원천 봉쇄)

OrderAgent의 `_confirm_kiwoom_fill`을 `services/trading/fill_confirm.py` 공용 헬퍼로 추출(OrderAgent는 위임, 시그니처·재시도 정책 불변). `kr_stock_execution_node`가 발주 후 이 헬퍼로 체결 확인:
- 체결분 > 0: 체결 수량으로 `active_position` 구성(현행 스탑 로직 유지) + **양쪽 엔진 등록**(공용 등록 헬퍼 경유 — §4.4) + `execution_status="completed"`.
- 체결 0: `active_position` 생성하지 않음, `execution_status="placed_pending_fill"`(신규 값). **구현 전 `execution_status` 소비자 전수 확인 필수**(BE 상태 mirror·FE 렌더 — "completed"만 특별 취급하는지 검증 후 신규 값 도입; 특별 취급 소비자 발견 시 해당 소비자도 함께 수정). 잔량을 Tracker에 등록.
- 부분: 체결분 포지션+등록, 잔량 Tracker 인계, `execution_status="completed"`(체결분 존재).
- Tracker 접근: 그래프 노드 → `app.dependencies.get_trading_coordinator()`(지연 import, 기존 노드들의 서비스 접근 관례 확인 후 동일 패턴).

### 4.3 리컨실러 (코디네이터 기존 30s 루프의 매 2번째 틱 = 60s 주기, 신규 태스크 없음)

`get_account_balance()` 보유 ↔ {코디네이터 `_state.positions` ∪ PositionManager `_positions`} 대조 (티커 기준):
- **고아**(브로커에만): 스탑 유래 조회 순서 = ① TrackedOrder(FILLED 포함 최근 레코드) → ② 영속 큐 기록(같은 ticker, 최근 우선, stop_loss 비null) → ③ 없음 → **기본 ±8%**(평단 기준, RiskParameters 신설 필드). 양쪽 엔진 등록 + 통지("고아 포지션 발견: {name} {qty}주 — 스탑 {유래} 등록").
- **역방향**(관리 중인데 브로커에 없음): 양쪽에서 제거 + 통지("외부 매도 감지"). 단 **TRACKING 중 매도 주문이 있는 티커는 제외**(자체 매도 진행 중 오탐 방지).
- **수량 불일치**: 브로커 수량으로 양쪽 보정(+통지, 임계 1주 이상 차이).
- 실패 시: 조회 실패는 해당 사이클 스킵+로그(fail-safe, 관리 상태 훼손 금지). 브로커 캐시(30s)와 60s 주기가 정합 — 추가 유량 부담 미미.

### 4.4 공용 등록 헬퍼 + PositionManager 스탑 영속화

- `register_fill_as_position(...)` 공용 헬퍼(코디네이터 모듈): ManagedPosition 생성→`_add_position`→PositionManager `add_position`/`update_position`(스탑 포함) — Tracker·그래프 노드·리컨실러 3소비자가 공유(등록 로직 단일화). PositionManager 접근은 `get_chat_coordinator()` 지연+예외 박싱(F2에서 검증된 패턴), PM 미기동 시 코디네이터 등록만 수행+로그.
- **PM 영속**: `app_settings` blob `agent_chat:position_manager_state`에 ticker별 `{stop_loss, take_profit, trailing_stop_pct}` 저장(add/update/remove 시 fire-and-forget persist, R5-P1 `_schedule_persist` 패턴). `PositionManager.start()`에서 `sync_from_account` **후** 오버레이 복원(브로커에 없는 티커의 잔존 항목은 폐기). 수동 재등록 불필요화 — RESUME 절차 단순화.

## 5. 이중 매도 리스크 (명시적 비범위 + C2 전제)

양쪽 등록으로 동일 티커 이중 감시는 **의도된 상태**. C1에선 두 엔진 모두 비자동(RiskMonitor `USER_APPROVAL` 알림 / PositionManager `auto_execute=False` 토론)이라 이중 매도 불가. 방어 매도 실행 시 `_apply_sell_fill`+리컨실러가 60초 내 수렴. **C2(자율) 전환 전 티커 단위 매도 잠금(in-flight guard)을 별도 아크로 반드시 선행** — 본 스펙 범위 밖이나 전제 조건으로 기록.

## 6. 테스트

- Tracker: 등록(3경로)→폴링 체결(전량/부분/무체결)→양쪽 등록 확인→만료(장 마감 엣지·날짜 변경 복원)→영속 왕복(R5-P1 `temp_storage` 픽스처 재사용).
- 그래프 노드: 0-fill 시 active_position 없음+Tracker 인계+`placed_pending_fill` / 부분·전량 시 등록 — 실 Pydantic 모델 픽스처(자기목 검증 금지, F1 교훈).
- 리컨실러: 고아 3가지 유래 순서, 역방향(+TRACKING 매도 제외), 수량 보정, 조회 실패 스킵.
- PM 영속: 재시작 왕복(sync 후 오버레이), 브로커 부재 티커 폐기.
- 컨벤션: `tests/test_services/test_f3_fill_tracking.py`(phase 스위트, `test_r5_p1_*` 관례) + 모듈별 단위. 기존 608+ 회귀 유지.

## 7. 범위 밖

WS 실시간 체결 이벤트(C안, R5-P4) / 큐 status 어휘 변경(placed 등 신규 상태 도입) / 이중 매도 티커 잠금(C2 전제, 별도 아크) / coin 마켓 확장 / 수동 REST 주문의 Tracker 등록(리컨실러가 커버) / 브레이커의 미실현 손익 반영(R5-P4).
