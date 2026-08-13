# 결정↔체결↔손익 계보(lineage) 복원 설계 — P0 측정 회복

- 날짜: 2026-07-19
- 상태: 설계 승인됨 (사용자 "승인합니다")
- 전제: HEAD `3acaa25`. 전략 검토 3-트랙 실측(2026-07-19)+계보 초크포인트 정밀 디스커버리 근거.
- 배경: kr_stock_trades·kr_realized_pnl의 decision_id 계열 100% NULL, agent_calibration 0행 — 캘리브레이션·EOD 리뷰·전략 합의 폐루프가 데이터 없이 공회전. 원인=계보가 6곳(A~F)에서 끊김+ID 네임스페이스 분열.

## 0. 결정 레코드
| # | 결정 | 내용 |
|---|------|------|
| D1 | **A안: 통합 결정 원장** | agent_chat_decisions를 모든 매매 결정의 durable 원장으로 승격 — `decision_source` 컬럼('agent_chat'/'analysis') 추가, LangGraph 승인 실행 시 컴팩트 결정 행 영속(신규 uuid). 근거: 세션은 GC로 삭제(P5)라 세션 ID 계보=매달린 포인터, 소비자 단일 테이블화. B안(네임스페이스 병존+분기) 기각 |
| D2 | 진입 계보 1순위 | 캘리브레이션 실소비는 entry_decision_id→outcome 역채움뿐 — 진입 생존이 핵심. 청산 결정 ID는 토론발 청산만 존재. **기계적 손절/익절·사용자 알림 승인·리밸런스 청산은 exit_decision_id=NULL이 정상**(의미 겸용 금지, exit_reason으로 구분) |
| D3 | 정상 NULL 3종 수용 | 끊김 D(EOD 원장 대사)·E(브로커 고아 채택)·F(백필 스크립트)는 출처가 구조적으로 부재 — NULL 정상, 소비자가 구분(기존 sentinel 유지) |
| D4 | 소급 없음 | 과거 행은 추적 정보 자체가 없어 백필 불가 — 신규 거래부터 축적 |
| D5 | 핫패스 무해 원칙 | 전 배선은 "값 전달"만(주문 로직 무변경), 계보 기록 실패가 주문 흐름을 절대 깨지 않음(best-effort). 킬스위치 불요 |
| D6 | 범위 | KR(kiwoom)만 — coin은 유휴+P4 아크. 매도체결 원장 불일치(005930 37/144) 진단은 L2에 포함 |

## 1. 실측 확정 사실 (디스커버리 — 구속)
- **유일한 정상 배선**: agent_chat 자동 워치 토론 → on_trade_approved(session_id=session.id) → OrderRequest.session_id → _record_fill_ledger `decision_id=order.session_id`(coordinator.py:977)·_poll_tracked_fills `decision_id=order.source_session_id`(:2757).
- **끊김 A**: bare OrderRequest — coordinator._close_position:1894·_reduce_position:1963·_add_to_position:2029, risk_monitor._execute_stop_loss:545·_execute_take_profit:605, handle_alert_action:1820/1853, portfolio_agent 리밸런스:334-340/397-403 — 전부 session_id 미전달.
- **끊김 B**: MonitoredPosition(position_manager.py:119-157)에 provenance 필드 전무. _trigger_discussion:966이 session.id(진짜 결정 ID)를 쥐고도 _apply_decision:977→:1603에서 유실.
- **끊김 C(최대)**: LangGraph 승인 → 그래프 execution node가 단독 실행(on_trade_approved 미경유). execution.py:384-398 `record_trade_fill`에 **decision_id= 키워드 누락 버그**(entry_or_exit도 누락). 설령 채워도 SessionManager ID라 조인 불가+GC로 소멸.
- 스키마는 이미 존재: kr_stock_trades.decision_id/strategy_id/entry_or_exit(_ensure_columns storage_service.py:432-445, INSERT 바인딩 정상 :1596-1647), kr_realized_pnl.entry/exit_decision_id(최초 CREATE :168-183). **컬럼 추가 거의 불요 — 값 스레딩이 본체**.
- ManagedPosition.analysis_session_id 존재(models.py:347)·blob 왕복 lossless. 채움 지점=on_trade_approved BUY(:762)+register_fill_as_position(:63-77)뿐.
- _apply_sell_position_delta(:1280): entry=position.analysis_session_id, exit=order.session_id — 소스 이원 구조는 옳음.
- **캘리브레이션 매칭**: label_and_calibrate는 agent_chat_decisions.outcome_realized_pnl만 읽음(calibration.py:146-160). 유일 채움=trade_log.py:172-173 update_decision_outcome — **0행 매치=완전 침묵**(storage_service.py:1978-1982 독스트링 명시).
- **regime 이중 라벨**: regime_label=breadth 전용, breadth None이면 neutral 하드코딩(regime.py:152-160) — index/flow 반영 메커니즘 자체가 없음. market_sentiment_label은 index/flow만으로도 정상 산출(:172-195). -6.4% 폭락일의 'neutral'은 regime_label 쪽.
- strategy_id는 전 코드베이스 무호출 사문 컬럼(이번 범위 밖 — 문서화만).

