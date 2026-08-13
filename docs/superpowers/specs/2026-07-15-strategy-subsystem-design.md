# 자율 전략 서브시스템 설계 (EOD 리뷰 → 전략 합의 → 적응형 전략)

> Status: DESIGN (brainstorming 산출물). 2026-07-15. 실사 근거: 4-도메인 데이터 랜드스케이프 워크플로우(trades/agent-chat/market-data/strategy).

## 목표 (Goal)
현재 시스템은 **종목별 전술 결정**(agent-chat 4-에이전트 합의 → BUY/SELL/HOLD)만 반응적으로 수행하고, 그 위의 **전략 계층**(스탠스·사이징·레짐 대응)이 없다. 이 서브시스템은 **① 장 마감 종합 리뷰 → ② 전략 레벨 에이전트 합의 → ③ 적응형 `TradingStrategy` → ④ 그 전략이 전술 계층을 가드레일로 구동**하는 폐루프를 만든다. 핵심 원료는 **정제된 과거 매매 + agent-chat 기록**(사용자 아이디어)이며, 여기에 **센티먼트/행동심리 입력 계층**을 포함한다.

## 실사로 확인한 현실 (What exists vs. what's needed)
| 버킷 | 현 상태 (durable?) | 판정 |
|---|---|---|
| ① 매매 실적 | `kr_stock_trades`·`coin_trades`·`coin_realized_pnl` append-only (storage.db) **durable** | 골격 O, **결정↔결과 링크 X** |
| ② agent-chat 결정/투표 | 런타임 리치(투표·논지·합의·반대의견) but `_session_history` 인메모리 100캡·**재시작 소실, SQLite 전무** | **증발 — 최우선** |
| ③ 시장 레짐/시장심리 | 종목별만 풍부. **지수·섹터·breadth·수급·매크로 X**, 시장전체 센티먼트 X | 대부분 부재 |
| ④ 포트폴리오·종목 컨텍스트 | coordinator 상태·PortfolioAgent·MarketContext **존재** | OK |
| 전략 레이어 | `TradingStrategy` 스키마·4프리셋·`/strategy` REST·PortfolioAgent **재사용 가능**; `StrategyEngine`·`evaluate_with_strategy` **데드코드**; 전략 **미영속·전술이 무시** | 골격 O, 배선 X |

**결정적 사실:** 사용자 아이디어("과거 매매+agent-chat 정제→전략")의 전제 — 결정↔결과가 durable하게 연결된 이력 — 이 **지금 존재하지 않는다.** 이것이 Phase 1이다.

## 전체 아키텍처 (5 Phase, 의존 순서)
```
[④ 레짐·시장심리 스냅샷]─┐
[① 매매·결과 원장]      ─┼─▶ ② EOD 종합 리뷰 ──▶ ③ 전략 레벨 합의 ──▶ TradingStrategy(적응형·버전이력)
[② agent-chat 결정+투표+센티먼트 원장]┘  (마감 배치·캘리브레이션)   (전략을 토론·투표)          │
                                                                                 ▼
                                                       ⑤ 전술 계층(현 종목별 합의)이 활성 전략을
                                                          가드레일로 소비(임계·사이징·우선 워치)
```
- **Phase 1 — 데이터 토대 (이 spec의 초점):** durable 결정↔결과↔센티먼트 원장.
- **Phase 2 — EOD 종합 리뷰 + 캘리브레이션:** 마감 배치가 원장을 읽어 종목·포트폴리오·**에이전트 적중률** 리뷰 + 최소 레짐 스냅샷.
- **Phase 3 — 전략 레벨 합의 + 적응형 전략:** 리뷰+레짐 → 전략-고도 다중 에이전트 토론/투표 → `TradingStrategy` 갱신(스키마 재사용) + 버전 영속.
- **Phase 4 — 전략→전술 배선:** 전술 합의가 활성 전략 소비, 이중 사이징 노브(RiskParameters vs PositionSizingRules) 단일화.
- **Phase 5 — 센티먼트/행동 + 레짐 데이터 심화:** 시장전체 심리·외국인/기관 수급·지수/섹터 페처(대형·후순위).

각 Phase는 독립 spec+plan. **아래는 Phase 1만 구현 수준으로 상술**한다.

---

# Phase 1 — Durable 결정·결과·센티먼트 원장 (구현 대상)

**한 문장:** 전술 결정(agent-chat)·체결·실현결과·센티먼트/행동 신호를 **재시작·일자를 넘어 durable하게, 서로 조인 가능하게** 저장해, 이후 EOD 리뷰·캘리브레이션·전략 합의가 읽을 수 있는 단일 이력을 만든다.

