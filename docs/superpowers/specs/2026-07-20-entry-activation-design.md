# 진입 활성화 설계 — P2: 발굴→토론 연결 + 투표 방향 균형 + 문턱 정리

- 날짜: 2026-07-20
- 상태: 설계 확정(사용자 "P2 준비" 지시 — 세부 결정은 검토 실측 근거로 컨트롤러 확정, §0에 플래그)
- 전제: HEAD `332b37e`. 진입 깔때기 검토(2026-07-20, 2트랙 실측) 근거. 장마감 1h40m 전 시작 — E-1은 EOD 전 착지 목표.
- 배경(실측): 사상 900표 중 buy/strong_buy 0표(과거 BUY 8건=버그 화석·테스트 확인). 기회 감지(1단)는 정상 작동(2/4종목 반복 트리거). 병목=②투표 방향(구조 편향 3종)+③discovery 승격→토론 단절(target_entry_price 미전달+confidence 0.55~0.65 < 문턱 0.75).

## 0. 결정 레코드 (컨트롤러 확정 — 근거 명시)
| # | 결정 | 내용·근거 |
|---|------|-----------|
| P2-D1 | E-1 승격 배선=가격근접 경로 활용 | 승격 시 target_entry_price(후보 종가 기반)+stop/tp(활성 전략 노브 산출)+confidence=composite 전달 — _detect_opportunity 무변경(기존 가격근접 분기가 자연 작동). 문턱 0.75 완화는 하지 않음(검증 전 관대화 금지) |
| P2-D2 | E-2 편향 제거≠매수 강제 | risk 지시를 양면 평가로 대칭화하되 리스크 관리 역할·가중 0.30 유지. sentiment는 NewsSentimentAnalyzer 실배선(실패=기존 등락률 폴백)+momentum 재라벨 제거(중복 신호). 시총 ×1e8 보정 전파(scanner 픽스와 동일 근거) |
| P2-D3 | E-3 문턱=조정 가능화(완화 아님) | consensus_threshold 하드코딩→전략 노브(entry_conditions, 바운드 [0.60, 0.85], 기본 0.75 불변 — EOD 합의가 데이터 기반 조정). min_technical_score=죽은 필드→전략 컨텍스트로 프롬프트 주입(soft guidance, 하드 게이트 아님) |
| P2-D4 | 안전 불변 | 게이트 체인·손절 규율(S)·계보(L)·HITL 무접촉. 매수는 여전히 4-에이전트 합의+게이트 전 관문 경유 — 이 아크는 "막힌 문을 여는" 것이지 "검문을 없애는" 것이 아님 |

## 1. 실측 앵커 (검토 확정 — 라인은 태스크 시작 시 재확인)
- **끊김 ③**: services/discovery/ranker.py:635-645 promote_candidates→add_to_watch_list에 target_entry_price/stop_loss/take_profit 미전달(None)+confidence=composite. _detect_opportunity(agent_chat/coordinator.py:619-668): target 없으면 confidence≥0.75 폴백뿐 → discovery 후보 영구 미발화. discovery_candidates 현재 0행(오늘 밤 첫 발동 예정).
- **편향 ①**: risk_agent.py:47-67 system_prompt+:138 "보수적으로 판단하세요" — 4에이전트 중 유일한 방향 지시, 가중 최고 0.30(models.py:80-85). 실측 risk hold 52%.
- **편향 ②**: sentiment_agent.py:182-184 momentum=price_change_pct 재라벨(technical과 메아리 — sell계열 87.5% vs 89% 동조). NewsSentimentAnalyzer(services/news/sentiment.py)는 정상 구현·미배선(coordinator._fetch_market_context:1153-1178이 뉴스 50건 count만).
- **편향 ③**: coordinator.py:1195 market_cap=mrkt_tot_amt 무보정(억원) → fundamental_agent.py:293-303이 "0억원" 표시 → LLM이 "데이터 오류"를 보류 근거로 실사용(워치 레코드 실측). scanner.py:852-856은 이미 ×1e8 보정(2026-07-18).
- **문턱**: models.py:272 consensus_threshold=0.75 하드코딩(chat_room.py:55 동일). 실측 NO_ACTION 다수가 0.66~0.71 미달 구간. strategy.py:54 min_technical_score 소비처 0(정의·UI 편집만). _build_strategy_context(coordinator.py:980-1024)는 entry_conditions 미주입.
- 오늘 국지 장애(LLM 라우터 무백엔드 3h11m, 81% 토론 증발 — 재시작 자가치유)는 범위 밖 백로그(관측성).

