# Telegram 시각 리포트 설계 — 개장전 · 개장후 · 발굴

작성: 2026-08-13 · 상태: **설계 승인됨, 구현 대기**

## 1. 문제

폰으로 가는 알림 3종이 시스템이 만든 분석의 **극히 일부**만 전달한다.

2026-08-13 실측:

| | 시스템이 만든 것 | 폰에 간 것 |
|---|---|---|
| 보유 5종 토론 | **30회 · 메시지 390건** | 없음 |
| 결정 `rationale` | 평균 **1,011자** × 121건 | 없음 |
| 에이전트별 투표·근거 | 결정당 4건 | 없음 |
| PER · PBR · EPS | 토론마다 조회 | 없음 |
| RSI · MACD · 거래량비 | 토론마다 조회 | 없음 |
| 뉴스 | 종목당 최대 50건 조회 | 건수·감성만 |

장전 브리핑이 실제로 보낸 것은 레짐 한 줄, 목표 노출도, 보유 종목 코드와 수량,
"조회 실패" 몇 개다.

이것은 이 리포에서 반복되는 패턴이다 — **만들어졌으나 닿지 않는다.**
어제 규명한 [발굴 승격 게이트 실명](2026-08-12-discovery-promotion-evidence-design.md)과
같은 구조다. 그때는 게이트가 재료를 못 봤고, 이번엔 사용자가 못 본다.

### 1-1. 이 문제가 실제로 비용을 냈다

2026-08-13 오전, 나는 *"목표 8.01%가 신규 진입을 막고 있는지 확인이 필요하다"* 고
관측 항목으로 올렸다. 답은 **이미 그날 토론 121건 안에 적혀 있었다**:

> 리스크 관리자: *"종목 비중 3.6%가 한도 2.8% 초과, 포트폴리오 주식비중 **11.8%**가
> 목표 **8.0%** 초과 — 신규 진입 불가"*

리포트가 있었으면 관측할 필요가 없는 사실이었다.

## 2. 전달 형식 — 실증으로 결정했다

Telegram은 **메시지 안에서 HTML 페이지를 렌더하지 못한다.**
`parse_mode="HTML"`이 지원하는 것은 `b · i · u · s · a · code · pre · blockquote ·
tg-spoiler` 인라인 태그뿐이다. `<table>`·`<div>`·CSS는 무시되거나 파싱 에러가 된다.

2026-08-13 14:00 실물 발송으로 확인:

| 형식 | 크기 | iPhone Telegram |
|---|---|---|
| `.html` | 11 KB | ✅ **열린다** — 채택 |
| `.pdf` | 467 KB | 열리지만 불필요 |
| `.png` | 131 KB | 사용자가 제외 |

**결정: `.html` 단일 파일 첨부.**

⭐ **그 결과 Chrome이 필요 없어졌다.** PDF/PNG를 뺐으므로 헤드리스 브라우저
서브프로세스, 렌더 지연(4.7초), 실패 경로가 전부 사라진다. jinja2로 문자열을 만들어
그대로 보낸다. **새 의존성 0.**

## 3. 아키텍처

```
backend/services/reports/           ← 신규 패키지
  __init__.py
  models.py      리포트 데이터 모델 (dataclass)
  collect.py     수집 — 보유별 리서치·뉴스·레짐·성과
  render.py      jinja2 → 단일 HTML 문자열
  templates/
    base.html        공통 레이아웃 + 전체 CSS (인라인)
    _position.html   보유 종목 카드 (3종이 공유)
    premarket.html
    postmarket.html
    discovery.html
```

`services/telegram/service.py`에 `send_document()` 한 메서드만 추가한다.

### 3-1. 데이터 흐름

```
agent_chat_decisions  ─┐
agent_chat_votes      ─┤
regime_judgment       ─┼→ collect.py → ReportData → render.py → HTML str
NewsService           ─┤                                            │
기존 collect_brief    ─┘                                            ▼
                                             telegram.send_document(bytes, filename)
```

