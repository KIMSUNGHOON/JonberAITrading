# F4b: 자율 경로 안전 봉합 — 설계

- **날짜**: 2026-07-14
- **상태**: 설계 승인됨 (사용자, 2026-07-14 — CRITICAL+IMPORTANT 10건 범위 + HITL 폴백 + 코디네이터 게이트 결정 포함)
- **근거**: 전면 기능 리뷰의 자율 트랙 감사(18건 확정, 발견→반박검증). F4a(수명주기) 직후 별도 아크. C2 자율 실증의 전제조건.

## 1. 문제

자율 모드(R3)는 2026-07-12 라이브 검증됐으나, 이후 F3·F-웨이브 ~25커밋이 결정 경로 심장부를 바꿨다(세션별 락 d75b888, 좀비-취소 분기 9c57fca, F3 분할주문/추적/리컨실러, PM sanity). 자율 감사가 **미발화 안전 불변식이 여러 곳에서 뚫렸음**을 확정 — 자동 승인·자동 매도가 게이트/핀/락을 우회하는 경로들. 재무 실증 전 봉합 필수.

## 2. 근본 원인 (감사 검증, HEAD eabb188)

| # | 심각도 | 원인 | 근거 |
|---|---|---|---|
| C1 | CRITICAL | **인젝터 제안ID 핀이 d75b888 락 밖에서 검증(TOCTOU)** — 유예 만료 시점 사용자 거부가 락을 잡고 재분석→새 제안으로 교체, 스테일 자동승인이 락 획득 후 안내된 적 없는 새 제안을 유예 0초·명목캡 미검증으로 actor=system 승인 | _autonomy_injector.py:127-171 |
| I1 | IMPORTANT | **AGENT_AUTO 손절/익절이 check_autonomy 완전 우회** — 자율 OFF·브레이커·live 무관하게 즉시 매도. PM 경로(R5-P0 A2)엔 게이트 有, 코디네이터 경로 無 | risk_monitor.py:293-295,336-338 → coordinator._execute_order_from_monitor |
| I2 | IMPORTANT | **max_positions 캡이 F3 미체결 BUY에 맹목 + 30초 캐시 잔고** — 자율 BUY 버스트가 max_open_positions 초과 | gate.py `_default_positions_count_provider` |
| I3 | IMPORTANT | **`/analysis/cancel/{id}`가 결정 락 우회** — 재분석 중 취소가 조용히 지워지고 인젝터가 취소된 세션에 재무장 | kr_stocks/analysis.py:319-375 |
| I4 | IMPORTANT | **zombie-cancel이 종결 세션 취소 수락** — 자동승인·실행된 거래를 COMPLETED→CANCELLED로 뒤집고 200 반환 | approval.py zombie 분기(9c57fca) |
| I5 | IMPORTANT | **통지 오보** — approve 분기가 placed_pending_fill·거부 주문을 "trade executed"로 텔레그램/WS 발신. 실제 사후 체결은 무음(코디네이터 alert 콜백 미배선) | approval.py approved 분기 |
| I6 | IMPORTANT | **자율이 코디네이터 비활성에도 주문** — 게이트가 코디네이터 활성을 요구 안 함 → F3 사후 체결 꼬리(추적·리컨실·기록) 죽은 채 미감시 포지션 | execution.py + gate.py |
| I7 | IMPORTANT | **재시작 고아 카운트다운** — 유예 중 재시작 시 재무장 없이 auto_approve_at 잔존, /operations·WS가 살아있는 듯한 카운트다운 렌더 | _autonomy_injector.py + approval.py |

## 3. 사용자 결정

1. **AGENT_AUTO 손절 게이트 거부 시 → HITL 폴백**(R5-P0 A2 동일: 미발주+감시 유지+텔레그램 1회 래치). "로봇 정지→사람 호출"로 안전.
2. **코디네이터 비활성 시 → 게이트 거부**(7번째 fail-closed 체크).
3. **범위 = CRITICAL 2 + IMPORTANT 8 (10건)**. MINOR 8은 상당수 컴포넌트 1·6에 흡수, 잔여는 백로그.

