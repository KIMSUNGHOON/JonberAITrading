# 갭 규율 설계 — 갭 관통 스탑 보존 + 감시 정합 픽스

- 날짜: 2026-07-20
- 상태: 설계 승인됨 (사용자 "승인")
- 전제: HEAD `1dfed17`(생존 규율 아크 배포됨, PID 64801). 개장 첫날 실전 발현 엣지의 근본 수정.
- 배경(실측): 2026-07-20 00:02 재시작 복원에서 `restore_stops_insane_dropped ticker=000660 stop_loss=1,807,923 current_price=1,782,000` — PM 인상 스탑이 프리오픈 갭 가격에 뚫려 드롭됨(S-5 최종리뷰 Important 예측 적중). 가격은 1,824,000으로 반등해 이번엔 유리했으나 손절 규율 위반이 우연히 이득이 된 것. + /halt·deny 상태에서 허위 "Stop-Loss Executed" 알림 무한 생성(N2)·PM 가드스킵 시 감시 공백(N3)·r_cap stop≤0 미가드(N4)·락인 관측성 부재.

## 0. 결정 레코드 (사용자)
| # | 결정 | 선택 |
|---|------|------|
| D1 | 갭 관통 정책 | **스탑 원본 보존** — 복원 시 스탑 그대로 유지, 발동 판정은 장중 감시 루프 정상 로직 위임(개장가<스탑=규율대로 즉시 손절, 위=높은 보호선 유지). 반등 베팅(현행 드롭+재산출) 기각, 즉시 강제 청산 마커도 기각(프리오픈 노이즈 취약) |
| D1b | tp 갭업 대칭 보존 (2026-07-20 추가 채택) | 익절가 갭업(take_profit ≤ 현재가) 엔트리도 **원본 보존** — 손절과 대칭. 무해 근거: 익절=토론 트리거뿐(자동 매도 없음), 보존 시 S-5 락인 트리거·동반 스탑 유지. 구조적 위법은 가격≤0·stop≥take_profit만 잔존 |

## 1. 실측 앵커 (S 아크 최종리뷰+오늘 라이브 — 라인은 태스크 시작 시 재확인)
- restore: `position_manager.py` `restore_stop_overlay`(:2347 부근) — 엔트리 단위 `_stops_sane` 실패 시 `continue`로 **스탑·take_profit_reached_at 통째 드롭**(주석은 "reached_at 미적용" 주장 — 불일치). `_stops_sane`(:1132-1154 부근)=현재가 대비 위법 검사 포함.
- N2: `risk_monitor.py` `_execute_stop_loss/_execute_take_profit`(:545-621 부근)이 `coordinator._execute_order_from_monitor`(반환값 없음) 호출 후 **무조건** "Stop-Loss Executed: Sold N shares" ORDER_FILLED 알림 생성. deny/인플라이트 스킵은 조용히 return이라 구분 불가. `coordinator._on_alert`(:1876-1878 부근)가 action_required=False 알림을 dedup 없이 `_state.pending_alerts`에 매 틱 append — /halt+손절가 하회 시 초당 무한 성장.
- N3: PM `_execute_close_position`(:1262-1265 부근)이 coordinator `_close_position` 반환 None(인플라이트 스킵/포지션 미발견)이어도 무조건 PM 감시 remove — reconciler 재편입까지 최대 60초 공백.
- N4: `r_sizing.py::r_cap_value` — stop_price≤0이면 거리 100%로 계산(캡이 equity×0.75%로 붕괴 — 보수 방향이나 의외 동작).
- 락인: `_apply_take_profit_lock_in` 성공 시 로그·이벤트 0(기존 %트레일링은 TRAILING_STOP_UPDATE 발행 — 비대칭).

## 2. 태스크 설계
### G-1 restore 스탑 원본 보존 + reached_at 독립 복원
- `restore_stop_overlay`: sanity 검사를 2계층 분리 — **구조적 위법**(가격≤0·stop≥take_profit 등 — 실 _stops_sane 구성 확인 후 분류)만 드롭, **갭 관통**(stop≥현재가)은 보존+`gap_through_stop_restored` info 로그(티커·스탑·현재가). 발동은 감시 루프 위임(코드 무변경 — current≤stop이면 STOP_LOSS_HIT 정상 발화).
- take_profit_reached_at은 스탑 sanity와 **독립 복원**(구조적 위법 엔트리도 reached_at은 살림 — 필드 자체가 위법 개념 없음). 주석-구현 일치화.
- **장중 신규 설정 경로(_stops_sane via update_position)는 byte-불변** — 락인·토론발 스탑 설정의 즉시 발동 방지 유지.

### G-2 허위 실행 알림 봉합 (N2)
- `_execute_order_from_monitor` → `bool` 반환(주문 제출=True, deny/인플라이트 스킵=False). **예외는 전파 유지**(리뷰 판정: False 치환 시 기존 ORDER_FAILED 알림 경로가 사장됨 — 전파가 옳음). 기존 호출부 하위호환(반환 무시 호출 무해).
- `_execute_stop_loss/_execute_take_profit`: False면 "Executed" 알림 미생성(1회 래치 deny 통지는 기존 유지). 성공 시 기존 알림 불변.
- `_on_alert`의 pending_alerts: 동일 (ticker, alert_type) 미해결 항목 존재 시 append 스킵(dedup — action_required 무관). 기존 소비자(FE pending_alerts_count·알림 처리) 거동 확인.

### G-3 경량 3건
- N3: PM `_execute_close_position`에서 coordinator 반환 None이면 remove 스킵+warning(감시 유지 — 다음 틱/1차 엔진이 처리). 정상 완료 시 기존 remove 불변.
- N4: `r_cap_value`에 `stop_price <= 0 → None` 가드+테스트.
- 락인 성공: info 로그(`take_profit_lock_in_applied` — 티커·구스탑·신스탑)+기존 이벤트 발행 관례 대칭(TRAILING_STOP_UPDATE 재사용 또는 동급 — 실코드 관례 확인).

## 3. 비변경 불변식
- 손절 자동 실행·게이트 체인·MARKET·R 사이징·계보·인플라이트 가드 전부 무접촉. HITL 폴백·래치 불변.
- 테스트 실 DB 금지(isolated_storage_service·트립와이어 206).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 보존된 갭 관통 스탑이 개장 직후 발동 | **의도된 동작**(D1 규율 우선) — 사용자 승인됨 |
| pending_alerts dedup이 정당 알림 억제 | 미해결 동일 (ticker,type) 한정 — 해결되면 재생성 가능, 테스트 핀 |
| restore 완화가 쓰레기 스탑 부활 | 구조적 위법 계층은 유지 — 분류 테스트 |
