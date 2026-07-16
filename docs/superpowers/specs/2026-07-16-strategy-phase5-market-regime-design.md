# 자율 전략 서브시스템 Phase 5 — 시장전체 레짐 심화 (지수·수급·시장심리)

> Status: DESIGN (brainstorming 산출물). 2026-07-16. 상위 설계: `2026-07-15-strategy-subsystem-design.md`의 Phase 5.
> 실사 근거: Explore 4-표면 매핑(Kiwoom client 구현현황·REST spec·센티먼트 인프라·예약 슬롯·regime 소비경로).

## 목표 (Goal)
자율 전략 서브시스템의 레짐 입력을 **스캐너 breadth 프록시 단일 신호**에서 **실제 시장 데이터**(KOSPI/KOSDAQ 지수 추세 · 외국인/기관 수급 · 이를 조합한 파생 시장심리)로 심화한다. 이 신호는 이미 존재하는 전략 합의 계층(`strategy_panel.regime_strategist`)이 소비하고, Phase 1이 예약해 둔 채로 항상 NULL이던 `agent_chat_decisions.market_sentiment`/`.flow` 슬롯을 채운다.

상위 spec이 Phase 5에 약속한 3대 산출물을 모두 전달한다:
1. **지수/섹터 페처** — ka20003 전업종지수(KOSPI/KOSDAQ + 업종지수).
2. **외국인/기관 수급** — ka10131 기관외국인 연속매매현황(시장전체 순매매·연속순매수일).
3. **시장전체 심리** — 새 뉴스 소스가 아니라 **지수+breadth+수급의 파생 복합 라벨**(사용자의 "네이버 뉴스 단일소스 리스크"를 구조적으로 우회).

## 실사로 확인한 현실 (What exists vs. what's needed)
| 버킷 | 현 상태 | 판정 |
|---|---|---|
| Kiwoom client 수급/지수/업종 메서드 | **0개 구현** (client.py는 per-종목 price/chart/orderbook + 계좌/주문 + universe만). `_request(api_id=...)` 배관은 재사용 가능 | 전부 신규, 배관 O |
| Kiwoom REST spec | ka20003(지수)·ka10131(수급)·ka10101(업종코드) 등 **spec 존재, 도달 가능** (`Kiwoom-REST-API/.../kiwoom_api_spec.json`, 208 API) | 페처만 배선하면 됨 |
| `regime_snapshot` 테이블 | breadth_* + regime_label + source(='scanner')만. **지수·수급·심리 컬럼 전무** | ALTER ADD COLUMN 필요 |
| `compute_regime_snapshot` | 순수 sync sqlite3, 스캐너 breadth만, 실패-무해(None) | 심화 필요 (기존 함수 보존) |
| `agent_chat_decisions.market_sentiment`/`.flow` | 예약 nullable 컬럼, **항상 NULL 하드코딩** (decision_log.py:130-131) | Phase 5가 채움 |
| `strategy_panel.regime_strategist` | `regime_history`로 `{regime_label, breadth_ratio}`만 받음 | 지수/수급/심리로 확장 |
| 시장전체 심리 | **전무** (regime.py 도크스트링이 감사로 확인). news_sentiment은 종목별 가격모멘텀 프록시 | 파생 라벨로 신설 |

**결정적 사실:** Phase 5가 필요로 하는 모든 시장 데이터는 spec'd이고 기존 `_request` 배관으로 도달 가능하다. 새 인프라(HTTP 클라이언트·인증)는 필요 없다 — 페처 메서드 + 응답 모델 + 레짐 조합 로직 + 소비경로 확장뿐이다.

## 핵심 설계 결정: 전부 비동기 EOD 배치 경로
Phase 5의 3대 산출물을 **전부 async EOD 배치**(장 마감 1회, `eod_orchestrator.run_eod_review`)에만 얹는다. **라이브 전술 토론 핫패스는 건드리지 않는다.**

