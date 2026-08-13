# US 신호 심화 v2 — 설계 기록 (3 워크스트림)

**날짜:** 2026-07-22
**선행:** US AI 신호 v1 + 큐레이션 2→7종 + 관측성(API+FE 카드) — 전부 배포·라이브
**Goal:** 사용자 지적 3갭 해소 — ①토론 중 다른 에이전트도 US 참조 ②신호가 반도체 슬라이스에 국한 ③발굴 Path A가 메가캡 skip으로 잠듦. 세 워크스트림을 하나의 아크로.

## 사용자 확정 설계 분기 (AskUserQuestion)
- **WS1 에이전트 전파**: sentiment+risk+moderator만 주입(technical/fundamental는 차트/재무 렌즈 순수성 유지).
- **WS2 신호 확장**: **다층 신호 분리** — memory·accel·demand 3 서브신호 + 종목별 매칭.
- **WS3 발굴 Path A**: **시장광의 레짐 틸트** — US 강세면 발굴이 momentum/AI 후보를 우대(7종 밖 광의).

## 정합 구조 (WS2가 토대)

```
WS2: 간밤 미국 fetch (union) → 3 서브신호 계산·캐시
      memory (MU·SMH)    ─┐
      accel  (NVDA·AVGO) ─┼─→ 종목별 매칭(공급측 큐레이션)  → WS1 프롬프트 넛지 + 스캐너 보너스
      demand (MSFT·GOOGL·AMZN·META) ─→ 시장 백드롭        → WS3 발굴 레짐 틸트
      overall (기존 US_AI_TICKERS 유지) ─→ 카드 헤드라인·하위호환
```

---

## WS2 — 다층 신호 분리 (토대)

**신호식 무붕괴 원칙**: 기존 `US_AI_TICKERS`(SMH0.5·MU0.25·NVDA0.25)와 캐시 최상위 `signal/signal_pct/components`는 **그대로 유지**(하위호환: 관측성 API·테스트가 이 shape에 의존). 서브신호는 **추가 키**로.

**서브신호 티커셋** (정확 가중은 plan 리서치로 미세조정, v1 균등/근사):
- `memory` = {MU: 0.5, SMH: 0.5} — 메모리/HBM 사이클
- `accel` = {NVDA: 0.6, AVGO: 0.4} — AI가속기/커스텀ASIC
- `demand` = {MSFT: 0.25, GOOGL: 0.25, AMZN: 0.25, META: 0.25} — 하이퍼스케일러 capex(AI 투자심리)

`fetch_us_ai_overnight(tickers)`는 이미 티커 리스트를 받으므로 **전 서브신호 티커 합집합을 1회 fetch**(중복 심볼 dedup). Finnhub 무료 60/min 여유(~7심볼).

**캐시 스키마 확장(additive)**: `us_ai_signal` blob에 `sub_signals: {memory:{signal,signal_pct,components}, accel:{...}, demand:{...}}` 추가. 최상위는 불변.

**종목별 매칭** (`ai_valuechain.py` 값 shape 변경 `str`→`{name, signal_type}`, 리서치 근거로 태깅):
| ticker | 종목 | signal_type |
|---|---|---|
| 005930 삼성전자 | memory | 메모리/HBM |
| 000660 SK하이닉스 | memory | HBM 대장 |
| 042700 한미반도체 | memory | HBM 장비(메모리 사이클) |
| 402340 SK스퀘어 | memory | 하이닉스 지주 프록시 |
| 007660 이수페타시스 | accel | AI가속기 PCB(NVDA 동조) |
| 353200 대덕전자 | accel | FC-BGA/AI서버 |
| 009150 삼성전기 | accel | 엔비디아 FC-BGA |

demand는 공급측 큐레이션에 매칭 종목 없음 → **per-ticker 넛지 대상 아님**, WS3 시장 틸트 드라이버로 소비(설계 결정, 사용자 리뷰 포인트).

**값 shape 변경으로 깨지는 lockstep 소비자**(seam 확인됨):
1. `coordinator._fetch_market_context`(coordinator.py:1284-1299) — 티커 signal_type 조회→매칭 서브신호로 us_market_context 문자열 구성(현재 overall 사용). `is_ai_valuechain` 자체는 키 멤버십이라 안전.
2. `scanner._scan_stock_discovery`(scanner.py:1017-1042) — 티커 signal_type→매칭 서브신호로 보너스(현재 overall `signal`).
3. **`trading.py:1412-1415`** us-signal 라우트 curation 언패킹 `for t, n in ...items()` — n이 dict 되면 깨짐 → **동시 수정 필수**(name=v["name"]). 응답에 `sub_signals`도 노출.

