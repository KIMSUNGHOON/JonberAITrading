# 발굴 품질 튜닝 설계 — DQ: flow 재정규화 + ETN 제외 + 문턱 재산출

- 날짜: 2026-07-20
- 상태: 설계 승인됨 (사용자 "승인합니다")
- 전제: HEAD `afa0a10`(오늘 5개 아크 배포됨, PID 14464). discovery 승격이 bearish/flow=0 구조에서 상시 0인 문제의 근본 수정.
- 배경(실측 2026-07-20 밤): 오늘 첫 discovery 스캔(84% 부분완주) 데이터로 승격 가능성 검증 → **자연 승격 0**. 원인 3종: ①ETN/스팩·채권 파생상품 유니버스 혼입(상위 오염) ②flow 팩터가 대부분 종목(대형주 포함)에서 0(ka10131 수급이 시장당 1페이지 상위 ~100건만)→composite 4팩터 중 1개 상시 0 페널티 ③bearish 문턱 0.65가 flow 죽는 구조 전제라 도달 불가. 실주식 최고 composite 0.373(bearish 가중).

## 0. 결정 레코드 (사용자)
| # | 결정 | 내용 |
|---|------|------|
| DQ-D1 | flow 완화 | **재정규화만** — flow 결측 종목은 나머지 3팩터 가중 재분배(결측=페널티 제거). ka10131 페이지네이션(커버리지 확대)은 스캔시간·SC 타임아웃 상충으로 별도 백로그 |
| DQ-D2 | 문턱 재검 | **데이터 기반 재산출+재시드** — 재정규화 적용 후 오늘 실주식 composite 분포로 "상위 N개 승격되는" 문턱 산출, app_settings 재시드(기존 DEFAULT와 정확 일치 시만 덮어쓰기). EOD 합의가 이후 계속 조정 |
| DQ-D3 | ETF/ETN | ETF/리츠/ELW는 이미 쿼리 제외 — **ETN·스팩만** 이름 패턴 필터(보수적 키워드, 오탐=누락이 오염보다 안전) |

## 1. 실측 확정 사실 (디스커버리 — 라인은 태스크 시작 시 재확인)
- **유니버스**: StockListItem(models.py:319-343)에 증권종류 필드 없음. get_all_stocks(client.py:1455-1500)가 mrkt_tp=0,10만 호출 → ETF(8)/리츠(6)/ELW(3)/펀드(4)/하이일드(9)/코넥스(50) 구조적 제외. **ETN·스팩은 전용 시장구분 없어 코스피/코스닥 혼입** — 이름 패턴만이 실용책. 필터 지점 client.py:1482-1483 is_normal 컴프리헨션 옆(exclude_warnings 동일 패턴). 채권=별도 시장이라 유니버스 밖(non-issue, 단 채권 파생 ETN은 이름 필터로).
- **flow 스코어**: factors.py:255-268 `_score_flow(flow: Optional[FlowRank])` — flow None(랭킹 밖)=0.0, 존재 시 presence=1.0 바닥으로 최소 0.333. 즉 값 도메인이 이미 결측(0.0) vs 존재(≥0.333) 구분(암묵적). compute_strategy_scores(:295-317)는 4전략 독립 0~1 dict(합성 안 함).
- **composite 조립**: ranker.py:306-308 `raw_scores={k: float(scores.get(k) or 0.0)}; composite=Σ(raw×strategy_weights)` — 재정규화 없음, flow=0이 가중만큼 순손실. factor_json(scanner.py:993-1000)엔 플레인 float만(None 마커 없음).
- **flow_map**: scanner.py:845-877 _build_flow_map이 랭킹 row만 dict, 없는 티커는 flow_map.get→None(scanner.py:989). get_inst_foreign_flow(client.py:643-671)는 시장당 1요청·cont_yn 미루프 → 커버리지 ~100건/시장. 실측: 2026-07-18 세션 대형주 8종 전부 flow=0.
- **문턱/가중**: ranker.py:57-70 DEFAULT_REGIME_WEIGHTS(bullish/neutral thr .55 cap5, bearish thr .65 cap2). _load_regime_weights(:124-147): app_settings 'discovery:regime_weights' 없으면 DEFAULT 시드 후 authoritative, **있으면 저장값 우선**(손상 시만 폴백). ⚠️로컬 DB에 이미 DEFAULT 그대로 시드됨 → 코드 상수만 바꿔선 무효, 재시드 필요.
- **원장 무침습**: discovery_candidates(storage_service.py:245-262) strategy_scores_json=raw 4전략+_weights 서브딕트(ranker.py:560-561, 실적용 가중 기록). _top_strategy_tag(ledger.py:193-216)는 _weights(dict) 배제·raw만 소비 → 재정규화(가중만 변경, raw 무변경)는 성과추적·eod_digest·get_discovery_performance 무영향.