근거:
- **레버리지:** 레짐은 이미 전략 합의의 직접 입력인데 현재 breadth 프록시뿐 → 여기를 강화하는 것이 서브시스템 목적에 가장 직결.
- **레이트리밋 안전:** EOD는 하루 ~2콜(지수 1 + 수급 1) 추가뿐 → Kiwoom 1.43req/s 천장 대비 무시 가능. `b7ab885` per-API 레이트 작업이 드러낸 핫패스 민감점을 완전히 회피.
- **레이턴시 안전:** 종목별 토론 경로에 fetch를 추가하지 않으므로 토론 지연 0.
- **폴백 안전:** 지수/수급 fetch 실패(예: mock 미지원, 1700 등) 시 breadth-only로 폴백 = 레거시 거동 byte-동일. 실패-무해가 EOD 체인 전체 규약(`never-raise`)과 일치.
- **검증 가능:** 실 Kiwoom mock 도메인(mockapi.kiwoom.com)이 ka20003/ka10131을 서빙 → 페처를 실제로 라이브 검증 가능(우리 내부 mock이 아니라 키움 공식 모의).

## 컴포넌트 & 데이터 스키마

### C1. Kiwoom 시장데이터 페처 (client.py 신규 메서드)
`_request(api_id, endpoint, data)` 배관 재사용. 각 메서드는 **실패-무해**(예외 삼켜 `None` 반환) — EOD 체인이 절대 안 깨지도록.

- **`get_all_sector_index(mrkt_tp="0") -> Optional[dict]`** — ka20003 전업종지수(`/api/dostk/sect`, req `inds_cd`). 응답 `all_inds_idex[]`에서 KOSPI(stk_cd="001")·KOSDAQ(stk_cd="101") 행을 추출: `{index_kospi(cur_prc), index_kospi_chg_pct(flu_rt), index_kosdaq, index_kosdaq_chg_pct}`. (전업종지수는 한 콜로 전 지수 반환 — 업종지수도 여기 포함, 5C 섹터로테이션이 재사용.)
- **`get_inst_foreign_flow(mrkt_tp) -> Optional[dict]`** — ka10131 기관외국인연속매매현황(`/api/dostk/frgnistt`, req `dt/mrkt_tp/netslmt_tp/stk_inds_tp/amt_qty_tp/stex_tp`). 응답 `orgn_frgnr_cont_trde_prst[]`를 **시장전체로 집계**: `{foreign_net_amount(Σ frgnr_nettrde_amt), institution_net_amount(Σ orgn_nettrde_amt), foreign_net_buy_days_top(대표 연속순매수일)}`. (또는 ka90009 외국인기관매매상위 — 구현 시 응답 예제로 확정.)
- rate_limiter `API_REQUEST_TYPE_MAP`에 `ka20003`·`ka10131`을 `RequestType.QUERY`로 등록(전역 QUERY 버킷 + per-API 게이트 자동 적용).
- 응답 모델은 dict 반환(Pydantic 모델은 최소화 — 조합 로직만 소비하고 원장엔 JSON으로 저장).

### C2. 레짐 심화 (regime_snapshot 확장 + compute_market_regime)
- **`regime_snapshot` 테이블 ALTER ADD COLUMN** (전부 nullable, 기존 행 안전):
  `index_kospi REAL`, `index_kospi_chg_pct REAL`, `index_kosdaq REAL`, `index_kosdaq_chg_pct REAL`, `foreign_net_amount REAL`, `institution_net_amount REAL`, `market_sentiment_label TEXT`, `sentiment_score REAL`.
