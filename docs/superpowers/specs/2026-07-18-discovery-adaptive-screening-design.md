# Discovery 레짐 적응형 종목 발굴 + 지식 축적 설계

- 날짜: 2026-07-18
- 상태: 설계 승인됨 (사용자 "승인 합니다")
- 전제: HEAD `f68247e`. 3-트랙 디스커버리(2026-07-18, 스캐너·데이터소스·통합지점) 실측 근거.

## 0. 결정 레코드 (사용자)
| # | 결정 | 선택 |
|---|------|------|
| D1 | 스캔 시점 | **EOD 자동 매일** (장마감 엣지 편입 — 장외라 rate limit 경합 없음) |
| D2 | 자동화 수위 | **자동 승격+보수 게이트** (총량 캡·쿨다운 신설, 진입은 기존 게이트 그대로) |
| D3 | 지식 소비자 | **발굴 성과 폐루프까지** (원장+사후수익 추적+EOD 리포트+전략 패널 배선) |
| D4 | LLM 역할 | **룰 팩터+상위만 LLM** (전 종목 룰 랭킹 → 상위 20~30만 LLM 구조화 검토) |
| D5 | 접근 | A안 승인 — 신규 `services/discovery/` 스코어러, 스캐너는 수집 셔틀, 전략 셋·가중 매트릭스 포함 전체 설계 승인 |

## 1. 현황 실측 (디스커버리 확정 — 설계 구속)
- **quick 스크리닝 사망**: scanner.py:1263-1268 시그널 타입 문자열이 technical_indicators.py:328-420 실제 타입('warning'/'opportunity'/'info')과 불일치 → 항상 HOLD/0.5. 신규 스코어러가 **대체**(레거시 quick/llm 모드는 무변경 유지, 발굴은 새 모드 사용).
- **Rate limit**: 전역 ~1.4req/s+per-api 1.0s, 라이브 매매와 공유(kiwoom_singleton) → 전 종목(~2,500) 풀스캔 40~60분, 장중 반복 불가 → EOD 배치 확정.
- **팩터 원천(추가 TR 불요)**: ka10001(가격+PER/PBR/EPS/BPS/시총, 종목당 1콜)+ka10081(일봉 OHLCV 단일 페이지 — 히스토리 길이 미보장, 계산 전 len 확인 필수)+ka10131(시장당 1콜, 기관/외인 순매수 랭킹+연속일수 — netslmt_tp='2' 순매수 고정)+regime_snapshot(Phase5 컬럼).
- **함정(봉합 대상)**: ①실패 시 가짜 HOLD(price=0) 저장→breadth 오염(scanner.py:970-983) ②유니버스 폴백 15종목 조용히(scanner.py:256-280, 메타 미기록) ③trd_qty 죽은 필드(scanner.py:832) ④워치리스트 총량 캡 부재(무한 성장) ⑤LLM 프리픽스 파싱 조용한 폴백(scanner.py:1219-1252 — 신규 경로는 JSON 구조화) ⑥regime breadth가 당일 완주 스캔 의존(regime.py:49-115) — 체인 재배치로 오히려 해소.
- **자동 승격 배관 존재**(779cfee, 기본 3중 OFF): _promote_results_to_watch_list(scanner.py:540-625)→coordinator.add_to_watch_list(coordinator.py:2721). 신규 승격은 이 배관을 재사용하되 **기존 action/confidence 필드 신뢰 금지**(죽은 quick 산출) — 신규 스코어 기반.
- **진입 파이프라인**(무변경): 워치리스트→ChatCoordinator 1분 주기(장중만, E2)→토론→check_autonomy 게이트. HITL 모드면 토론만 반복(데드엔드)임을 인지 — 이 아크 범위 밖.
- **원장 관례**: storage.db 17테이블, CREATE TABLE IF NOT EXISTS+_ensure_columns(nullable만), accrete(uuid PK) vs 날짜 upsert 두 스타일. scanner_results.db는 별 파일(JOIN 불가, regime.py:46-71 교차 판독 선례).