## 컴포넌트 & 데이터 스키마 (전부 `backend/data/storage.db`, `storage_service.py`에 DDL/writer 추가)

### C1. agent-chat 결정 원장 (최우선 — 사용자 아이디어의 전제)
현재 `ChatSession`(agent_chat/models.py:204)·`AgentVote`(:110)·`TradeDecision`(:126)은 인메모리뿐. 이를 영속화.
- **신규 테이블 `agent_chat_decisions`**: `id(=ChatSession.id)`, `ticker`, `stock_name`, `trade_date`, `created_at`, `status`, `action`, `confidence`, `consensus_level`, `rationale`, `dissenting_opinions(json)`, `entry_price/stop_loss/take_profit/position_pct`(결정 제안치), `news_sentiment`, `news_count`, `behavioral_signals(json)`(C4), `regime_snapshot_id`(FK, Phase2가 채움, Phase1은 nullable), `market_context(json)`(선택: 축약 MarketContext), `outcome_realized_pnl`(nullable — **Phase1이 청산 시 기계적 숫자 백필**: C3의 매칭 결과를 진입 결정에 기록), `outcome_label`(nullable: correct/incorrect/flat — **판단이므로 Phase2가 채움**). 인덱스: ticker, trade_date, action.
- **신규 테이블 `agent_chat_votes`**: `id`, `decision_id`(FK), `agent_type`(technical/fundamental/sentiment/risk), `vote`(strong_buy…abstain), `confidence`, `reasoning`, `key_factors(json)`, `suggested_position_pct/stop_loss_pct/take_profit_pct`(risk 에이전트). 인덱스: decision_id, agent_type.
- **transcript(Phase1 제외):** Phase1은 **투표(agent_chat_votes)+결정+논지(rationale/key_factors/dissenting)만** 저장한다. 전체 토론 transcript(all_messages)는 용량이 크고 리뷰/캘리브레이션에 필수가 아니므로 **Phase1에서 저장하지 않는다**(필요 시 후속에서 `agent_chat_transcript` 테이블로 추가 — 스키마 확장만).
- **영속 훅 배선:** coordinator.py:158/173-175의 `on_session_complete`/`on_decision` 콜백이 **미등록**임(호출자 0). 이를 등록해 세션 완료 시 위 테이블에 append. manual `/discuss`도 저장(결정만, 미실행이라도 신호 가치).

### C2. 매매↔결정 provenance (링크 복구)
현재 챗 실행이 `kr_stock_trades.session_id = f"chat_{timestamp}"`(coordinator.py:567, **가짜 id**) → 결정과 조인 불가.
- `kr_stock_trades`·`coin_trades`에 컬럼 추가: `decision_id`(=ChatSession.id, nullable), `rationale`(nullable), `strategy_id`(nullable, Phase3), `entry_or_exit`('entry'|'exit'|'add'|'reduce').
- 챗 실행 경로가 **실 `ChatSession.id`**를 넘기도록 수정(가짜 timestamp 제거). `record_trade_fill`(trade_log.py:45) 5개 호출부가 이미 손에 든 provenance(`ManagedPosition.analysis_session_id`·`QueuedTrade.reason`·`TrackedOrder.source_session_id`)를 넘기도록 배선. `fee`도 실값 전달(현재 0 하드코딩).

### C3. KR 종목별 실현결과 원장 + EOD 스냅샷
현재 KR 실현손익은 ka10074 일별·라이브뿐(영속 X, 브로커 30일 창 밖 소실). coin만 `coin_realized_pnl` 보유.
- **신규 `kr_realized_pnl`**(coin_realized_pnl 미러): `id`, `stk_cd`, `entry_price`, `exit_price`, `quantity`, `realized_amount`(수수료·세 반영 net), `entry_decision_id`(FK), `exit_decision_id`(FK), `holding_period_seconds`, `entry_at`, `exit_at`, `created_at`. **진입↔청산 매칭**(가중평균 평단 기준, coin과 동일 방식)으로 SELL/REDUCE 시 append.
- **신규 `daily_perf_snapshot`**(EOD 배치가 마감 후 1회 기록): `trade_date`, `equity`(kt00004 평가액), `realized_pnl`, `commission`, `tax`, `net_pnl`, `win_trades`, `loss_trades`, `cumulative_return_pct`, `regime_snapshot_id`(Phase2), `created_at`. 브로커 창을 넘겨 **durable 자산곡선/성과 시계열** 확보. (Phase1은 스냅샷 *기록*만; 이를 소비하는 EOD 리뷰 로직은 Phase2.)

