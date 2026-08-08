# 순 실현손익(net) — 학습 신호가 거래비용을 무시하던 것 봉합

브랜치 `fix/net-realized-pnl` (base `609b9b9`) · 워크트리 `.claude/worktrees/net-pnl`

---

## 상태

완료. 5개 수정 지점 전부 배선, 회귀 0(기존 실패와 정확히 동일한 집합),
각 지점의 RED 확인 완료.

## 무엇이 바뀌었나

`kr_realized_pnl.realized_amount = (exit − entry) × qty`는 순수 gross였고,
그 값이 그대로 `agent_chat_decisions.outcome_realized_pnl`로 백필돼
`calibration.py`의 정오답 채점 → 전략 재가중으로 흘러갔다. 비용을 못 넘긴
거래가 "승리"로 학습됐다.

이제 `realized_amount`(gross)는 그대로 두고 `fee`/`tax`/`net_amount`를
나란히 적으며, **결정 백필과 승패 카운터는 net을 쓴다.**

| # | 파일 | 내용 |
|---|------|------|
| ① | `backend/services/storage_service.py` | `kr_realized_pnl`에 `fee`/`tax`/`net_amount`/`cost_source` 4개 컬럼 — 기존 `_ensure_columns` 선례(`kr_stock_trades`의 `tax`/`cost_source`, 573~583행) 그대로 재사용. `save_kr_realized_pnl` INSERT 확장. |
| ② | `backend/services/trading/trade_log.py` | `record_kr_realized_pnl_async`가 `compute_fill_cost`로 왕복 비용 산정 → `record`에 담고 **`update_decision_outcome(entry_decision_id, net_amount)`**. |
| ③ | `backend/services/trading/eod_snapshot.py` | `_count_win_loss_trades`가 `net_amount` 부호로 세되, NULL(레거시 행)이면 `realized_amount`로 폴백. |
| ④ | `backend/scripts/backfill_net_realized_pnl.py` (신규) | 기존 25행 일회성 백필 + 결정 outcome 재백필. dry-run 기본, `--apply`로 적용. |
| ⑤ | `backend/services/trading/calibration.py` | `_decision_label` docstring에 "입력이 이제 net이므로 이 문턱은 비용이 아니라 잡음 대역이다" 명기. `EOD_FLAT_THRESHOLD_KRW`는 **미변경**. |

### 바꾸지 않은 것

`realized_amount`(gross)의 값·의미 / `cost_model.compute_fill_cost` 본문 /
`PaperFillSettings` 요율 / `kr_stock_trades` 비용 경로 /
`daily_perf_snapshot`(브로커 net) / `_decision_label`·`_vote_hit` 로직 /
`EOD_FLAT_THRESHOLD_KRW = 10000.0`.

---

## 마이그레이션 실행 위치와 근거

**결정: 별도 스크립트 `backend/scripts/backfill_net_realized_pnl.py`**
(`initialize()` 안이 아님).

근거 — 이 리포의 선례가 **DDL은 `initialize()`, DML은 `scripts/`** 로
갈라져 있다:

1. **선례 2건이 전부 스크립트다.** `backend/scripts/backfill_realized_pnl.py`
   (ka10074 과거 실현손익), `backend/scripts/backfill_trades_20260713.py`
   (체결 4건). 둘 다 dry-run/멱등 id 관례를 갖고, 테스트도
   `tests/test_scripts/` 아래에 있다(`test_backfill_realized_pnl.py`,
   `test_cleanup_session_stores.py`) — 즉 "일회성 데이터 마이그레이션은
   테스트 가능한 스크립트로 만든다"가 확립된 관례다.
2. **`initialize()`에는 값 마이그레이션 전례가 0건이다.** `_ensure_columns`는
   자기 독스트링에서 "SQLite ADD COLUMN은 기존 행을 상수로만 채울 수 있다"고
   한계를 명시하면서도 뒤따르는 UPDATE를 단 한 번도 붙이지 않았다. 그 파일의
   `initialize()`는 CREATE TABLE / ALTER / CREATE INDEX만 한다.
3. **이 백필은 학습 원장(`agent_chat_decisions`)까지 쓴다.** 프로세스가 뜰
   때마다 저수준 스토리지 생성자에서 조용히 실행될 성질이 아니고,
   `tests/conftest.py`의 L-6 트립와이어가 경계하는 바로 그 표면이다.
4. 부수 효과: `_BACKFILL_STK_CD_SENTINEL`을 `services/storage_service.py`에서
   임포트하면 `storage_service → services.trading.__init__ → coordinator →
   storage_service` 순환이 생긴다. 스크립트는 `services/`에서 **단방향으로**
   임포트하므로(`eod_snapshot.py`의 주석이 명시한 그 방향) 상수를 재정의하지
   않고 그대로 쓸 수 있다.

스키마(①)만 `initialize()`에 있고, 앱이 아직 재기동하지 않아 컬럼이 없는
DB에서도 스크립트 단독으로 완결되도록 `apply` 경로에서만 같은 ALTER를
수행한다(dry-run은 스키마를 건드리지 않는다).