## 2. 전략 셋 + 레짐 적응 (위임 설계)
**공통 품질 필터**(전략 이전): 현재가>0(가짜 HOLD 차단)·시총 하한(기본 500억, 설정화)·일봉 히스토리 len≥60·관리종목 제외(기존 exclude_warnings)·PER<0 또는 PBR>극단치는 가치 감점만(제외 아님).

| 전략 | 스코어 성분 (0~1 정규화) | 주 레짐 |
|------|--------------------------|---------|
| momentum | MA 정배열(SMA5>20>60)+MACD>시그널+20일 고가 근접도+거래량 증가율(5d/20d) | bullish |
| pullback | SMA60 위+RSI 40~55+SMA20 근접도(±2%)+추세 기울기 | bullish/neutral |
| flow | ka10131 랭킹 존재+기관/외인 연속일수(≥3 가점)+순매수 금액 정규화 | 전 레짐 |
| meanrev | RSI<30 심도+볼린저 하단 이탈 후 복귀+5일 낙폭 과대 | bearish/neutral |

**레짐 가중 매트릭스**(app_settings `discovery:regime_weights` JSON 저장 — 기본값 시드, 추후 전략 합의가 조정 가능한 확장점. 이 아크에선 읽기만):
```
bullish: momentum .40 pullback .25 flow .25 meanrev .10 | 승격 일 캡 5
neutral: flow .30 pullback .30 momentum .20 meanrev .20 | 승격 일 캡 5
bearish: flow .35 meanrev .35 pullback .20 momentum .10 | 승격 일 캡 2 + composite 문턱 상향
```
composite = Σ(전략 스코어 × 레짐 가중). 레짐 라벨은 당일 regime_snapshot.market_sentiment_label(없으면 regime_label, 그것도 없으면 neutral 폴백).

## 3. 아키텍처 — EOD 체인 재배치
현행 마감 엣지(coordinator.py:2359-2374): ①poll_fills ②expire주문 ③daily_snapshot ④run_eod_review ⑤strategy_consensus ⑥fill배리어 ⑦ledger대사 ⑧notify요약.
**신규**: ①② → **★스캔 트리거(discovery 수집 모드, 비동기)+완료 대기(캡 90분, asyncio.wait_for — 타임아웃/실패=경고 로그 후 체인 정상 진행, 승격 스킵)** → ③④(레짐이 **오늘** breadth 사용 — 기존 하루 지연 해소)⑤ → ⑥⑦ → **★발굴 후처리: 사후수익 백필 → 레짐 가중 랭킹 → 상위 N(기본 25) LLM 구조화 검토 → 보수 게이트 승격 → discovery_candidates 원장 기록** → ⑧(digest에 발굴 섹션 포함).
- 킬스위치 `DISCOVERY_ENABLED`(기본 false로 배포→검증 후 on): off면 스캔 트리거·후처리 전부 부재, 체인 byte-동일.
- 실패-무해 계약: 발굴 전 단계는 try/except로 감싸 마감 체인·스케줄러 틱을 절대 깨지 않음(run_eod_review와 동일 계약).
- 휴장일: 마감 엣지 자체가 발화 안 함(기존 _market_was_open 로직) — 발굴도 자동 휴무.

## 4. 데이터 모델
**scanner_results.db** (스캐너 소유 스키마에 ALTER 추가):
- scan_results: `factor_json` TEXT nullable(전략별 스코어+원자 팩터 스냅샷+당일 종가), discovery 모드에서만 기록. 실패 종목=행 미저장(드롭 — 가짜 HOLD 근절, discovery 모드 한정).
- scan_sessions: `universe_fallback` INTEGER nullable(폴백 시 1)+`scan_mode` TEXT nullable.

