# US AI 크로스마켓 신호 → 한국 AI 밸류체인 강화 — 설계

**작성일**: 2026-07-22
**아크**: 간밤 미국 AI 섹터 성과를 한국 결정(sentiment 토론·discovery 발굴)의 입력 신호로 투입 (US 매매 재도입 아님, 신호 데이터만)
**선행**: [[session-2026-07-21-discovery-manual-trigger]] — 사용자 문제제기: 시스템이 US 시장을 전혀 못 봐(US/yfinance 스택 R2 제거) AI 공급망 lead-lag 선행 신호에 눈이 멀어 있음. 07-22 개장 시 삼성전자 +5.7% 갭업(미 AI 반등 반영)을 시스템이 원인 모른 채 재검토하는 사각지대가 실증됨.

**워크플로(사용자 지시)**: 독립 리서치 → 격리 dev(worktree, 라이브 무중단) → 검증 → 검증 후 production integration.

---

## 1. 문제

시스템의 regime·sentiment·discovery flow는 **전부 한국 시장만** 본다. 한국 AI 밸류체인(삼성전자·SK하이닉스 등 메모리/HBM)은 간밤 미국 AI 섹터(반도체)를 **선행 추종**하는데, 그 선행 신호가 시스템 입력에 전혀 없다. 결과: 미 AI 반등이라는 촉매를 모른 채 한국 AI주를 평가 → 어제 발굴 승격 0, 오늘 삼성전자 갭업도 "고평가"만 보고 반려할 위험.

## 2. 리서치 요약 (설계 근거)

**lead-lag: 실재하나 좁고 기계적** (외부 리서치, 2026 실시간 증거 + 1건 오래된 학술):
- 삼성전자+SK하이닉스 = KOSPI 시총 **40–52%** → "KOSPI가 SOX 추종"은 사실상 두 종목 현상. **광의 지수(S&P500) 상관 붕괴(0.5→0.025), 반도체 섹터(SOX) 특화 신호만 신뢰.**
- **MU(마이크론)** = 메모리 직접 read-through(가장 깨끗) · **NVDA** = HBM 수요(SK하이닉스가 NVDA HBM4 58–70% 공급) · **SMH/SOXX ETF** = 섹터 베타(무료 API 티어에 ^SOX 지수 없음 → ETF).
- 한미반도체(042700)는 이 채널 약함(제외). 관계는 이제 양방향/얽힘. **override 요인**(자체실적·국내수급 쇼크·수출규제)이 신호를 압도할 수 있음.
- ⭐**신호는 "확신 넛지"로만** — 독립 매매 엣지 아님(단순 오버나이트 아노말리는 거래비용에 소멸). 기존 파이프라인이 이미 하려는 판단의 사이징/확신을 미세 조정하는 용도.

**데이터 소스**: **Finnhub**(무료 `/quote`가 `pc` prev-close·`dp` %change 직접 제공, 60콜/분, 인덱스 미지원→ETF 사용). provider 교체 가능 인터페이스로 설계(Stooq 봇차단·무료티어 변동성 대비).

**티커 v1 코어**: **SMH + MU + NVDA** (섹터베타 + 메모리 read-through + HBM 수요). 한국 대상: 005930 삼성전자·000660 SK하이닉스.

## 3. 목표 / 비목표

**목표**: 간밤 미 AI 섹터 성과를 bounded 신호로 산출·캐시하고, AI 밸류체인 한국 종목의 **sentiment 토론(프롬프트 넛지)**과 **discovery composite(소량 가산)**에 입력한다. 킬스위치로 완전 격리, off 시 기존과 100% 동일.

**비목표**: US 매매 재도입 · regime 실시간 투입(EOD 타이밍이 당일엔 늦음, v1 제외) · 풀 신호식(vol-normalize/tanh/decay, v2로) · 5번째 discovery 전략 승격(STRATEGIES 확장, DQ 재보정 유발 — v2로) · 투표/문턱/게이트 로직 변경.

## 4. 설계 (최소 침습 v1)

### 4.1 데이터 fetcher + provider 인터페이스
- **신규 `services/trading/us_market_data.py`** — `market_data.py`의 `fetch_index_snapshot`/`fetch_market_flow`와 동일 shape(순수 async, 정규화 dict, 실패 시 None, **never-raise**).
- `async def fetch_us_ai_overnight(tickers: list[str]) -> Optional[dict]`: Finnhub `/quote`로 각 티커의 `dp`(%change)·`pc`·`c` 수집 → `{ticker: {"chg_pct": float, "prev_close": float}}`. provider는 얇은 함수 경계(`_finnhub_quote(ticker, api_key)`)로 분리해 교체 가능.
- `FINNHUB_API_KEY`(app/config.py, .env) 미설정/빈값이면 None 반환(fail-harmless).

