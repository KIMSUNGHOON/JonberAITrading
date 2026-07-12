# R5-P1: 실행 신뢰성 (2026-07-13)

자동매매 모델 감사(`2026-07-12-autotrade-model-audit.md`) A3/A4 + 개장 큐
스케줄러 + 매도 실패 시 포지션 유지. R5-P0(A1/A2/A5, `c39ba82`) 후속.
"R5-P1 승인" = 감사가 명시한 설계의 실행 지시. TDD + 적대적 리뷰.

패턴: R5-P0가 "번역/방향" 결함이었다면 R5-P1은 "상태 신뢰성" — 실행 결과를
사실대로 반영하고(체결), 재시작을 견디고(영속), 시간 경계를 넘긴다(개장).

## 정찰로 확정한 근본 원인

- **A3-체결**: `order_agent._execute_kiwoom_order:384-393` — 어댑터 `place()`가
  성공(=접수)을 반환하면 `filled_quantity=order.quantity`(전량 체결 가정),
  `avg_price=order.price`(지정가 체결 가정). 실제 체결은 비동기. ka10075(미체결)/
  ka10076(체결)이 Phase A에서 완비(`get_filled_orders(stk_cd)` → FilledOrder
  `ord_no`/`ccld_qty`/`ccld_uv`).
- **A3-매도실패**: `coordinator._close_position:856` — `_execute_order` 후
  **체결량 무관하게 `_remove_position` 무조건** 호출. 매도 미체결에도 포지션 소실.
- **A4-영속**: `_refresh_account_info`는 계좌 총액만 세팅하고 `_state.positions`를
  브로커 보유로 재구성하지 않음 → 재시작 시 포지션·스탑·큐·일일카운트 전부
  인메모리 소실 → 리스크 모니터 무감시. storage_service에 KR 포지션/큐 테이블 없음
  (coin_positions는 있음). 영속 시임: `get_app_setting`/`set_app_setting`(SQLite).
- **스케줄러**: `coordinator.start():175-179`는 기동 시 시장 열림+큐 있으면 1회
  처리. 실행 중 **개장 전이는 미감지**. risk_monitor 루프=1s 주기.

## 구현 계획 (순차 TDD)

### t1 — A4 영속 (positions+stops / queue / daily-count)
- storage_service: 코디네이터 상태 blob 저장/조회
  (`trading:coordinator_state` JSON — positions[model_dump]/trade_queue/
  daily_trades_count/daily_count_date). app_settings 재사용(신규 테이블·마이그레이션
  없음, 단일 사용자 paper 규모에 적정).
- coordinator: `_persist_state()`(각 변이 후: _add_position/_remove_position/
  add_to_queue/큐 상태전이/daily_trades_count 증가) + `_restore_state()`(start에서
  1회: positions 재적재→risk_monitor.add_position 재등록, queue 복원, 일일카운트
  날짜≠오늘이면 0 리셋). 브로커 재구성이 아니라 **로컬 상태 자체를 영속**(스탑은
  브로커가 모르므로 로컬이 유일 소스).

### t2 — A3 매도 실패 시 포지션 유지 (순수 correctness)
- `_close_position`: `_execute_order` 결과의 `filled_quantity`로 분기 —
  전량 체결 시 제거, 부분 체결 시 수량 차감(유지), 미체결 시 **유지**(경고 로그).
- `_execute_order_from_monitor`(손절/익절 실행): 이미 filled>0 가드 있음 —
  부분 체결 시 수량 차감으로 강화.

### t3 — A3 체결 확인 루프 (ka10076)
- kiwoom 체결 확인: 배치 성공(접수) 후 `get_filled_orders(stk_cd=ticker)`를
  `ord_no` 매칭으로 조회해 실제 `ccld_qty` 합산·평균단가 산출. 유한 재시도
  (기본 3회×짧은 간격), 타임아웃 시 status="pending"/부분(체결 가정 금지).
- order_agent `_execute_kiwoom_order`: place 성공 후 확인 단계 삽입 —
  확인 실패/미체결이면 filled_quantity=확인값(0 포함), avg_price=실제 체결가.
  주입 가능한 확인기로 테스트(타이밍 비의존).

### t4 — 개장 큐 스케줄러
- coordinator: start()에서 경량 주기 태스크 기동(stop()에서 취소) — ~30s마다
  KRX 세션 확인, **닫힘→열림 전이 엣지** 감지 시 큐 있으면 process_trade_queue.
  마지막 개장 상태 추적. 재게이트(R5-P0)가 실행 시점 안전 재확인.

## 적대적 리뷰 수정 (4차원 워크플로, 8 CONFIRMED / 2 REFUTED)

리뷰가 t1-t4의 통합 결함 8건을 확증 — 전부 봉합(TDD 7테스트 추가):

- **#1 캐시가 체결확인 재시도 무력화**: `get_filled_orders`가 5s 캐시라
  1.5s(3×0.5s) 재시도가 동일 스냅샷만 봄 → 비동기 체결 유실. `use_cache`
  파라미터 추가, `_confirm_kiwoom_fill`이 `use_cache=False`로 매 폴 최신 조회.
- **#3 startup 드레인 영속 순서**: `_persistence_active=True`가 개장 큐 드레인
  *뒤*에 설정 → 드레인 실행분 미영속 → 크래시 시 중복 매수+스탑 소실.
  플래그를 `_restore_state` 직후(드레인 전)로 이동.
- **#4 ADJUST_STOP_LOSS 미영속**: 모니터 WatchConfig만 갱신하고 ManagedPosition은
  미갱신 → 재시작 시 조정 되돌림. ManagedPosition.stop_loss도 갱신+영속.
- **#5b RiskMonitor가 reduce 클로버**: `_execute_stop_loss/_take_profit`가 executor
  호출 후 **무조건 `remove_position`** → `_apply_sell_fill`이 재등록한 부분체결
  잔량/유지된 미체결 포지션을 삭제. 무조건 제거 삭제 — executor(코디네이터)가
  실체결 기준으로 모니터 생명주기 소유.
- **#8 EXECUTE_STOP_LOSS/TAKE_PROFIT 무조건 제거**: 사용자 확정 청산 경로가
  t2 미커버 → 미체결에도 고아. `_apply_sell_fill`로 통일.
- **#6 process_trade_queue 재진입**: t4로 start()/스케줄러/수동 3경로 도달 →
  동시 호출 시 PENDING/PROCESSING 중복 실행. `_processing_queue` 가드 래퍼.

REFUTED 2: 브로커-로컬 정합(범위 밖 잔여), 빈 ord_no 폴백(도달 희박).

## 잔여(범위 밖)
- 브로커 보유 vs 로컬 포지션 정합(외부 매매 반영), WS 체결 이벤트 실시간 반영,
  미체결 SELL 재발주 in-flight 가드(auto-exec 모드), coin 실현손익 소스,
  브레이커 미실현/방어SELL 예외(R5-P4).