## 2. 태스크 설계
### E-1 discovery 승격 배선 완결 (EOD 전 착지 목표)
- promote_candidates: add_to_watch_list 호출에 `target_entry_price=cand.close_price`(발굴 종가 — "이 가격대면 검토 가치" 의미론, 익일 시가가 ±3% 근접 시 토론 자연 발화), `stop_loss=close×(1−전략 stop_loss_pct)`, `take_profit=close×(1+take_profit_pct)`(활성 전략 노브 — coordinator.risk_params 아닌 strategy exit_conditions, 실소스 확인), `confidence=cand.composite` 유지.
- 승격 로그에 target/stop/tp 포함. 기존 manual 워치 항목 무접촉.
- 테스트: 승격→WatchedStock 필드 채움→_detect_opportunity(목 현재가 근접)가 True 반환하는 종단 핀.

### E-2 투표 방향 균형 (편향 제거 3종)
- ①risk_agent 프롬프트: "보수적으로 판단하세요"→"손실 리스크와 기회비용(놓친 상승)을 양면 평가해 판단하세요"류 대칭 문구+system_prompt의 일방 하방 지시 완화(리스크 요인 제기 역할은 유지). 가중 0.30 불변.
- ②시총 보정: coordinator._fetch_market_context의 mrkt_tot_amt에 ×100_000_000(scanner와 동일 주석·근거). fundamental 프롬프트 표시 정상화.
- ③sentiment 실배선: _fetch_market_context가 NewsSentimentAnalyzer로 뉴스 상위 N(기본 5)건 실분석(LLM 1콜, 타임아웃·실패=기존 등락률 라벨 폴백+로그) → MarketContext.news_sentiment에 실감성. sentiment_agent의 momentum 재라벨 제거(price_change_pct는 프롬프트에 이미 별도 노출 — 중복 삭제).
- 테스트: 프롬프트 스냅샷 핀(하방 지시 부재·양면 문구 존재)+시총 표시 수기 대조+감성 폴백 체인.

### E-3 문턱·조건 정리
- consensus_threshold: EntryConditions에 `consensus_threshold: float = 0.75`(ge=0.5 le=0.9) 신설 → ChatSession/chat_room이 활성 전략에서 읽음(부재=0.75 기존값). STRATEGY 소비는 프리셋·EOD 합의 조정 대상(KNOB_BOUNDS [0.60, 0.85] 추가 — strategy_consensus 실구조 확인 후 배선, 스키마 밖이면 문서화만).
- min_technical_score 등 entry_conditions를 _build_strategy_context에 주입(에이전트·모더레이터 프롬프트에 "진입 기준" 섹션 — soft guidance 명시).
- 테스트: 전략 값이 세션 문턱에 반영·부재 폴백·컨텍스트 주입 스냅샷.

## 3. 비변경 불변식
- check_autonomy 게이트·손절 자동(S)·계보(L)·인플라이트 가드·HITL 폴백·_detect_opportunity 문턱 수치(0.03/0.75) 무접촉.
- 매수 실행 경로 로직 무변경 — 변경은 "투표 입력의 질(편향·데이터)"과 "발굴 연결·문턱의 조정 가능성"뿐.
- 실 네트워크·실 DB 테스트 금지(NewsSentimentAnalyzer는 목).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 편향 제거 과교정→무분별 매수 | 문턱 수치 불변+게이트 전 관문 유지+리뷰 포커스 "매수 강제화 문구 금지" |
| 뉴스 감성 LLM 지연이 토론 블록 | 타임아웃(기본 20s)+실패 폴백, 토론당 1콜 한정 |
| E-1 산출 stop/tp가 전략과 불일치 | 활성 전략 노브 단일 소스+수기 대조 테스트 |
| EOD 전 미착지 | E-1만 우선 병합 가능 구조(태스크 독립) — 미착지 시 오늘 승격분은 휴면(무해), 익일 재승격 |