## 4. 컴포넌트 설계

### 4.1 인젝터 제안ID 핀 원자화 (C1 = CRITICAL 2건 봉합)

`submit_decision`/`_submit_decision_locked`에 `expected_proposal_id: Optional[str] = None` 파라미터 추가. 인젝터의 `_auto_approve_after_grace`가 핀한 proposal_id를 전달. **락 안에서**(awaiting 체크 직후, 결정 적용 전):
- `actor == "system"` AND `expected_proposal_id` 지정 시: `(state.get("trade_proposal") or {}).get("id") != expected_proposal_id` → **거부**(mutation 없음, `logger.info("auto_approve_stood_down_inside_lock", ...)`, 400/HTTPException 아닌 조용한 no-op 반환 — 인젝터는 이를 정상 stand-down으로 처리).
- `actor == "user"` 경로는 파라미터 무시(하위호환, 기존 동작 불변).

핀 검증이 제출과 원자적 → 거부가 새 제안으로 교체한 뒤 스테일 승인이 락을 얻어도 ID 불일치로 stand-down. **manual-wins 불변식 복원.** 인젝터 측: 게이트 재검증(check_autonomy)은 락 밖에 남되, 최종 결정은 이 핀으로 원자 보호(게이트는 안전측 보수적 재검증, 핀이 identity 보증).

### 4.2 AGENT_AUTO 손절 게이트 배선 (I1)

RiskMonitor의 `_execute_stop_loss`/`_execute_take_profit`가 호출하는 코디네이터 경로(`_execute_order_from_monitor`)에 방어 매도 전 `check_autonomy("kiwoom", TradeAction.SELL, quantity=..., entry_price=...)` 삽입. **거부 시(결정 1)**: 미발주 + 포지션 감시 유지 + 텔레그램 통지(래치 `close_gate_denied_notified` 준용 — 거부 에피소드당 1회, 게이트 재허용 시 해제). R5-P0 A2와 동일 시맨틱. RiskMonitor의 `USER_APPROVAL` 모드 경로는 이미 알림만이라 불변.

주의(범위 내 명시): 브레이커가 방어 매도도 차단하는 R5-P4 한계는 이 게이트에도 적용(당일 손실한도 초과 시 자율 손절 정지=사람 호출) — 의도된 fail-closed, 별도 개선 안 함.

### 4.3 취소 락 통일 (I3)

두 취소 엔드포인트(`kr_stocks/analysis.py`의 cancel, coin 대응)를 결정 직렬화에 통합. 택1(구현 시 결정, 리포트 명시): (a) 라우트가 `approval.submit_decision(id, "cancelled")` 경유, 또는 (b) `_session_decision_lock(session_id)`를 approval.py에서 export해 라우트 본문을 감쌈. → 재분석 중 취소가 락 대기 후 참 상태를 봄, 인젝터 재무장 방지.

### 4.4 종결 세션 취소 거부 (I4)

zombie-cancel 분기(approval.py 9c57fca)를 "실제 awaiting-ish"일 때만 종결 마크: 레거시 딕셔너리 히트는 `session["status"]=="awaiting_approval"`, sm 히트는 `sm.status==AWAITING_APPROVAL` 요구. 종결(completed/error) 세션의 취소는 409("이미 처리됨 — 취소 불가"). F4a T4의 approved-거부 409와 통합(같은 초크포인트, 조건만 확장: approval_status=="approved" OR status가 이미 terminal).

### 4.5 코디네이터 활성 게이트 (I6 = 결정 2)

`services/autonomy/gate.py`의 kiwoom 분기(또는 check_autonomy 체인)에 7번째 fail-closed 링크: `app.dependencies._trading_coordinator_instance`가 None이거나 `coordinator.is_active`가 False → **거부**(`reason="사후 체결 추적 불가 — trading 시스템 미기동"`). `_default_risk_params`가 코디네이터를 얻는 기존 패턴 재사용. 자율 전용(actor=system 경로) — HITL 수동 승인은 코디네이터 없이도 가능해야 하므로 이 체크는 자율 주입 경로 또는 게이트의 autonomous 컨텍스트에만.