## WS1 — 에이전트 전파 (risk + moderator)

`MarketContext.us_market_context`는 이미 전 에이전트에 도달(models.py:224). **프롬프트 템플릿 주입만** 추가(coordinator 무변경):
- `risk_agent.py`: `analysis_prompt_template`(~83행) + `vote_prompt_template`(~134행)에 `{us_market_context}` + 두 `.format()`(analyze 176-184·vote 275-283)에 `us_market_context=context.us_market_context or ""`. sentiment(79/130/168/253) 미러.
- `moderator_agent.py`: `make_decision(session, context)`가 context 접근 가능(210행). `vote_prompt_template` discussion_summary 뒤(~115행)에 `{us_market_context}` + `.format()`(234-241)에 arg. **액션은 vote_to_action 기계적 도출(332행)이라 US는 rationale만 형성 — 넛지 계약 유지**(투표/confidence 불변).
- technical/fundamental **미주입**(렌즈 순수성).

WS2 후이므로 us_market_context는 이미 **종목별 매칭 서브신호**로 구성됨 → risk/moderator도 해당 종목에 맞는 신호를 봄.

## WS3 — 발굴 시장 틸트 (demand 드라이버)

**T5 선례 준수**(ranker.py:467-472): DEFAULT_REGIME_WEIGHTS 상수 불변(guard ranker.py:79-80 "절대 수정 금지"), 가중치 벡터 무접촉, **bounded·additive·clamp·하위호환** 스타일.

**설계**: AI섹터 전용 strategy score가 없으므로(STRATEGIES=momentum/pullback/flow/meanrev, momentum이 유일 프록시), **모든 후보에 bounded additive 틸트**를 momentum raw_score × demand 신호로:
```
tilt = clamp(raw_scores["momentum"] * demand_signal * TILT_K, 0.0, TILT_MAX)   # TILT_MAX ≈ 0.08
composite = min(1.0, composite + us_crossmarket_bonus + tilt)                    # 기존 T5 term과 나란히
```
- **demand_signal 양(+)일 때만** 상방 틸트(US AI 투자심리 hot → momentum 후보 우대). demand≤0이면 tilt=0(무변경).
- 큐레이션 7종 **밖의 모든 후보**에 적용 → "시장광의" 요건 충족.
- 가중치 벡터·regime 라벨·regime_snapshot **무접촉**(ranker-side 후처리, compute_market_regime fold-in 배제 — EOD-only·게이팅·희석 이유).
- 킬스위치: US_SIGNAL_ENABLED off → demand_signal 없음 → tilt=0. 별도 `US_DISCOVERY_TILT_ENABLED`(기본 on-when-US-on) 불필요, US 게이트에 종속.

**리스크·가드**: STRATEGIES/DEFAULT_REGIME_WEIGHTS 불변(P4 seal 정신 준수), TILT_MAX 소량, 실측 후 조정 주석. scanner가 momentum score를 전 종목 factor_json에 이미 산출하므로 ranker가 raw_scores["momentum"]로 접근 가능(seam 확인).

## WS 관측성 (FE 카드 확장)

기존 `UsSignalCard` + `/discovery/us-signal` 응답을 3 서브신호로 확장: overall 헤드라인 아래 memory/accel/demand 각 %와 구성종목, 큐레이션에 signal_type 배지, demand→발굴 틸트 활성 여부 한 줄. null 안전 규칙 유지.

## 스코프 / 태스크 (plan에서 상세)
- **T1**(BE): us_market_data.py 3 서브신호 계산+캐시 additive 확장 + 테스트.
- **T2**(BE): ai_valuechain.py signal_type 태깅 + 3 lockstep 소비자(coordinator 넛지·scanner 보너스·trading.py 라우트) 매칭 배선 + 테스트.
- **T3**(BE): WS1 risk+moderator 프롬프트 주입 + 넛지-불변 회귀 테스트.
- **T4**(BE): WS3 ranker demand 틸트(bounded/additive/clamp, 가중치 불변) + 테스트.
- **T5**(FE): UsSignalCard 3 서브신호+태그 표시 확장 + vitest.

## 비목표 / 안전
- STRATEGIES·DEFAULT_REGIME_WEIGHTS·regime_snapshot·투표/confidence 로직 무변경.
- 신호 최상위 shape 하위호환(관측성 v1 계약 유지). never-raise·킬스위치(US_SIGNAL_ENABLED)·시크릿 무노출.
- 실 네트워크/실 LLM 테스트 금지(모킹).

## v3 백로그(비포함)
서브신호 가중 실측 회귀·티커셋 추가 확장·틸트 magnitude A/B·demand의 per-ticker 매핑(수요측 한국 종목 발굴 시).