- **기존 `compute_regime_snapshot`(sync breadth) 보존** — 변경 없음. `source="scanner"` 행은 그대로.
- **신규 `compute_market_regime(breadth_snap, index, flow) -> dict`** (순수 함수, 조합 전용): breadth 스냅샷(있으면)에 지수·수급을 병합하고 **파생 복합 심리**를 산출:
  - `sentiment_score` = 가중합(breadth_ratio · KOSPI/KOSDAQ 등락률 정규화 · 외국인/기관 순매수 부호) — 각 소스는 available할 때만 가중(None이면 재정규화).
  - `market_sentiment_label` = score를 `PHASE5_SENTIMENT_THRESHOLD`로 bullish/bearish/neutral 라벨링.
  - `regime_label`(기존 risk_on/off/neutral)은 breadth 기준 유지(하위호환) — 심리는 별도 필드.
  - **폴백:** index/flow가 None(mock/실패)이면 breadth-only → 심리는 breadth만으로 산출하되 낮은 신뢰. breadth·index·flow **전부** None이면 `None` 반환(현행과 동일, 저장 안 함).

### C3. eod_orchestrator 배선
`run_eod_review` 내 기존 `compute_regime_snapshot`(sync, to_thread) 뒤에 삽입:
```
snap = await to_thread(compute_regime_snapshot, ...)        # 기존 breadth
index = await get_all_sector_index(coordinator._kiwoom)     # 신규, 실패=None
flow  = await get_inst_foreign_flow(coordinator._kiwoom)    # 신규, 실패=None
enriched = compute_market_regime(snap, index, flow)         # 신규 조합
if enriched: await storage.save_regime_snapshot(enriched); rid = enriched["id"]
```
전체 try/except never-raise 보존. `coordinator._kiwoom`가 None(미배선)이면 페처 skip → breadth-only. `PHASE5_MARKET_DATA_ENABLED=False`면 페처 skip.

### C4. strategy_panel 피드
- `build_strategy_context`의 `regime_history` 항목에 신규 필드 추가: `market_sentiment_label`, `sentiment_score`, `index_kospi_chg_pct`, `index_kosdaq_chg_pct`, `foreign_net_amount`, `institution_net_amount` (없으면 None — 하위호환).
- `regime_strategist` 프롬프트를 breadth 단독 → "지수 추세 + 외국인/기관 수급 + 파생 시장심리 + breadth"로 확장. 데이터 부족 시 여전히 neutral·낮은 confidence 규약 유지.

### C5. 결정 슬롯 백필 (예약 슬롯 해소)
- `backfill_regime_id`(또는 sibling `backfill_market_context`) 확장: 그날 `regime_snapshot`의 `market_sentiment_label`/`sentiment_score`를 JSON으로 `agent_chat_decisions.market_sentiment`에, 수급(`foreign_net_amount`/`institution_net_amount`)을 `.flow`에, 그날 모든 결정 행에 UPDATE로 박제.
- **핫패스 무변경:** 결정은 인메모리 상태로 만들어지고 EOD에 시장 컨텍스트가 백필된다(regime_snapshot_id와 동일 패턴). decision_log.py의 write-time `None` 하드코딩은 그대로 두고 EOD 백필이 채운다.
- 목적: 원장이 "이 결정 당시 시장 레짐/수급/심리"를 기록 → 향후 레짐조건부 캘리브레이션("risk_off에서 내린 결정이 더 나빴나") 가능.

### C6. config 플래그
- `PHASE5_MARKET_DATA_ENABLED: bool = True` — 킬스위치(False면 페처 전부 skip, 레짐 = 순수 breadth = 레거시).
- `PHASE5_SENTIMENT_THRESHOLD: float = 0.1` — 복합 심리 라벨 경계(EOD_REGIME_BREADTH_THRESHOLD 패턴).
- (선택) 지수/수급 가중치는 상수로 시작(설정화는 후속).

## 데이터 흐름 (Phase 5)
```
장 마감 ── eod_orchestrator.run_eod_review ──▶
  1. compute_regime_snapshot (sync breadth)               [기존, 불변]
  2. get_all_sector_index (ka20003)  ─┐
     get_inst_foreign_flow (ka10131) ─┤ 실패=None (실패-무해)  [신규 페처]
  3. compute_market_regime(breadth, index, flow)          [신규 조합]
       → market_sentiment_label + sentiment_score
  4. save_regime_snapshot (심화된 행)
  5. label_and_calibrate / build_eod_review                [기존]
  6. backfill: regime_id + market_sentiment + flow → 그날 agent_chat_decisions  [확장]
       ↓
  strategy_panel.build_strategy_context
       → regime_history{index, flow, sentiment}
       → regime_strategist가 실제 시장데이터로 추론          [강화]
```