### C4. 센티먼트/행동 입력 캡처 (사용자 우려 반영)
"네이버 뉴스 단일 소스 리스크"의 구조적 해소는 **캘리브레이션**(Phase2)이지만, 그러려면 **결정 시점의 센티먼트+행동 신호가 durable하게 기록**돼야 함(Phase1이 캡처).
- C1의 `agent_chat_decisions.news_sentiment`·`news_count`에 더해, **`behavioral_signals(json)`**에 결정 시점의 가격/거래량 행동 신호를 명시 라벨링해 저장: 거래량비(vol_ratio)·갭·모멘텀 상태(golden/dead cross·trend)·과열/투매 근접(RSI 극단)·변동성(historical vol%). **이미 `technical_indicators.py`가 계산 중인 값을 재사용**해 결정 레코드에 박제.
- 스키마에 **시장전체 심리·수급 슬롯을 nullable로 예약**(`market_sentiment(json)`, `flow(json)`) → Phase5 페처가 채우면 마이그레이션 없이 확장. Phase1은 available한 per-종목 신호만 채우고 슬롯만 만든다.
- **주의:** Phase1은 센티먼트를 *재설계하지 않는다* — 오직 **결정과 함께 durable 캡처**해 이후 "이 센티먼트가 실제 수익률을 예측했나"를 Phase2가 검증할 수 있게 만든다.

## 데이터 흐름 (Phase 1)
```
agent-chat 세션 완료 ──on_session_complete(신규 배선)──▶ agent_chat_decisions + agent_chat_votes
                                                          (news_sentiment + behavioral_signals 포함)
체결(record_trade_fill) ──실 decision_id·rationale·fee 전달──▶ kr_stock_trades/coin_trades (링크됨)
SELL/REDUCE 청산 ──진입↔청산 매칭──▶ kr_realized_pnl (entry/exit decision_id FK)
장 마감 ──EOD 배치(신규, market_hours closed 트리거)──▶ daily_perf_snapshot 1행
```

## 에러 처리 & 불변식
- 모든 영속은 **fire-and-forget 실패-무해**(기존 `_schedule_persist` 패턴) — 기록 실패가 매매/모니터링을 절대 막지 않음.
- `decision_id` nullable — 링크 못 찾아도 체결 기록은 남김(부분 provenance 허용).
- **KR 브로커 원장 계산 불변**: `kr_realized_pnl`은 표시/분석용 파생 기록이며 브로커 실현손익(ka10074) 계산을 대체하지 않음. net 계산은 기존 double-subtraction 봉합(paper_performance.py:155-176) 규약을 따름.
- mock/live 무관하게 스키마 동작(mock에서도 체결·결정 발생).

## 테스트 (TDD)
- C1: 세션 완료 시 `agent_chat_decisions`+`agent_chat_votes`에 정확한 행(액션·합의·4투표·논지) 저장, 재시작 후 조회됨. manual `/discuss`도 저장.
- C2: 챗 실행이 **실 ChatSession.id**로 기록(가짜 `chat_ts` 아님), decision_id로 체결↔결정 조인 성공, fee 실값.
- C3: 진입→청산 시 `kr_realized_pnl` 매칭 행(entry/exit decision_id·holding_period·net realized), EOD 배치가 `daily_perf_snapshot` 1행 기록.
- C4: 결정 레코드에 news_sentiment + behavioral_signals(vol_ratio/trend/RSI극단 등) 박제, market_sentiment/flow 슬롯 nullable 존재.
- 회귀: 기존 storage_service·coordinator·agent_chat·trade_log 테스트 PASS. 마이그레이션(신규 컬럼)이 기존 행 안전.

## 범위 밖 (Phase 1 아님)
- EOD 리뷰 *로직*·에이전트 적중률 계산·outcome_label 채우기 = **Phase 2**.
- 전략 레벨 합의·`TradingStrategy` 적응·영속·전술 배선 = **Phase 3/4**.
- 시장전체 심리·외국인/기관 수급·지수/섹터 페처 = **Phase 5**(스키마 슬롯만 Phase1에서 예약).

## 마이그레이션 노트
storage_service.py는 `CREATE TABLE IF NOT EXISTS` + 신규 컬럼은 `ALTER TABLE ADD COLUMN`(SQLite, DEFAULT NULL) 방식. 기존 `data/storage.db` 무손실.