### 3-2. 기존 코드에 손대는 곳

| 파일 | 변경 |
|---|---|
| `services/telegram/service.py` | `send_document()` 추가 · `_send_message` 재시도 규칙 정정(§7) |
| `services/telegram/briefing.py::send_morning_brief` | 텍스트 발송 뒤 리포트 첨부 |
| `services/trading/coordinator.py:4581` | `send_daily_summary` 뒤 리포트 첨부 |
| `services/discovery/orchestrator.py:179` | `send_discovery_promotion` 뒤 리포트 첨부 |
| `services/telegram/config.py` | `TELEGRAM_REPORT_HTML_ENABLED` 게이트 추가 |
| `.gitignore` | `backend/data/reports/` 추가 (§6-3) |

**텍스트 메시지는 지금 것을 그대로 둔다.** HTML 생성이나 첨부가 실패했을 때
유일한 정보원이기 때문이다. 텍스트를 줄이는 것은 리포트가 안정된 뒤의 별건이다.

## 4. 보유 종목 카드 — 이 설계의 핵심

3종 리포트가 공유하는 단위다(`_position.html`).

```
┌──────────────────────────────────────────────┐
│ 팬오션 028670                       −5.13%   │
│ 3,115주 · 평단 5,969 → 현재 5,710            │
│ ▓▓▓▓▒▒▒▒▒▒▒▒▒  손절 5,520 · 여유 3.33%       │
│                                              │
│ 오늘 토론 6회 → HOLD   합의 79%   ⚠️ 이견 1  │
│                                              │
│ 🔧 기술     HOLD 58%                         │
│    정배열·MACD +47, 거래량 0.60x 부족         │
│ 📊 펀더멘털  BUY 62%            ← 반대표      │
│    PER 10.11(업종 12~15) · PBR 0.53          │
│ 💬 심리     HOLD 58%                         │
│    뉴스 50건 중립, 단기 −1.72%                │
│ ⚖️ 리스크    HOLD 62%                         │
│    비중 3.6% > 한도 2.8% — 추가매수 불가       │
│                                              │
│ RSI 57.2 │ 거래량 0.60x │ 추세 bullish        │
│ PER 10.11│ PBR 0.53    │ EPS 564             │
│                                              │
│ 📰 최신 뉴스                                  │
│  · 한국경제 · 2시간 전    ●중립               │
│    「HMM·팬오션 운임 지수 3주째 …」            │
│  · 매일경제 · 5시간 전    ●긍정               │
│    「벌크선 시황 개선 …」                      │
└──────────────────────────────────────────────┘
```

### 4-1. 데이터 출처 매핑

모든 필드의 출처를 명시한다. 새로 계산하는 것은 없다 — **전부 이미 저장된 값**이다.

| 화면 요소 | 출처 |
|---|---|
| 종목명·코드·수량·평단·현재가·손익% | `GET /api/kr_stocks/positions` |
| 손절가 | 코디네이터 포지션 스냅샷. ⚠️ **두 엔진이 서로 다른 손절가를 든다**(PositionManager vs coordinator, 실측 차이 470~6,095원) → **출처 엔진을 함께 표기**한다 |
| 손절 여유 % | `(현재가 − 손절가) / 현재가` |
| 토론 횟수 | `COUNT(agent_chat_decisions)` where ticker, trade_date |
| 최종 결정·합의도 | `agent_chat_decisions.action` / `.consensus_level` (최신 1행) |
| 에이전트별 투표·신뢰도·근거 | `agent_chat_votes.{agent_type, vote, confidence, reasoning}` |
| 반대표 판정 | `vote != 최종 action`인 행 |
| RSI·거래량비·추세·정배열 | `agent_chat_decisions.behavioral_signals` (JSON) |
| PER·PBR·EPS | 🔴 저장돼 있지 않다 → **Kiwoom `ka10001` 리포트 시점 조회** (§4-3) |
| 뉴스 감성·건수 | `agent_chat_decisions.{news_sentiment, news_count}` |
| 뉴스 헤드라인 | **`NewsService.search_stock_news()` 리포트 생성 시점 조회** |

