# 3대 잔여 이슈 설계 — 매도 체결 배선(R5-P4) · 장외 완전 idle · 장마감 요약 통지

- 날짜: 2026-07-17
- 상태: 설계 확정 (사용자 결정 4건 반영)
- 전제: HEAD `922d6d0`(세션 SSOT 통합 배포 직후). 라인 앵커는 이 HEAD 기준 — 구현 시 심볼로 재확인.
- 진단 출처: 3-트랙 병렬 조사 워크플로우(라이브 storage.db 읽기 실측 포함, 2026-07-17)

## 0. 결정 레코드

| # | 결정 | 선택 |
|---|------|------|
| E1-D1 | 매도 사후 체결의 원장 표현 | **체결 단위 델타 append** (현 BUY 사후체결 방식과 통일 — 한 주문 여러 체결 행, SUM(executed_quantity)=브로커 누적 수렴, 이중계상 없음) |
| E2-D1 | 장외 idle 범위 | **완전 idle** — 토론 트리거뿐 아니라 PositionManager 30s 루프·RiskMonitor 1s 루프·워치 가격 갱신 루프의 시세 폴링까지 장외 중단 |
| E3-D1 | 장마감 리포트 FE 표면 | **PerformancePanel 섹션 확장** (신규 타일·레이아웃 범프 없음) |
| E3-D2 | 요약문 생성 | **LLM 서술형** — 단, 결정적 digest가 항상 선행 생성되고 LLM은 타임아웃+실패 시 템플릿 폴백 |
| 부속 | 동시호가(08:30~09:00) | closed 취급(현행 MarketHoursService 판정 그대로) |
| 부속 | 수동 토론(/discuss) | 장외에도 허용 — 자동 트리거 지점만 게이트하므로 구조적 예외 |
| 부속 | Telegram 게이트 | 신규 `TELEGRAM_NOTIFY_DAILY_SUMMARY: bool = True` (additive) |
| 부속 | digest 영속 | `eod_review.report_json`에 `digest`/`narrative` 섹션 추가(스키마 무변경, INSERT OR REPLACE 재사용) |
| 부속 | 마감 엣지 놓친 날 | 수동 트리거 `POST /api/trading/eod-report/run` (선례: /strategy/consensus/run). 기동 자동 백필은 스코프 아웃 |
| 부속 | 리밸런싱 SELL | 경로 유지 + `_apply_sell_fill` 경유 + **check_autonomy(SELL) 게이트 추가**(현재 자율 게이트 우회 — fail-closed 정렬) |
| 부속 | 과거 누락 114주 | 원장 소급 불가(ka10076=당일 한정) — **실현손익만** ka10074 기간 조회 1회성 백필 스크립트(dry-run 기본, 실행=사용자 승인) |

## 1. 이슈① 매도 체결 배선 (R5-P4 본체)

### 진단 (라이브 실측)
원장 매도 41주 vs 브로커 실매도 155주 = **114주 누락**(000660 7주+005930 107주), kr_realized_pnl 1행뿐. 근본 원인 단일: 원장 기록이 발주 직후 ~1.5초(ka10076 3회 확인 창) 체결분 1회로 끝나고, **SELL 사후 체결 발견 메커니즘이 의도적 부재** — fill_tracker 등록이 BUY 전용(`coordinator.py:712` `if side == OrderSide.BUY`, `execution.py:419` `_is_buy_action` 게이트, 'R5-P4 scope-out' 주석). 부차: 리밸런싱 SELL(`coordinator.py:531-538`)은 기록·포지션 차감·autonomy 게이트 전부 0. reconciler는 포지션 수량만 보정하고 원장은 안 씀(누락 흔적 없이 흡수). FE 거래내역=이 원장 단독 소스(`GET /kr_stocks/trades`).