## 2. 태스크 설계
### DQ-1 ETN/스팩 유니버스 제외
- client.get_all_stocks에 `exclude_etf_etn: bool = True`(또는 exclude_derivatives류 명명) 파라미터 — is_normal 필터 옆에서 stk_nm 이름 패턴 제외. 패턴=보수적: 접미/포함 "ETN"·"스팩"·"채권"·"회사채"·"국고"·"통안"·"금리"·"CD "·"인버스"·"레버리지"·"선물"(실주식 오탐 최소 — 실 종목명 샘플로 검증). _load_stock_list(scanner.py:302-305)에서 활성. 추가 API 콜 0. 정상 종목명(예: "SK하이닉스") 미포함 확인 테스트.

### DQ-2 flow 결측 재정규화
- **flow_present 플래그**: scanner discovery 수집(scanner.py:989 부근)에서 factor_json에 `flow_present: bool`(flow_map.get(stk_cd) is not None) 저장. compute_strategy_scores 반환 dict에도 노출(factors.py — atoms 또는 최상위, 실구조 판단).
- **재정규화 헬퍼** `_effective_weights(base_weights: dict, flow_present: bool) -> dict`(ranker.py): flow_present=False면 flow 가중을 나머지 3팩터에 비례 재분배(sum 보존 — 예 bearish {m .10 p .20 f .35 mr .35}→flow 제거 후 {m .10 p .20 mr .35} /0.65 정규화={m .154 p .308 mr .538}). flow_present=True면 base 그대로. ranker.py:306-308 composite 계산에서 raw_scores·effective_weights 사용. 원장 _weights엔 **실적용(재정규화된) 가중** 저장.
- flow_present 소스: factor_json에 플래그 있으면 사용, 없으면(구 스캔) raw flow==0.0을 결측 프록시 폴백(하위호환). threshold 비교는 재정규화된 composite로.

### DQ-3 문턱 데이터 기반 재산출 + 재시드
- 재정규화 구현 후, 오늘(bearish) 부분완주 세션(20260720153027 — SC-1 partial로 소급 or 신규)의 실주식 composite 분포를 스크립트로 재측정(ETN 제외 후) → "상위 ~5개 실주식이 승격되는" 문턱 산출. 예상: 재정규화 후 상위 0.5~0.58 범위(검산: 크레오 0.576·웹젠 0.538) → bearish thr 0.65→~0.55, bullish/neutral 0.55→~0.50 후보(실측 확정, 보고서 근거 기재).
- DEFAULT_REGIME_WEIGHTS 코드 상수 갱신 + **앱 시작 시 1회성 재시드 마이그레이션**(또는 명시 스크립트): 저장된 discovery:regime_weights가 **기존 DEFAULT와 정확히 일치**할 때만 새 값으로 덮어쓰기(사용자/EOD 조정값 보존). 마이그레이션 위치=app.main lifespan 또는 storage init(관례 확인).
- 일 캡(cap5/cap2)은 무변경(문턱만 재산출).

## 3. 비변경 불변식
- 승격 게이트 나머지(LLM suitable·쿨다운 7일·일 캡·watch 총량 캡·universe_fallback 스킵)·discovery EOD 체인·SC 파티셜·계보·rate limiter·정상 flow 종목 4팩터 스코어 무접촉.
- 원장 raw scores·_top_strategy_tag·성과추적 무변경(재정규화는 _weights만).
- 실 네트워크·실 DB 테스트 금지(tmp·목).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| ETN 이름 필터가 정상 종목 오탐 제외 | 보수적 접미/키워드만, 실 종목명 샘플 테스트, 오탐=누락(오염보다 안전) |
| 재시드가 EOD/사용자 조정값 덮어씀 | 기존 DEFAULT와 정확 일치 시만 덮어쓰기 |
| 문턱 완화가 저품질 승격 | 재정규화로 스케일 정상화된 상태의 문턱(억지 아님)+LLM suitable·캡 게이트 유지 |
| 재정규화가 flow 존재 종목 스코어 왜곡 | flow_present=True는 base 가중 그대로(재분배는 결측만)+회귀 핀 |
| 구 스캔 factor_json(flag 없음) 하위호환 | raw flow==0.0 폴백 프록시 |