### 4-2. 근거 텍스트 길이

`agent_chat_votes.reasoning`은 200~500자다. 카드에는 **첫 문장 또는 120자**까지만
싣고, 잘렸으면 `…`을 붙인다. 전문은 담지 않는다(사용자 선택: "4에이전트 카드 +
지표 스트립 + 최신 뉴스", 사회자 종합 전문은 제외).

`key_factors`는 JSON 배열이며 이미 요약된 한 줄들이다. **`reasoning` 대신
`key_factors[0]`을 우선 사용하고, 비어 있을 때만 `reasoning`을 자른다.**

### 4-3. 🔴 PER/PBR/EPS는 구조화되어 있지 않다

`agent_chat_decisions`에 펀더멘탈 컬럼이 없다. 값은 fundamental 에이전트의
`reasoning` 자연어 안에만 있다(`"PER 10.11배로 업종 평균…"`).

**자연어 파싱은 하지 않는다.** LLM이 문구를 바꾸면 조용히 깨지고, 잘못된 숫자를
리포트에 싣는 것은 값이 없는 것보다 나쁘다.

대신 **Kiwoom `ka10001`을 리포트 생성 시점에 조회한다** — 어제 만든
`services/discovery/enrich.py::_make_stock_info_fetch`와 같은 경로다.
보유 5종이면 5회, `min_interval=1.0`으로 약 5초.

조회 실패 시 해당 칸은 `—`로 남기고 리포트는 나간다.

## 5. 리포트 3종

### 5-1. 개장전 (`premarket.html`) — 08:30

| 섹션 | 내용 |
|---|---|
| 헤더 | 날짜 · 레짐 라벨 · 신뢰도 · `degraded_json` 태그 |
| 지표 카드 3 | 목표 노출도 · 보유 종목 수 · 평가손익 |
| **노출도 추이** | 최근 5거래일 `effective_target_pct` 막대 + 레짐 라벨. 라벨과 목표가 어긋나면 콜아웃 |
| **오늘의 제약** | 리스크 에이전트가 말한 진입 가능 여부 — 실제 노출도 vs 목표, 슬롯, 종목당 상한, 일일 한도 |
| **보유 N종 리서치** | §4 카드 × N (**어제** 토론 기준 + 밤사이 뉴스) |
| 어제 로테이션 | 진입·청산과 실현손익 |
| 준비 | 자율 모드 · 일일 거래 · 지수 시계열 최신일·소스 |

"오늘의 제약" 섹션은 §1-1의 사고를 막기 위한 것이다. **왜 못 사는지가 브리핑
첫 화면에 있어야 한다.**

### 5-2. 개장후 (`postmarket.html`) — EOD 체인

| 섹션 | 내용 |
|---|---|
| 헤더 | 날짜 · 당일 손익 · 체결 건수 |
| **오늘 무슨 일이 있었나** | 체결·손절·익절 타임라인. 0건이면 "0건" + 이유 |
| **보유 N종 리서치** | §4 카드 × N (**오늘** 토론 종합, 결정 변화 표시) |
| 실현손익 | 청산 종목별 진입·청산·순손익 |
| 전략 개정 | `strategy_revisions` 최신 — 패널이 바꾼 노브와 방향(↑↓) |
| 발굴 | 스캔 결과 요약 (상세는 5-3) |

`strategy_revisions` 블록은 **직전 값과의 차이**를 함께 보여준다. 4일 연속 축소
같은 흐름은 값 하나만 보면 안 보인다.

### 5-3. 발굴 (`discovery.html`) — EOD 발굴 파이프라인

승격 종목별로:

| 요소 | 출처 |
|---|---|
| 종합점수 · 랭킹 · 문턱 | `discovery_candidates.{composite, rank}` |
| **전략별 원점수 분해** | momentum · pullback · flow · meanrev 막대 |
| PER · PBR · 시총 | `discovery_candidates.{per, pbr, market_cap}` (어제 추가) |
| 뉴스 헤드라인 | `discovery_candidates.news_count` + 리포트 시점 재조회 |
| **LLM 판단 근거** | `discovery_candidates.{llm_rationale, llm_confidence}` (어제 추가) |
| 시장경보 | `skip_reason LIKE 'market_warning:%'` — 차단된 종목도 **차단 사유와 함께 표시** |

차단된 종목을 숨기지 않는다. 무엇이 걸러졌는지가 게이트가 일한다는 증거다.

## 6. 실패 처리

### 6-1. 리포트가 알림을 죽이면 안 된다

```
텍스트 메시지 발송  ← 항상 먼저, 항상 시도
      ↓
HTML 생성 (try)     ← 실패해도 위는 이미 나갔다
      ↓
첨부 발송 (try)     ← 실패는 로그만
```

리포트 경로 전체를 `try/except Exception`으로 감싸고 `logger.warning`만 남긴다.
**리포트 예외가 호출자에게 전파되면 안 된다** — 발굴 파이프라인이나 EOD 체인이
리포트 때문에 죽으면 안 된다.

### 6-2. 섹션 독립 저하

`format_brief`의 기존 철학을 그대로 쓴다 — *"섹션 하나가 죽어도 나머지는 나간다."*

| 실패 | 결과 |
|---|---|
| 뉴스 조회 실패/쿼터 소진 | 그 종목 뉴스 블록만 "조회 실패" |
| Kiwoom `ka10001` 유량 초과 | PER/PBR 칸만 `—` |
| `agent_chat_votes` 없음 | 카드에 "토론 없음" — 신규 편입 종목의 정상 상태 |
| 포지션 조회 실패 | 보유 섹션 전체가 "조회 실패", 나머지 섹션은 렌더 |

### 6-3. 🔴 리포트 파일이 공개 리포에 올라가면 안 된다

`backend/data/`는 `.gitkeep`만 추적되고 `*.db`만 무시된다. **`.html`은 무시 대상이
아니다.** 리포트에는 보유 종목·수량·평단·계좌 손익이 들어가고 이 리포는
**공개(`github.com/KIMSUNGHOON/JonberAITrading`)** 다.

- 저장 위치: `backend/data/reports/YYYY-MM-DD-{kind}.html`
- **`.gitignore`에 `backend/data/reports/` 추가** — 이 작업의 첫 커밋에 포함한다
- 보존: 최근 **14일**, 그 이전은 생성 시 삭제

### 6-4. 파일명

`{kind}-{trade_date}.html` (예: `premarket-2026-08-13.html`).
Telegram 대화에서 날짜로 찾을 수 있어야 한다.

## 7. 전송 재시도 — 기존 규칙의 정밀화

### 7-1. 관측

2026-08-13 실측: `telegram_send_failed` **27건** / `plain_fallback_ok` **25건**
→ **2건은 어디로도 가지 않았다.**

```
13:50  NetworkError  (httpx.ConnectError: All connection attempts failed)
13:54  TimedOut
```

### 7-2. 현재 동작은 결함이 아니라 의도다

`service.py:176-183`에 이유가 적혀 있다:

> *"TimedOut/NetworkError/Forbidden 등 그 외 TelegramError는 전송 여부가
> 불확실하므로(응답만 유실됐을 수 있음) 재시도하지 않는다."*

중복 발송을 피하려는 판단이며 타당하다. **이것을 뒤집지 않는다.**

### 7-3. 다만 연결 실패는 구별할 수 있다

`httpx.ConnectError`는 **연결이 성립한 적이 없다**는 뜻이다 — 서버에 도달하지
않았으므로 중복 위험이 없다. PTB는 이것을 `NetworkError` **정확히 그 타입**으로
올린다. 하위 클래스는 둘뿐이고 각각 이미 다뤄진다:

```python
NetworkError.__subclasses__() == [BadRequest, TimedOut]
```

따라서 판별식은 **정확한 타입 비교**다:

```python
# isinstance는 쓸 수 없다 — BadRequest와 TimedOut이 NetworkError의 하위라
# 각각의 기존 처리(평문 폴백 / 재시도 안 함)를 삼켜버린다.
is_connect_failure = type(error) is NetworkError
```

`is_connect_failure`이면 **최대 2회, 2초 간격**으로 같은 청크를 재발송한다
(`_send_chunks(start_index=sent_index)` 재사용 — 이미 성공한 청크는 다시 보내지
않는다). 실패하면 기존과 동일하게 `False`.

`TimedOut`은 그대로 재시도하지 않는다 — 전송 여부가 정말로 불확실하다.

## 8. 테스트

전부 TDD. RED가 **올바른 이유로** 실패하는지 확인한 뒤 구현한다.

| 대상 | 테스트 |
|---|---|
| `collect.py` | 각 수집기: 정상 / 데이터 없음 / 예외 → 부분 결과 반환 |
| `render.py` | 데이터 → HTML 문자열: 필수 값 포함, 반대표 배지, 뉴스 0건 |
| `_position.html` | 만장일치 vs 이견 / 토론 없음 / PER 없음 |
| `send_document` | 게이트 off → 미발송 · 봇 미초기화 → `False` · 성공 → `True` |
| `_send_message` | `type(e) is NetworkError` → 재시도 · `TimedOut` → 재시도 없음 · `BadRequest` → 평문 폴백(회귀) |
| 배선 3곳 | 리포트 예외가 **호출자에게 전파되지 않는다** · 텍스트는 그래도 발송된다 |
| 보존 | 15일 전 파일 삭제, 14일 이내 유지 |

⚠️ **전체 스위트는 워크트리에서 돌린다** — 백엔드 테스트는 opt-in 격리가 없으면
라이브 `storage.db`에 쓴다(2026-08-11에 이것으로 자율 토론 엔진이 3거래일 꺼졌다).
`conftest.py`의 라이브 DB 가드와 엔드포인트 가드(`api.telegram.org` 차단)가
2026-08-12에 들어갔지만, **가드는 규칙을 대체하지 않는다.**

## 9. 범위 밖

- **PNG·PDF** — iPhone에서 HTML이 열리는 것을 확인했으므로 불필요
- **링크·공개 URL** — 백엔드는 localhost 전용이고, 노출은 별도 보안 결정
- **텍스트 메시지 축약** — 리포트 안정화 후 별건
- **인터랙티브 차트** — 정적 인포그래픽으로 충분. JS를 넣으면 파일이 커지고
  Telegram 인앱 뷰어에서 동작이 불확실하다
- **`agent_chat_transcripts` 전문** — 메시지 390건은 리포트가 아니라 로그다

## 10. 미확인 — 구현 중 확인할 것

1. **`NewsService` 쿼터** — 보유 5종 × 하루 2회(개장전·개장후) = 10회.
   `get_quota_status()`로 여유를 확인하고, 부족하면 캐시 TTL을 늘린다.
2. **Telegram 첨부 크기** — 봇 한도는 50 MB이고 샘플이 11 KB라 여유는 크지만,
   보유 종목이 늘고 뉴스가 붙으면 실측할 것.
3. **`behavioral_signals` 키 안정성** — 오늘 관측된 키는
   `volume_ratio · trend · cross · rsi` 넷이다. 다른 키가 오면 표시만 건너뛴다.

## 11. 참조

- 승격 게이트 재료 주입: `2026-08-12-discovery-promotion-evidence-design.md`
- 관측 런북: `docs/runbooks/2026-08-12-morning-observation.md`
- 샘플 실증: 2026-08-13 14:00 iPhone 발송 (`.html` 11 KB 확인)