### 설계
- **T1 — SELL 잔량 추적 등록**: pending/partial SELL 결과를 `TrackedOrder(side="sell")`로 fill_tracker에 등록. 사이트: ①`on_trade_approved` F3 블록(BUY-only 조건 제거) ②그래프 `execution.py` `_is_buy_action` 게이트 확장 ③`_close_position`/`_reduce_position`/`_execute_order_from_monitor`의 SELL 결과 — 공통 등록 헬퍼(`_track_unfilled(order, result)`)로 통일.
- **T2 — sell 델타 후처리**: `_poll_tracked_fills`(30s ka10076 폴)의 기록부는 이미 side 불문 → 유지. 델타 후처리 분기: sell 델타는 `register_fill_as_position`(포지션 증가) 대신 **포지션 차감 + `record_kr_realized_pnl`**(기존 `_apply_sell_fill`의 차감·실현손익 시맨틱 재사용 — 원장 기록은 폴 기록부가 담당하므로 이중 기록 금지 형태로 분리·재구성). E1-D1: 델타 행 append(주문당 여러 행), `order_id` 컬럼으로 그룹.
- **T3 — 리밸런싱 SELL 정합**: `check_autonomy(SELL)` 게이트(거부=미발주+로그) → 발주 시 `_apply_sell_fill(...)` 경유(기록+차감) → 잔량은 T1 헬퍼로 추적.
- **T4 — EOD 원장 대사 백스톱**: 마감 엣지 체인에 `reconcile_trade_ledger()` 스텝 — ka10076 당일 체결 스냅샷 vs `SELECT order_id, SUM(executed_quantity) FROM kr_stock_trades WHERE date=today GROUP BY order_id` diff → 누락 델타를 원장에 upsert(+실현손익 동반). idempotent(order_id 기준), never-raise, 폴이 놓친 잔여를 당일 내 회수.
- **T5(선택 스크립트)** — `backend/scripts/backfill_realized_pnl.py`: ka10074 기간 조회로 kr_realized_pnl 과거 누락 백필(dry-run 기본, 실행=사용자 승인). 원장 행 소급 생성은 하지 않음(체결 시각·단가 소급 불가).

### 불변식
- BUY 경로 거동 byte-불변(등록 조건 완화만). `_apply_sell_fill`의 전량제거/부분차감/미체결유지 시맨틱 불변. fee=0 현행 유지(net 손익은 ka10074 소스 — 기존 P2-4 체계 무변경).
- 이중계상 금지: 발주 시 기록분(1.5초 창)과 사후 델타의 합 = 브로커 누적. 폴 기록은 "이전 폴 이후 증가분"만(현 BUY 방식 그대로).

## 2. 이슈② 장외 완전 idle

### 진단 (라이브 실측)
최근 3일 장외 시간대에만 토론 ~79건(전부 NO_ACTION). 원인: ①`_check_watch_list`(1분 주기) 기회 판정이 장외 가격 동결로 영구 참→30분 스로틀 주기 재발화 ②`_check_strategic_reeval` 순수 벽시계 30분 조건. MarketHoursService(KRX 09:00-15:30, 주말+동적 공휴일+폴백)가 완비돼 있으나 agent_chat 계층 미사용. agent_chat은 kiwoom 전용(coin 참조 0건) — 게이트의 coin 오차단 불가.

### 설계 (E2-D1: 완전 idle — no-op-cycle 패턴)
루프/스케줄 자체는 유지하고 각 사이클 선두에서 `is_market_open(KRX)` false면 skip(조기 return). 스케줄러 수술 없음, 개장 첫 사이클에 자동 재개.

게이트 지점 전수 (5):
1. `agent_chat/coordinator.py::_check_watch_list` 선두 — 토론 스팸 주범.
2. `agent_chat/position_manager.py::_check_strategic_reeval` 선두 — 벽시계 재평가(베이스라인 리셋도 하지 않음 → 개장 직후 due 처리).
3. `agent_chat/position_manager.py::_check_all_positions`(30s 루프 본체) 선두 — 방어 감시 포함 전체 skip. **결과: 장외 손절/익절 감시 중단** — 장외엔 체결 불가(KRX day-order)라 안전하고, 개장 첫 30s 사이클에 즉시 재개(갭 대응은 어차피 개장 후 첫 틱).
4. `services/trading/risk_monitor.py::_monitor_loop` 사이클 선두 — 1s 시세 폴링 중단.
5. `agent_chat/coordinator.py::_watch_refresh_loop` 사이클 선두 — 워치 가격 갱신 폴링 중단.

공통 구현: `services/trading/market_hours.py`에 얇은 헬퍼 `is_krx_open_cached(ttl=30s)`(분당 수백 회 호출되는 RiskMonitor 1s 루프 대비 판정 캐시 — 공휴일 서비스 재조회 방지). 게이트 로그는 상태 전이 시 1회만(open→closed/closed→open, 사이클마다 로그 금지).

게이트 금지(명시적 비대상): trading coordinator `_queue_scheduler_loop`(open/close 엣지 감지·EOD 체인·큐 처리의 심장 — 절대 게이트 금지), `_poll_tracked_fills`(마감 직후 최종 회수 필요 — 기존 마감 엣지 로직 유지), reconciler, 수동 `/discuss` 라우트, coin 스택 전체.

## 3. 이슈③ 장마감 요약 통지

