# P2-4 페이퍼 체결 사실성 Implementation Plan (중간안 + coin 장부 선행)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 모의 체결의 낙관/오염을 봉합해 "수익률 담보"를 사실화 — coin 장부오염 선행 → 수수료·세금 → 슬리피지 → coin live 버그. KR 브로커 원장은 불변(desync 회피).

**Audit/Design:** `docs/superpowers/audits/2026-07-14-paper-fill-realism-audit.md` (§C 중간안).

## Global Constraints
- C1 라이브 :8001(master OFF+hitl)·:5173 HMR. 백엔드 변경은 재시작 배포. 커밋 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 백엔드 테스트: `cd backend && env -u OPENROUTER_API_KEY python -m pytest <파일> -v -p no:logging`.
- **KR 원장 계산 불변**: `fill_confirm.py`·`coordinator.py`의 avg_price/_apply_sell_fill·`paper_performance.py`·ka10074/ka10076 경로는 읽지도 고치지도 않음(R5-P1 회귀 회피). KR 개선은 (a) 표시/결정 레이어, (b) 방어매도 order_type에만.
- **coin만 시뮬**: `_execute_paper_order`(paper 분기) 안에만. live 분기는 실 Upbit 체결 진실 사용(이중계산 원천 차단).
- 수수료율·슬리피지 bps는 **설정화**(코드 상수 금지). 기본값 보수적.

---

## Task P0: coin 장부오염 선행 (C2 게이트·최우선)
**Files:** Modify `backend/services/storage_service.py`(save_coin_position 가중평균 + SELL 삭제경로), `backend/agents/graph/coin_nodes.py`(SELL 저장 경로), `backend/app/api/routes/coin/helpers.py`(실현손익 최소집계), Test 신규
**근본:** (a) 자율 SELL이 `if side=="bid":`에 갇혀 save_coin_position 미호출→판 포지션이 옛 평단으로 무한 "보유"(coin_nodes.py:741-750); (b) save_coin_position `INSERT OR REPLACE`→반복매수 시 가중평균 아닌 마지막매수 덮어씀(storage_service.py:692-739); (c) coin 실현손익 집계 전무.
- [ ] Step1 실패테스트: (a) 자율 SELL 후 해당 coin 포지션이 제거/차감됨(GET /coin/positions에서 사라짐, 현재 실패해야 정상); (b) 반복 BUY 시 avg_entry_price가 가중평균(마지막가 덮어쓰기 아님); (c) 청산 시 coin 실현손익 row가 최소 형태로 적재(진입가·청산가·수량·실현액).
- [ ] Step2~4: coin_nodes SELL 경로가 save/제거 호출; save_coin_position을 가중평균 upsert로(전량매수 덮어쓰기 제거); coin 실현손익 최소집계 추가. 회귀: 기존 coin 테스트 PASS.
- [ ] Step5 커밋: `fix(coin): 장부오염 봉합 — SELL 미저장·반복매수 덮어쓰기·실현손익 부재 (P2-4 선행)`

## Task P1: 수수료·세금 + 설정
**Files:** Create `backend/app/config.py` 신규 `PaperFillSettings`(또는 기존 config 확장), Modify `backend/agents/graph/coin_nodes.py`(paper fee), `backend/app/api/routes/coin/helpers.py`(calculate_position_pnl fee 차감), Create KR display cost helper + Modify `backend/services/trading/risk_monitor.py`(트리거 비교), Test
**근본:** coin fee=0 하드코딩. KR 실시간 미실현·손절/익절 트리거가 raw가(무비용).
- [ ] Step1 실패테스트: (a) `PaperFillSettings`(kr_commission_bps/kr_sell_tax_bps/coin_fee_bps/slippage_bps) 존재·기본 보수값; (b) coin paper 매수 원가에 fee 가산·매도 실현손익에서 왕복 fee 차감; (c) KR 신규 `effective_pnl(avg,current,qty,side)` display helper가 왕복 순비용 반영, 실시간 미실현 표시·손절/익절 트리거 비교가 이를 사용(단 ManagedPosition.unrealized_pnl 원장 계산·fill_confirm·coordinator는 불변).
- [ ] Step2~4: 설정 추가; coin paper fee 반영; KR display helper + 트리거 배선. 회귀: KR 실현손익·avg_entry 테스트 불변 확인.
- [ ] Step5 커밋: `feat(fill): 수수료·세금 반영 — coin paper fee + KR 실시간 순비용 보정 + PaperFillSettings (P2-4)`

## Task P2: 슬리피지
**Files:** Modify `backend/agents/graph/coin_nodes.py`(paper adverse+진입 재조회), `backend/services/trading/risk_monitor.py`(방어매도 order_type), Test
**근본:** 슬리피지 전무(get_price_with_slippage dead code). 방어매도가 트리거가 그대로 LIMIT→갭 시 비현실적 유리.
- [ ] Step1 실패테스트: (a) coin paper 진입가를 실행시점 재조회(stale 제거) 후 side별 adverse(buy +bps, sell −bps); (b) KR `_execute_stop_loss`/`_execute_take_profit`가 order_type=MARKET(또는 슬리피지-버퍼 aggressive LIMIT)로 발주(어댑터 호출 인자 검증).
- [ ] Step2~4: coin paper 슬리피지+재조회; KR 방어매도 MARKET화. 회귀 PASS.
- [ ] Step5 커밋: `feat(fill): 슬리피지 — coin paper adverse+진입재조회 + KR 방어매도 MARKET화 (P2-4)`

## Task P3: coin live 버그 + KR net/gross 검증
**Files:** Modify `backend/agents/graph/coin_nodes.py`(:867 live executed_volume 폴백), Test(KR net/gross 실응답 검증)
- [ ] Step1: (a) coin live `_execute_live_order`가 미체결(executed_volume 0)을 요청수량으로 폴백하지 않도록 수정(실체결량 사용); (b) KR `net_pnl=realized-cmsn-tax` 이중차감 여부를 실 모의서버 응답 1건으로 검증(**자기목 픽스처 금지**). 이중차감이면 봉합.
- [ ] Step2 커밋: `fix(coin): live executed_volume 실체결량 사용 + KR net/gross 검증 (P2-4)`

## Task P4: 배포+검증
- [ ] 백엔드 재시작 → coin SELL 후 포지션 정합·수수료 반영 실현손익·방어매도 MARKET 확인. 레저.