## 2. 태스크 설계
### L1 통합 결정 원장
- agent_chat_decisions에 `decision_source` TEXT nullable(_ensure_columns, 기존 행=NULL≡'agent_chat' 폴백 해석)+`session_ref` TEXT nullable(원 세션 참조 — GC 후에도 행은 durable).
- 신규 `persist_analysis_decision(storage, *, session_id, ticker, action, confidence, rationale) -> decision_id(uuid)` — KR 그래프 execution node의 발주 직전 1곳에서 호출(best-effort: 실패=None → 계보 없이 발주 진행). agent_chat 경로 persist_session은 무변경(source 기본 해석).
- 소비자 영향 0 확인: 캘리브레이션 per-agent는 votes 조인이라 analysis 행 자연 제외, 결정 목록 API·EOD 리뷰는 additive 컬럼 무해.

### L2 발주·기록 배선 + 원장 불일치 진단
- execution.py:384-398 버그 픽스: `decision_id=<L1 발급 id>`+`entry_or_exit` 전달. register_fill_as_position에도 동일 id 전달(ManagedPosition.analysis_session_id=durable 결정 id — 이후 청산 시 entry_decision_id로 생존).
- _close_position/_reduce_position/_add_to_position에 `decision_id: Optional[str]=None` 파라미터 → OrderRequest.session_id 스레딩(기본 None=기존 거동 불변). risk_monitor·handle_alert_action·리밸런스는 D2에 따라 무스레딩(NULL 정상 — 주석 명문화).
- **원장 불일치 진단**: 005930 매도 quantity=144/executed=37 'partial' 동결+000660 7주 괴리의 근본 원인 실데이터 추적(_poll_tracked_fills 생존 주기·재시작 시 TrackedOrder 복원·expire 경로) — 원인 확정 후 픽스(범위 내면)+회귀 테스트, 범위 초과면 사실 보고+후속 분리.

### L3 PositionManager provenance
- MonitoredPosition에 `entry_decision_id: Optional[str]=None`(pydantic — 스키마 불요). add_position/update_position/register_fill_as_position(:97-117) 관통. sync_from_account 발 포지션=None 정상.
- _trigger_discussion의 session.id를 _apply_decision→_execute_close/_reduce/_add_position 시그니처로 관통 → coordinator._close_position(decision_id=...) — 토론발 청산의 exit_decision_id 확보.

### L4 역채움 관측성 + E2E
- update_decision_outcome: 0행 매치 시 `decision_outcome_update_missed` warning(결정 id·금액 포함)+bool 반환(호출부 로그). 
- E2E 회귀 테스트: 결정 영속→BUY 체결→SELL 체결→kr_realized_pnl(entry/exit id 채움)→outcome 역채움→label_and_calibrate가 ≥1행 산출 — 전 구간 tmp DB.

### L5 regime 라벨 융합
- compute_market_regime: breadth None 시 regime_label을 sentiment_score 기반 폴백 산출(bullish→risk_on/bearish→risk_off/else neutral — PHASE5_SENTIMENT_THRESHOLD 재사용). breadth 있으면 기존 산식 불변.
- 소비자 감사: regime_label vs market_sentiment_label을 읽는 전 소비처 grep·표 문서화(spec 부록 또는 코드 주석), 불일치 소비자 발견 시 정정.

## 3. 비변경 불변식
- 주문 실행 로직·수량·가격·게이트 일절 무변경(값 스레딩만). 계보 기록·결정 영속 실패=주문 흐름 무영향(try/except best-effort).
- agent_chat 기존 결정 영속·투표·모더레이터 무변경. 기존 컬럼 의미 무변경(additive만).
- 실 네트워크·실 DB 테스트 금지(tmp DB 픽스처 관례).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 핫패스 예외 유입 | 전 배선 best-effort+기존 경로 byte-불변 테스트 핀 |
| analysis 결정 행이 소비자 통계 왜곡 | decision_source로 구분 가능, 캘리브레이션 votes 조인 자연 제외 확인 테스트 |
| 원장 불일치 원인이 광범위 | L2 진단은 time-box — 원인 확정·보고까지 필수, 픽스는 범위 내 판단 |
| regime_label 의미 변경 파장 | breadth 있는 경우 byte-불변, 폴백만 신설+소비자 감사 동반 |