**storage.db** (관례 준수, initialize()에 CREATE TABLE IF NOT EXISTS):
- `discovery_candidates`(accrete, id uuid PK): trade_date, ticker, name, composite_score, strategy_scores_json, regime_label, rank, llm_verdict_json nullable, promoted INTEGER, skip_reason TEXT nullable, close_price REAL, fwd_1d/fwd_5d/fwd_20d REAL nullable(백필), created_at.
- 백필: EOD 후처리가 "미충전 fwd 필드가 있는 과거 후보"를 조회해 당일 스캔 factor_json의 종가로 (거래일 기준 경과일) 채움. 추가 API 콜 0.
- 요약 쿼리 `get_discovery_performance(days)`: 전략별 승격/미승격 후보 수·평균 fwd 수익률·적중률(fwd_5d>0 비율).

## 5. 보수 게이트 (승격)
- 승격 조건: composite ≥ 문턱(기본 bullish/neutral 0.55, bearish 0.65 — regime_weights JSON에 동봉 저장) ∧ LLM verdict.suitable=true ∧ 품질 필터 통과.
- LLM verdict JSON 스키마: `{"suitable": bool, "confidence": float, "rationale": str, "risks": str}` — llm_verdict_json에 원문 저장.
- 일 캡: bullish/neutral 5, bearish 2. **워치 총량 캡 30 신설**: 초과 시 discovery발(신규 source 필드) 스코어 열위부터 자동 제거, 수동 추가분 보호. WatchedStock에 `source` 필드 추가(blob 직렬화라 마이그레이션 자유, 기존 항목 폴백 'manual').
- 쿨다운: 동일 종목 재승격 7일(discovery_candidates 원장 판정)+현재 보유/워치 중 제외(기존 dedup 재사용).
- 유니버스 폴백 세션이면 승격 전면 스킵(원장에 skip_reason='universe_fallback').
- LLM: llm_provider.generate(task='discovery'), 프롬프트가 JSON만 요구, json.loads 실패=해당 종목 승격 보류(skip_reason='llm_parse_failed', 룰 스코어는 원장 기록). 프리픽스 파싱 금지.

## 6. 폐루프 배선 (D3)
- EOD digest에 `discovery` 섹션(오늘 승격 종목+스코어+전략 태그, 어제 후보 fwd_1d 요약) → 기존 Telegram 요약·FE EOD 리포트 패널에 자동 포함(E3 배관 재사용).
- build_strategy_context(strategy_panel.py:89-151)에 `discovery_performance`(get_discovery_performance(14)) 추가 — 패널리스트가 전략별 발굴 성과를 근거로 스탠스 조정 가능. 가중치 자동 조정은 후속 아크(이번엔 컨텍스트 제공까지).

## 7. 비변경 불변식
- 기존 quick/llm 스캔 모드·API·FE 거동 무변경(discovery는 신규 모드). 수동 스캔·수동 승격 경로 무변경.
- check_autonomy 게이트·토론 파이프라인·HITL 흐름 일절 무변경. 승격 이후는 전부 기존 경로.
- 마감 엣지 체인 기존 8단계의 상호 순서·계약 무변경(사이에 삽입만). DISCOVERY_ENABLED=off면 byte-동일.
- rate limiter 정책 무변경(장외 실행으로 회피).
- 실 네트워크·실 DB는 테스트 금지(합성 OHLCV·목 클라이언트, storage는 tmp DB 픽스처 관례).

## 8. 리스크
| 리스크 | 완화 |
|--------|------|
| 스캔 미완주(60분+) | 90분 캡 후 체인 진행·승격 스킵, 다음 날 재시도 |
| 후보 폭주→토론 비용 | 일 캡+총량 캡 30+기존 쿨다운 30분·max_concurrent 3 |
| 히스토리 부족 종목 | len<60 품질 필터로 제외(단일 페이지 ka10081 한계 명시) |
| 가중치 튜닝 오류 | DB 저장이라 재시작 없이 수정 가능, 원장에 당시 가중 기록(strategy_scores_json에 포함) |
| 신규 모드 회귀 | 킬스위치 기본 off 배포→라이브 1회 수동 검증 후 on |