### 라이브 DB **복사본** 대상 검증 (실 DB 미변경, mtime 08:17 그대로)

```
전체 행: 26  후보: 25  이미 net 있음(skip): 0  센티널 'ALL'(skip): 1
  [005930] gross=+22,008 fee=6,120 tax=35,216 -> net=-19,328  <== 부호 반전
부호가 뒤집히는 행: 1
결정 outcome 재백필 대상: 7
  -> 원장 25행, 결정 5행 갱신됨      (7 중 2건은 결정 행 자체가 이미 없음)

2회차: 후보 0 / 원장 0행 / 결정 0행 갱신  ← 멱등
```

명세의 삼성전자 케이스가 그대로 재현됐다(fee 6,120 · tax 35,216 ·
net −19,328). 결정 outcome 5건 변화:

| 결정 | 종목 | before (gross) | after (net) |
|------|------|---------------:|------------:|
| 995715e1 | 049070 | −208,086 | −218,098 |
| 96253449 | 093190 | +174,071 | +168,711 |
| be0c669b | 094840 | +69,655 | +66,377 |
| fa842320 | 090430 | +14,200 | +13,461 |
| 8892bb2c | 068270 | +639,716 | +616,282 |

부호가 뒤집힌 005930 행(`de838ed9`)은 **결정 행이 이미 존재하지 않아**
실 DB에서는 학습 신호가 바뀌지 않는다 — 원장만 net으로 정정된다.

---

## 설계 판단 2건 (명세에 없던 것)

### (a) 부분체결 슬라이스의 결정 백필 = "마지막 체결이 이긴다"

한 `entry_decision_id`에 여러 행이 달리는 것이 라이브의 정상 형태다(049070은
6행). 런타임의 `update_decision_outcome`은 합산이 아니라 **덮어쓰기**이므로
실제 저장된 값은 항상 마지막 체결의 것이다(실 DB 대조로 확인: 049070 =
−208,086 = exit_at 최댓값 행). 백필도 같은 규칙(`exit_at` → `created_at` →
`id` 순 최댓값)을 써서, **gross→net 이상의 의미 변화가 생기지 않게** 했다.

### (b) `cost_source = "model_unavailable"` 세 번째 값

명세는 `'model' | 'model_backfill'` 두 값을 요구했다. `compute_fill_cost`는
순수 함수지만 `get_paper_fill_settings()`(pydantic BaseSettings — 환경변수가
깨지면 ValidationError)를 호출하므로, 그게 터지면 **원장 행 자체를 잃는다**
— never-raise 계약은 지켜지지만 결과는 더 나쁘다. 비용 산정만 실패로 두고
(net = gross, `cost_source="model_unavailable"`) 기록은 계속하도록
`_compute_realized_costs`에 내부 가드를 넣었다. 테스트
`test_cost_model_failure_does_not_lose_the_ledger_row`가 이걸 잡는다.

---

## 테스트

신규 21개 전부 통과 (`tests/test_services/test_trading/test_net_realized_pnl.py`
10개 + `tests/test_scripts/test_backfill_net_realized_pnl.py` 11개).
둘 다 `pytestmark`에 `usefixtures("isolated_storage_service")`.

기존 3개는 **gross가 결정으로 흘러가는 것을 명시적으로 검증하던 테스트**라
새 계약으로 갱신했다(명세의 의도적 동작 변경):

- `test_lineage_e2e.py::test_analysis_path_full_lineage_e2e` (50,000 → 47,985)
- `test_lineage_e2e.py::test_agent_chat_path_full_lineage_e2e` (−70,000 → −71,715)
- `test_kr_realized_pnl.py::test_record_kr_realized_pnl_async_backfills_decision_outcome`
  (5,555 → 3,615)

세 곳 모두 원장의 gross 단언은 **유지**하고 net 단언을 추가했다.

### RED 확인 (각 수정 지점을 되돌렸을 때 실패하는 테스트)

| 되돌린 것 | 실패한 테스트 |
|-----------|---------------|
| ② `update_decision_outcome(net_amount)` → `realized_amount` | **5건**: `test_decision_outcome_backfill_uses_net_not_gross` (22008 ≠ −19328) · `test_decision_outcome_backfill_passes_net_to_storage_call` · `test_record_kr_realized_pnl_async_backfills_decision_outcome` · `test_analysis_path_full_lineage_e2e` · `test_agent_chat_path_full_lineage_e2e` |
| ③ `net_amount` 폴백 제거 (gross만 사용) | **2건**: `test_gross_win_becomes_net_loss_in_win_loss_counter` (1,0)≠(0,1) · `test_net_amount_wins_over_gross_when_both_present` |
| ① `_ensure_columns(kr_realized_pnl, …)` 제거 | **8건**: `test_records_exact_model_costs_for_live_samsung_row` · `test_gross_win_becomes_net_loss_…` · `test_legacy_row_without_net_amount_falls_back_to_gross` · `test_net_amount_wins_over_gross_…` · `test_zero_quantity_leaves_net_equal_to_gross` · `test_cost_model_failure_does_not_lose_the_ledger_row` · lineage e2e 2건 |
| ④ `'ALL'` 센티널 필터 제거 | **1건**: `test_all_sentinel_row_untouched` (123456.0 is not None) |
| ④ 멱등 가드 2종 제거 (`already_net` continue + `WHERE net_amount IS NULL`) | **3건**: `test_backfill_is_idempotent` · `test_second_run_does_not_clobber_a_newer_decision_outcome` (−19328 ≠ 777) · `test_plan_is_pure_and_skips_rows_that_already_have_net` |