### 4.2 신호 산출 (v1 단순, bounded)
- `def compute_us_ai_signal(snapshot: dict) -> Optional[dict]`: SMH·MU·NVDA의 `chg_pct`를 가중 평균(SMH 0.5·MU 0.25·NVDA 0.25, 결측 티커는 가중 재정규화) → **`signal_pct`**(가중 %change) → **`signal`** = `clamp(signal_pct / SCALE, -1.0, 1.0)`(SCALE 상수, 예 3.0%=±1 포화; v1 단순, 실측 후 조정) → `{"signal": float, "signal_pct": float, "as_of": date, "components": {...}}`. 티커 전부 결측이면 None.
- (v2 후보: winsorize·EWMA vol-normalize·tanh·세션 decay — 리서치 formula. v1은 배관·격리·검증 우선.)

### 4.3 사전-장 배치 + app_settings 캐시
- **신규 pre-open cron** — `krx_holiday.start_scheduler(hour=…)` 패턴(app/main.py lifespan) 또는 `ChatCoordinator.start()`의 `AsyncIOScheduler`에 `add_job(trigger='cron', hour=8, ...)` 추가(신규 객체 없이 최소 diff). US 마감 후·KR 개장(09:00) 전 1회/일: fetch → compute → **`app_settings` 키 `us_ai_signal`에 JSON 캐시**(`get_app_setting`/`set_app_setting`, `discovery:regime_weights` 패턴). 이 캐시 하나가 전 소비처 단일 소스.
- 개장 후에도 캐시된 당일 신호 유효(오버나이트 값은 세션 내 고정). 날짜(as_of)로 stale 판별.

### 4.4 종목 식별 (큐레이션)
- **신규 `services/discovery/ai_valuechain.py`** — 정적 `AI_VALUECHAIN_TICKERS: dict[str, str]`(v1 코어: `"005930":"삼성전자","000660":"SK하이닉스"`; 확장 여지 주석) + `def is_ai_valuechain(ticker: str) -> bool`. `DEFAULT_REGIME_WEIGHTS`처럼 손 큐레이션(코드에 섹터 매핑 부재 실측 확인). sentiment·discovery 양쪽에서 import.

### 4.5 sentiment 주입 (프롬프트 넛지, 투표 로직 불변)
- `MarketContext`(models.py:~218)에 **`us_market_context: Optional[str] = None`** 신규 필드(`strategy_directive` 패턴).
- `coordinator._fetch_market_context()`(~1206-1272, news-sentiment 블록 뒤)에서: `is_ai_valuechain(ticker)` AND 캐시된 `us_ai_signal`(당일) 존재 시에만 `us_market_context` = 한 줄 요약(예: "간밤 미 AI 반도체(SMH +2.1%·MU +3.4%·NVDA +1.8%) 강세 — 이 종목은 AI 공급망(메모리/HBM)으로 선행 추종 경향이나 확정 신호 아님, 자체 밸류에이션·수급이 우선"). 결측/off/비-AI종목이면 None(빈 문자열).
- `sentiment_agent.py` `analysis_prompt_template`(66-89)·`vote_prompt_template`에 `{us_market_context}` 한 줄 추가(None→빈). **confidence 캡·투표 도출 로직은 불변** — LLM 정성 판단에만 노출(하드코딩 투표 밀기 없음).

### 4.6 discovery 주입 (composite 소량 가산, 하위호환)
- `scanner._scan_stock_discovery()`의 factor_json 구성부(~1011-1025)에 **`us_crossmarket_bonus: float`** top-level 키 추가: `is_ai_valuechain(stk_cd)` AND 캐시 신호 존재 시 `max(0.0, signal) * US_BONUS_WEIGHT`(예 0.05), 아니면 0.0.
- `ranker.rank_candidates()`의 가중합 직후(~468): `composite = min(1.0, composite + factor.get("us_crossmarket_bonus", 0.0))`. **`STRATEGIES`/`DEFAULT_REGIME_WEIGHTS`/`_effective_weights` 전혀 불변, 구 factor_json은 `.get(...,0.0)`으로 완전 하위호환.** (넛지 규모 작게 — 리스크 규율/문턱 불변, 데이터 아티팩트로 승격 강제 방지.)
- (선택) `ranker._build_llm_messages()`(503-527) LLM 검토 프롬프트에도 한 줄 노출(스코어 수학 무침습 2차 노출면).