### 진단
마감 엣지 체인(스냅샷→EOD리뷰→전략합의) 완성·재료 전부 실존: eod_review.report_json(portfolio/per_stock/regime), strategy_revisions 최신 행(stance·3패널리스트 한국어 rationale·노브), 워치리스트/계좌/보유 API. 갭: 조립기·통지 스텝·FE 노출 API·FE 표면.

### 설계
- **T6 — `services/trading/eod_digest.py`**: `build_eod_digest(coordinator, storage) -> dict` 순수 조립(never-raise, 섹션별 null 내성): ①watch: 종목별 signal/confidence/현재가 vs 타깃 ②account: 예수금·총평가·당일 실현손익(daily_perf_snapshot)·누적수익률 ③holdings: 수량·평단·현재가·평가손익·스탑/타깃(portfolio_summary 관점) ④strategy: 익일 stance·rationale 발췌·핵심 노브 변화(strategy_revisions 최신) ⑤regime: 시장심리 라벨·지수 등락(있으면).
- **T7 — LLM 내러티브(E3-D2 책임설계)**: `narrate_eod_digest(digest) -> Optional[str]` — 기존 LLM 라우터(`generate` 계열, strategy_panel 관례) 재사용, 한국어 브리핑 1편(400~800자), `asyncio.wait_for(120s)` + never-raise. **실패/타임아웃 시 None → 모든 소비자(Telegram/FE)는 결정적 템플릿 렌더로 폴백.** digest·narrative 모두 eod_review.report_json에 추가 저장.
- **T8 — 마감 체인 통지 스텝**: coordinator 마감 엣지에서 `run_strategy_consensus` 직후 — digest 조립→narrative 시도→저장→`telegram.send_daily_summary(digest, narrative)`(신규 타입드 메서드, `TELEGRAM_NOTIFY_DAILY_SUMMARY` 게이트, Markdown 4000자 분할 기존 API)→`broadcast_eod_summary(...)`(TradeNotificationManager 재사용, `eod_summary` 타입). 전 스텝 never-raise(기존 체인 관례).
- **T9 — API**: `GET /api/trading/eod-report?date=`(기본 최신) — report_json(digest·narrative 포함) 반환. `POST /api/trading/eod-report/run` — 수동 재생성+재통지(마감 엣지 놓친 날/재시작 대비).
- **T10 — FE**: ①`useTradeNotifications.ts` 타입 유니언에 `eod_summary`+토스트/벨 렌더 ②`PerformancePanel.tsx`에 "EOD 리포트" 접이식 섹션(getEodReport — narrative 우선 표시, 없으면 digest 템플릿 렌더, 날짜 셀렉터는 최신만 v1) ③`client.ts` getEodReport.

### 주의
- 요약의 당일 거래·실현손익은 **daily_perf_snapshot/ka10074 계열 소스** 사용(kr_stock_trades 직접 집계 금지 — 이슈① 수정 전 데이터 왜곡 방지, 수정 후에도 브로커 소스가 권위).
- 이슈② 완전 idle과의 상호작용: 마감 엣지 체인은 trading coordinator 소관(게이트 비대상)이므로 요약 생성·발송은 장외 idle과 무관하게 동작.

## 4. 실행 순서·의존
E2(장외 idle — 독립·즉효) → E1(체결 배선 T1~T4) → E3(요약 T6~T10, T4의 EOD 대사와 같은 마감 체인에 인접하므로 E1 후). T5 백필 스크립트는 맨 뒤(선택). 배포는 전체 1회(사용자 승인) 권장.

## 5. 테스트 전략
- E1: TDD — sell 잔량 등록(경로별), 폴 sell 델타(차감+실현손익+원장 append), 이중계상 금지(발주기록+델타 SUM=브로커), 리밸런스 게이트+기록, EOD 대사 idempotent. 모의 ka10076 페이로드 픽스처.
- E2: MarketHoursService monkeypatch(open/closed) — 5지점 각각 skip/재개, 상태전이 로그 1회, 수동 /discuss 비게이트, coin 무영향(구조적).
- E3: digest null 내성(빈 워치/에이전트/수급), narrative 타임아웃→템플릿 폴백, Telegram 게이트 플래그, report_json 왕복, FE 타입·렌더(vitest).
- 공통: conda agentic-trading, 타깃 파일만 FOREGROUND, 실 DB 격리.

## 6. 비변경
autonomy gate 체인(강화만: 리밸런스 SELL 게이트 추가), EOD 기존 스텝 순서(신규 스텝은 append), FE status 5-Literal, kr_stock_trades 스키마(컬럼 무변경 — order_id 기존 활용), reconciler의 포지션 대사 역할, coin 스택, 세션 SSOT 산출물 전부.