## 에러 처리 & 불변식
- 모든 페처·조합은 **실패-무해**(None 반환, 절대 raise 안 함) — EOD 체인의 기존 never-raise 규약 준수.
- **폴백 = 레거시 byte-동일:** index/flow 없거나 `PHASE5_MARKET_DATA_ENABLED=False`면 레짐은 순수 breadth(현행). 신규 컬럼은 nullable.
- **ALTER TABLE ADD COLUMN** (SQLite, DEFAULT NULL) — 기존 `data/storage.db` 무손실. `_ensure_columns` PRAGMA 마이그레이션 패턴(Phase 1 T3 선례) 재사용.
- **핫패스 절대 무변경:** 라이브 전술 토론·모니터링 경로에 fetch 추가 0. 레이트리밋 예산 EOD ~2콜/일.
- mock/live 무관 동작: 실 Kiwoom mock(mockapi.kiwoom.com)이 ka20003/ka10131 서빙 → 라이브 검증. 내부 mock/오프라인이면 None 폴백.
- 브로커 원장 계산 불변: 신규 신호는 표시/전략 입력용 파생 기록. 매매·실현손익 계산 경로 무영향.

## 테스트 (TDD)
- **C1:** ka20003/ka10131 응답 예제 파싱 → index/flow dict 정확. 예외(네트워크/파싱) → None. rate_limiter에 QUERY 등록됨.
- **C2:** `compute_market_regime` — breadth+index+flow → 복합 심리 라벨/score 정확. index/flow None → breadth-only 폴백. 전부 None → None. score 재정규화(available 소스만) 검증.
- **C3:** eod_orchestrator가 심화 스냅샷 저장, `_kiwoom=None`/`ENABLED=False`에서 breadth-only, 페처 예외 시 EOD 완주(never-raise).
- **C4:** `build_strategy_context`의 regime_history가 신규 필드 운반(없으면 None), regime_strategist 프롬프트에 지수/수급/심리 반영.
- **C5:** EOD 백필이 그날 agent_chat_decisions의 market_sentiment/flow를 채움(재시작 후 조회됨).
- **회귀:** 기존 regime/eod_orchestrator/strategy_panel/strategy_consensus 테스트 PASS. ALTER 마이그레이션 기존 행 안전. `PHASE5_MARKET_DATA_ENABLED=False` → 레거시 스냅샷 byte-동일.

## 범위 밖 (Phase 5 아님 — 명시적 DEFER, 후속)
- **5B (핫패스 종목별 주입):** 종목별 수급(ka10059)·시장심리를 **라이브 전술 토론**에 주입(`MarketContext.market_sentiment`/`.flow` 필드 + `_fetch_market_context` fetch). 레이트리밋·레이턴시 민감 → 별도 spec. Phase 5는 시장전체 신호로 "시장심리"를 이미 커버.
- **5C (심화 신호):** 섹터 로테이션 랭킹, 프로그램매매(ka90xxx), 실시간 WS(0J 업종지수/0U 업종등락) 구독. ka20003의 업종지수 데이터는 이미 fetch되므로 5C가 재사용.
- 지수/수급 가중치 설정화, sentiment 백테스트/캘리브레이션 검증(Phase 2 캘리브레이션 기구 재사용은 후속).

## 마이그레이션 노트
`storage_service.py`의 `regime_snapshot` DDL에 `CREATE TABLE IF NOT EXISTS`는 신규 설치용, 기존 db는 `_ensure_columns`(PRAGMA table_info → 누락 컬럼 `ALTER TABLE ADD COLUMN`) 마이그레이션(Phase 1 T3 kr_stock_trades 선례와 동일 패턴). `save_regime_snapshot`은 신규 nullable 키를 non-null일 때만 기록.