### 회귀 — base `609b9b9`와 대조

`/tmp/net-pnl-base`에 base 커밋을 detached worktree로 체크아웃해 **같은
명령으로 동일 스위트**를 돌려 비교했다(`git stash` 미사용, 작업 후 worktree
제거 완료).

```
base 609b9b9 :   9 failed, 2420 passed, 21 errors
this branch  :   9 failed, 2441 passed, 21 errors
```

**실패/에러 집합이 완전히 동일하다** — 아래 9 FAILED + 21 ERROR는 전부 이
브랜치 이전부터 있던 것이다(신규 회귀 0, 신규 통과 +21).

기존 실패 9건: `test_decision_ledger.py::test_calibration_naturally_excludes_analysis_rows_from_per_agent` ·
`test_discovery_ranker.py::test_promoted_candidate_triggers_detect_opportunity_end_to_end` ·
`test_f3_fill_tracking.py::test_pending_buy_registers_tracked_order` ·
`test_f3_fill_tracking.py::test_partial_buy_registers_position_and_remainder` ·
`test_kiwoom/test_cache.py::test_cache_stats` · `…::test_reset_stats` ·
`test_kiwoom/test_rate_limiter.py::test_token_refill` ·
`test_trading/test_graph_strategy_consumption.py::test_detect_opportunity_uses_strategy_thresholds` ·
`test_trading/test_strategy_panel.py::test_context_includes_discovery_performance_summary`

기존 에러 21건: `test_checkpoint_gc.py` 3 · `test_discovery_orchestrator.py` 3 ·
`test_f3_fill_tracking.py` 1 · `test_r5_p0_autotrade_safety.py` 1 ·
`test_scanner_discovery_mode.py` 1 · `test_trading/test_cost_basis_reconcile.py` 1 ·
`test_trading/test_fill_notification.py` 1 · `test_trading/test_kr_realized_pnl.py` 4 ·
`test_trading/test_liquidity_sizing_wiring.py` 3 · `test_trading/test_order_failure_notify.py` 1 ·
`test_trading/test_risk_monitor_gate.py` 2 (전부 `caplog`/픽스처 관련, 이 태스크와 무관)

---

## 우려사항 / 잔여

1. 🔴 **배포 순서.** 라이브에 적용하려면 ①앱 재기동(→ `_ensure_columns`가
   컬럼 추가) → ②`python scripts/backfill_net_realized_pnl.py --apply`
   순서다. 스크립트가 컬럼을 스스로 추가할 수 있으므로 역순도 동작하지만,
   **실행 전 `storage.db` 백업**을 권한다 — 이 스크립트는 학습 원장
   (`agent_chat_decisions`)을 쓰는 유일한 백필이다.
2. 🟡 **기록 경로와 백필이 서로 모르는 창.** 봉합된 `trade_log`가 배포된
   뒤 백필을 돌리기 전까지 새로 쌓인 행은 `cost_source='model'`, 그 이전
   행은 NULL이다. 백필은 `net_amount IS NULL`만 보므로 두 집합이 섞여도
   안전하다(테스트 `test_plan_is_pure_and_skips_rows_that_already_have_net`).
3. 🟡 **`kr_realized_pnl`은 거래가 아니라 부분체결 슬라이스다**(기존 기록
   참조). 이 태스크는 그 구조를 바꾸지 않았다 — 승패 카운터는 여전히
   슬라이스 단위로 세고, 결정 백필도 여전히 마지막 슬라이스만 반영한다.
   즉 **비용은 정정됐지만 "왕복 1건 = 여러 행" 문제는 그대로**다. 명세가
   그렇게 요구했고 의미 변화를 최소화한 결과지만, 별건으로 남는다.
4. 🟡 **모의 브로커 요율(왕복 0.90%)과의 괴리는 의도적**이다. 이 값들은
   `daily_perf_snapshot`(브로커 net)과 일치하지 않는다 — 그건 봉합 대상이
   아니라 두 원장이 서로 다른 질문에 답하기 때문이다(학습 신호 vs 실제
   계좌). `cost_source`가 어느 쪽인지 남기므로 나중에 브로커가 체결 단위
   수수료를 주면 갈아탈 수 있다.
5. 🟢 `EOD_FLAT_THRESHOLD_KRW = 10000.0`은 미변경. 090430 결정이 백필 후
   13,461로 문턱을 여전히 넘으므로 라벨(`correct`)은 안 바뀐다.