### 4.6 통지 정직화 + 재시작 카운트다운 정리 (I5+I7)

- **통지(I5)**: approval.py approved 분기가 `state["execution_status"]` 분기 — `"completed"`→기존 "체결" 문구, `"placed_pending_fill"`→"접수, 체결 대기(ord_no {n})" (broadcast_trade_queued 스타일), `"failed"`→거부/실패 문구. 자율 무인 운용의 유일 push 채널이 미발주를 "체결"로 오보하지 않게.
- **카운트다운(I7)**: F4a `reconcile_stranded_sessions`가 이미 복원 세션의 `auto_approve_at`을 클리어(공통 처리) — 그 지점에 reasoning 라인 추가("재시작으로 자율 승인 타이머 해제 — 수동 승인 필요"). adoption 경로(`_adopt_session_from_manager`)에도 동일 클리어 확인/보강. 재무장은 하지 않음(fail-closed).

### 4.7 max_positions 캡 F3 인지 (I2)

`gate.py`의 kiwoom positions_count_provider가 보유 티커 ∪ 코디네이터 `fill_tracker.tracking()`의 미체결 BUY 티커를 합산해 카운트. `_default_risk_params`의 코디네이터 획득 패턴 재사용. 30초 캐시 잔고 맹점을 미체결 추적으로 보완.

## 5. 테스트

- 각 컴포넌트 TDD, 실 Pydantic 픽스처(자기목 금지). 특히:
  - **4.1 경쟁 재현**: 느린 게이트/락 상황에서 스테일 system-approve가 제안 교체 후 ID 불일치로 stand-down(핀 없으면 잘못 승인 = RED). manual-wins.
  - **4.2**: 게이트 거부 시 미발주+감시 유지+통지 1회 래치; 허용 시 정상 방어 매도.
  - **4.5**: 코디네이터 None/inactive → 자율 승인 거부; active → 통과. HITL 경로 불변.
  - **4.4**: 종결 세션 취소 409; 정상 awaiting 취소 200.
- 회귀: agent_chat+autonomy 195, approval 스위트, r5_p0 게이트, F3 스위트.
- 라이브: F4b 배포 후 **통제된 페이퍼 자율 실험**(별도 승인) — 감사 산출 E2E 리허설 계획(전제조건: env 플립·모드·워치 종목·관찰 항목·킬스위치 5단계)을 §6에 첨부.

## 6. E2E 자율 실증 리허설 계획 (배포·별도 승인 후)

전제조건: `AUTONOMY_ENABLED=true` 재시작 + `PUT trading-mode kiwoom=autonomous` + `POST trading/start`(코디네이터 활성 — 이제 게이트 필수) + watch-list 소액 종목 + agent-chat start.
관찰 항목: 제안→60s 카운트다운 라이브 감소→auto_approved(actor=system)→placed_pending_fill 통지("접수, 체결 대기")→(체결 시)사후 등록 양엔진→거부권(유예 중 거부→stand-down)→핀 검증(거부 후 새 제안이 스테일 승인 안 됨).
킬스위치: ①모드 hitl 전환(즉시) ②AUTONOMY_ENABLED=false 재시작 ③trading/stop ④agent-chat/stop ⑤포지션 수동 청산.

## 7. 범위 밖

- **MINOR 잔여**(백로그): PM 방어 청산 0-fill 시 감시 드롭(A3 클래스, R5-P1 연장), zombie-cancel 미러 정직화(state 플래그+실패 표면화), WATCH 워치리스트 R5-P1 blob 영속, 인젝터 관측성 로그(400→info stand_down — 4.1에 일부 흡수), 스테일 auto_approve_at 미러 갱신 잔여.
- F4a P1(미러 정직화 전체·cancel 출처 c23b86dd·ka10076 정산).
- 브레이커 방어SELL 차단 재검토(R5-P4).