### 4.7 킬스위치
- **신규 `US_SIGNAL_ENABLED: bool = False`**(app/config.py, `DISCOVERY_ENABLED` 패턴, 기본 off — 미검증 외부 소스). fetcher·cron·sentiment 주입·discovery 주입 전부에서 체크. off 시 전 경로가 기능 추가 이전과 **100% 동일 거동**.

## 5. Global Constraints

- **킬스위치 off = 완전 무변경**: `US_SIGNAL_ENABLED=False`(기본)면 fetch·주입 어느 것도 실행 안 됨.
- **never-raise/fail-harmless**: US fetch·신호·캐시 실패는 로그만, 한국 파이프라인(토론·발굴·매매)을 절대 막지 않는다.
- **리스크 규율·판단 로직 불변**: 투표·confidence 캡·consensus_threshold·discovery 문턱·게이트·손절 무변경. US 신호는 프롬프트 넛지 + 소량 composite 가산(확신 넛지)일 뿐.
- **하위호환**: 신규 factor_json 키·MarketContext 필드는 optional, 구 데이터/off 경로 무영향.
- **실 네트워크/LLM 금지(테스트)**: Finnhub·LLM은 mock/스텁.
- **US 매매 없음**: 신호 데이터만, OrderRequest/체결 경로 무접촉.

## 6. 테스트

- **fetcher**: Finnhub `/quote` 응답 mock → 정규화 dict(chg_pct/prev_close); 키 미설정→None; 일부 티커 실패→나머지 유지; 전량 실패→None.
- **신호**: compute_us_ai_signal — 가중·클램프·결측 재정규화·전량결측 None. 경계(±SCALE 포화).
- **큐레이션**: is_ai_valuechain(005930)=True, 임의 종목=False.
- **sentiment 주입**: AI종목+캐시 신호→MarketContext.us_market_context 채워짐+프롬프트 포함; 비-AI/off/결측→None+프롬프트 불변. 투표 로직 불변 회귀.
- **discovery 주입**: AI종목→factor_json us_crossmarket_bonus>0→composite 가산; 비-AI/off→0→composite 불변. 구 factor_json(.get) 하위호환.
- **킬스위치**: US_SIGNAL_ENABLED=False → 전 경로 no-op(주입 0, fetch 미호출).
- **회귀**: 기존 agent_chat/discovery/trading 스위트 green.

## 7. 배포 후 검증 + 통합 (사용자 워크플로)

1. **격리 dev**: worktree에서 구현·단위검증(mock, 키 불필요). 라이브 서버 무영향(공유 체크아웃 미병합).
2. **pre-integration 라이브 fetch 검증**: `FINNHUB_API_KEY`를 `.env`에 추가 후, worktree에서 standalone 스크립트로 실 Finnhub fetch→signal 산출→값 타당성(부호·규모) 확인(라이브 서버 무접촉).
3. **integration**: 단위+라이브 fetch 검증 통과 시 FF 병합→**장 마감 후(15:30~16:35 스캔 창 회피) 또는 개장 전** 재시작(사용자 `!`). `US_SIGNAL_ENABLED=true`·`FINNHUB_API_KEY` env 세팅.
4. **post-integration 스모크**: pre-open cron 발동(또는 수동 1회) → `app_settings.us_ai_signal` 캐시 확인 → AI종목 토론 프롬프트/발굴 factor_json에 신호 반영 확인.

## 8. 파일 요약

- 신규: `services/trading/us_market_data.py`(fetcher+provider), `services/discovery/ai_valuechain.py`(큐레이션+헬퍼).
- 수정: `app/config.py`(US_SIGNAL_ENABLED·FINNHUB_API_KEY), `app/main.py` 또는 `services/agent_chat/coordinator.py`(pre-open cron), `services/agent_chat/models.py`(MarketContext.us_market_context), `services/agent_chat/coordinator.py`(_fetch_market_context 주입), `services/agent_chat/agents/sentiment_agent.py`(프롬프트), `services/background_scanner/scanner.py`(factor_json bonus), `services/discovery/ranker.py`(composite 가산 + 선택 LLM 프롬프트).
- 테스트: `tests/test_services/test_trading/`(fetcher·signal), `tests/test_services/test_agent_chat/`(주입), `tests/test_services/test_discovery_*`(bonus·큐레이션).

관련: [[session-2026-07-21-discovery-manual-trigger]]
