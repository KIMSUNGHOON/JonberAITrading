# 토스증권 Open API — 조사 및 연동 분석

> 조사: 2026-08-12. 출처: `https://developers.tossinvest.com/docs`
> 원문 3종 — [overview.md](https://openapi.tossinvest.com/openapi-docs/overview.md) ·
> [api-reference/README.md](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md) ·
> [openapi.json](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)
>
> ⚠️ `/docs`는 JS로 렌더링되는 SPA라 fetch로는 "불러오고 있어요"만 나온다.
> **`/llms.txt`가 AI 에이전트용 진입점**이고, 거기서 위 3개 URL로 간다.

---

## 0. 요약 — 이 API가 우리에게 무엇인가

**한 줄**: 시세·수급·시장정보는 토스가 Kiwoom보다 **넓고 10배 빠르다**. 펀더멘탈(PER/PBR)은 **없다**.

| 우리 문제 (2026-08-12 기준) | 토스로 해결되나 |
|---|---|
| `index_daily`가 yfinance라 **상시 1거래일 지연** | ✅ `market-indicators/KOSPI/candles` — 지수를 직접 준다 |
| KRX 달력 API 죽어 `source=fallback_table` 상시 | 🟡 부분 — `market-calendar/KR`은 **3영업일치만**. 연간 표 대체 불가, **일일 대조 검증용**으로는 유효 |
| Kiwoom 레이트리밋 **~1.4 req/s** 병목 | ✅ MARKET_DATA **15/s**, CHART **20/s**, 수급 **10/s** |
| `flow` 팩터가 얕음(수급 랭킹 결측 잦음) | ✅ `investor-trading` — 개인·외국인·기관(7분류)·기타법인 + 외국인보유율 + CFD |
| 승격 게이트에 **리스크 필터 없음** | ✅ `warnings` — 투자경고·투자위험·단기과열·정리매매·VI |
| 발굴 유니버스를 Kiwoom으로 2,653종 훑음 | 🟡 `rankings`로 좁힐 수 있으나 스펙 미확인 |
| 승격 게이트에 **펀더멘탈 없음** | ❌ **토스에 PER/PBR/EPS가 없다.** Kiwoom `ka10001` 유지 |
| 뉴스·호재 | ❌ 없음. `services/news`(naver) 유지 |

---

## 1. 인증

**OAuth 2.0 Client Credentials.** Base URL `https://openapi.tossinvest.com`

1. WTS 로그인 → 설정 > Open API에서 `client_id` / `client_secret` 발급
2. **같은 화면에서 허용 IP 등록** — 미등록 IP는 `403`으로 차단된다
3. `POST /oauth2/token` (`Content-Type: application/x-www-form-urlencoded`, `grant_type=client_credentials`)
4. 이후 모든 요청에 `Authorization: Bearer {access_token}`

```bash
curl -s -X POST 'https://openapi.tossinvest.com/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials' -d 'client_id=xxx' -d 'client_secret=yyy'
```

🔴 **계좌·자산·주문·조건주문은 헤더가 하나 더 필요하다**: `X-Tossinvest-Account: {accountSeq}`
없으면 `400 account-header-required`.

⚠️ **IP 화이트리스트가 운영상 함정이다.** 이 시스템은 집 맥에서 돌고 공인 IP가 바뀔 수 있다.
IP가 바뀌면 전 API가 403이 되는데, 우리 코드의 넓은 `except`가 이것을 "데이터 없음"으로
삼킬 위험이 있다 — 배선할 때 403을 **명시적으로 구별**해 로그·Telegram에 올려야 한다.
(2026-08-07에 "데이터 실패가 노출도 상한을 두 배로 열었다"와 같은 계열의 위험이다.)

---

## 2. 레이트리밋 — Kiwoom 대비 결정적 우위

클라이언트 × API 그룹 단위. **응답 헤더로 잔량을 준다** (`X-RateLimit-Limit` / `-Remaining` / `-Reset`, 429엔 `Retry-After`).

| 그룹 | 한도 | 우리 용도 |
|---|---|---|
| `MARKET_DATA_CHART` | **20/s** | 캔들 — 발굴 스캔 |
| `MARKET_DATA` | **15/s** | 현재가·호가·체결 |
| `STOCK_TRADING_TREND` | **10/s** | 투자자별 매매동향(flow) |
| `MARKET_INDICATOR_PRICE` | 10/s | KOSPI/KOSDAQ 현재가 |
| `MARKET_INDICATOR` | 10/s | 지수 투자자별 매매대금 |
| `ORDER` | 10/s (09:00~09:10도 10/s) | |
| `ORDER_INFO` | 6/s (**09:00~09:10엔 3/s로 감소**) | 매수가능금액 등 |
| `RANKING` · `STOCK` · `ASSET` · `MARKET_INDICATOR_CHART` | 5/s | |
| `MARKET_INFO` | 3/s | 달력·환율 |
| `ACCOUNT` · `STOCK_ALL` | **1/s** | 계좌목록·전종목 |

**대조**: Kiwoom은 실측 **~1.4 req/s**이고, 2026-08-12에 0.85초 간격으로 22종을 조회하다
`ka10001 return_code=5 (유량 초과)`를 실제로 맞았다. 토스 `MARKET_DATA`는 **10배 이상** 여유가 있다.

⚠️ `ORDER_INFO`가 개장 10분간 절반(6→3/s)으로 **줄어드는** 유일한 그룹이다. 개장 직후
매수가능금액을 반복 조회하는 경로가 있으면 그때 걸린다.

---

## 3. 엔드포인트 전수

### 시세 (Market Data)
| 엔드포인트 | 용도 |
|---|---|
| `GET /api/v1/prices` | 현재가 |
| `GET /api/v1/candles` | 캔들 — `interval` **`1m`\|`1d`**, `count` 기본 100 / **최대 200**, `before`(ISO8601), `adjusted` 기본 **true** |
| `GET /api/v1/orderbook` | 호가 |
| `GET /api/v1/trades` | 최근 체결 |
| `GET /api/v1/price-limits` | 상·하한가 |

캔들 응답: `timestamp` / `openPrice` / `highPrice` / `lowPrice` / `closePrice` / `volume` / `currency` + `nextBefore`(페이지네이션)

### 종목 정보 (Stock Info)
| 엔드포인트 | 용도 |
|---|---|
| `GET /api/v1/stocks` | 기본 정보 |
| `GET /api/v1/stocks/all` | 마켓별 전종목 (`STOCK_ALL` 1/s) |
| `GET /api/v1/stocks/{symbol}/warnings` | **매수 유의사항** |
| `GET /api/v1/stocks/{symbol}/investor-trading` | **투자자별 매매동향** |
| `GET /api/v1/stocks/{symbol}/program-trades` | 프로그램매매 |
| `GET /api/v1/stocks/{symbol}/short-selling` | 공매도 |
| `GET /api/v1/stocks/{symbol}/credit-trades` | 신용거래 |
| `GET /api/v1/stocks/{symbol}/securities-lending` | 대차거래 |

🔴 **`/stocks` 응답에 PER·PBR·EPS·시가총액이 없다.** 있는 것은
`symbol` `name` `englishName` `isinCode` `market` `securityType` `isCommonShare` `status`
`currency` `listDate` `delistDate` `sharesOutstanding` `leverageFactor`
`koreanMarketDetail{liquidationTrading, nxtSupported, krxTradingSuspended, nxtTradingSuspended}`.

→ **시가총액은 `sharesOutstanding × 현재가`로 계산 가능**하지만 PER/PBR/EPS는 만들 수 없다.
펀더멘탈은 Kiwoom `ka10001`(`per`/`pbr`/`eps`/`bps`/`mrkt_tot_amt`)을 계속 써야 한다.

### 시장 지표 (Market Indicators)
| 엔드포인트 | 용도 |
|---|---|
| `GET /api/v1/market-indicators/prices` | 지표 현재가 |
| `GET /api/v1/market-indicators/{symbol}/candles` | **지표 캔들** |
| `GET /api/v1/market-indicators/{symbol}/investor-trading` | 지표 투자자별 매매대금 |

지원 심볼 **8개**: `KOSPI` `KOSDAQ` `KR_BOND_2Y` `KR_BOND_3Y` `KR_BOND_5Y` `KR_BOND_10Y` `KR_BOND_20Y` `KR_BOND_30Y`
분봉(`1m`)은 **지수만**, 국채는 일봉(`1d`)만.

### 시장 정보 (Market Info)
| 엔드포인트 | 용도 |
|---|---|
| `GET /api/v1/market-calendar/KR` | 국내 장 운영 |
| `GET /api/v1/market-calendar/US` | 해외 장 운영 |
| `GET /api/v1/exchange-rate` | KRW↔USD |

달력 응답 = `today` / `previousBusinessDay` / `nextBusinessDay` **3영업일치뿐**.
각각 `{date, integrated}`이고 `integrated`는 `preMarket`·`regularMarket`·`afterMarket`의
`startTime`/`singlePriceAuctionStartTime`/`endTime`을 담는다.
🔴 **휴장일이면 `integrated`가 `null`** — 이것이 휴장 판정 신호다.

### 계좌·주문
`GET /api/v1/accounts` · `GET /api/v1/holdings` ·
`POST /api/v1/orders` · `POST /api/v1/orders/{id}/modify` · `POST /api/v1/orders/{id}/cancel` ·
`GET /api/v1/orders` · `GET /api/v1/orders/{id}` ·
`GET /api/v1/buying-power` · `GET /api/v1/sellable-quantity` · `GET /api/v1/commissions`

**조건주문** (`SINGLE`·**`OCO`**·**`OTO`**): `POST /api/v1/conditional-orders` (+ modify / DELETE / 목록 / 상세)

⭐ **OCO(One-Cancels-Other)가 있다.** 지금 우리 손절·익절은 **프로세스 안에만** 존재해서
"장중 재시작 금지"라는 운영 제약을 만들고, 프로세스가 죽으면 무방비가 된다.
OCO를 브로커에 걸어두면 그 위험이 구조적으로 사라진다 — **이 API에서 가장 값어치 있는 발견일 수 있다.**
(단, 실제 주문 경로를 토스로 옮기는 것은 별개의 큰 결정이다.)

### 랭킹
`GET /api/v1/rankings` — "거래대금·거래량 상위, 급상승·급하락, 토스 체결 기준 상위".
⚠️ **파라미터·응답·열거값이 문서에 없다.** 실제 호출로 확인해야 한다.

---

## 4. 에러 모델

```json
{"error": {"requestId": "...", "code": "invalid-request", "message": "...", "data": {}}}
```

우리가 반드시 구별해야 할 코드:

| HTTP | code | 의미 / 대응 |
|---|---|---|
| 401 | `expired-token` | 토큰 갱신 후 재시도 |
| 401/403/404 | **`edge-blocked`** | **IP 화이트리스트 문제** — 조용히 삼키면 안 된다 |
| 400 | `account-header-required` | `X-Tossinvest-Account` 누락 |
| 429 | `rate-limit-exceeded` / `edge-rate-limit-exceeded` | `Retry-After` 준수 |
| 409 | `already-filled` / `already-canceled` / `already-modified` | **방어 매도 재제출 억제와 같은 계열** — 이미 처리된 주문 |
| 422 | `insufficient-buying-power` · `order-hours-closed` · `stock-restricted` · `price-out-of-range` · **`opposite-pending-order-exists`** | 주문 거부 사유 |
| 500 | `internal-error` / `maintenance` | |

⭐ `409 already-*`와 `422 opposite-pending-order-exists`는 우리가 Kiwoom `800033`
(매도가능수량 부족)으로 겪은 문제와 **같은 성질**이다. 토스는 이것을 **구조화된 코드**로 준다 —
문자열 매칭 대신 코드로 분기할 수 있다.

---

## 5. 우리 시스템에 붙이는 방법 — 우선순위

### 🔴 P1. `index_daily`를 토스 지수로 교체 (효과 확실·범위 작음)

**현 상태**: `services/trading/index_series.py`가 yfinance `^KS11`을 쓴다. 08:05 수집 시점에
Yahoo가 전일 종가를 아직 안 내놔 **상시 1거래일 지연**이고, 그 때문에
`index_series_lagging`이 매일 뜬다. 2026-08-12에 09:30 재수집(`259ab7a`)을 붙여 완화했지만
**원인은 데이터 소스**다.

**교체안**:
```
GET /api/v1/market-indicators/KOSPI/candles?interval=1d&count=200
```
- 40일 창(`INDEX_LOOKBACK_DAYS=40`)에 200개 상한은 충분
- `MARKET_INDICATOR_CHART` 5/s — 하루 1회 호출이라 무관
- 응답 `closePrice`를 그대로 `index_daily.close`에 upsert, `source`를 `toss:KOSPI`로

⚠️ **주의 2가지**
1. `adjusted` 기본 `true`(수정주가). yfinance 값과 미세하게 다를 수 있다 —
   교체 시 **과거 40일을 한 번에 다시 받아** 소스를 섞지 말 것.
2. 당일 진행 봉이 섞여 오는지 확인해야 한다. 우리는 `259ab7a`로 **오늘 날짜 행 제외**
   가드를 이미 넣어뒀으니 그대로 유효하다.

**검증**: 교체 후 며칠간 yfinance와 **행 단위 대조**. 2026-08-07에 "내 지식과 다르다"를
데이터 오류로 오판한 전례가 있으므로, 값이 다르면 어느 쪽이 맞는지 먼저 확인한다.

### 🔴 P2. 승격 게이트에 `warnings` 추가 (오늘 설계 중인 작업에 직결)

2026-08-12 리서치에서 확인한 것: 발굴 LLM은 종목명 + 지표 4개만 보고 판단한다.
그런데 **투자경고·투자위험·단기과열·정리매매**는 밸류에이션 논쟁 없이 명확한 위험 신호다.

```
GET /api/v1/stocks/{symbol}/warnings
→ warningType ∈ {LIQUIDATION_TRADING, OVERHEATED, INVESTMENT_WARNING,
                 INVESTMENT_RISK, VI_STATIC, VI_DYNAMIC, VI_STATIC_AND_DYNAMIC,
                 STOCK_WARRANTS}
```

- 상위 25종만 조회 → `STOCK` 5/s로 5초면 끝난다
- `LIQUIDATION_TRADING`(정리매매) / `INVESTMENT_RISK`(투자위험)는 **하드 차단**이 정당하다.
  PER 필터와 달리 "강세장이면 무시하고 급등한다"는 반론이 성립하지 않는다
- 나머지는 LLM 프롬프트에 실어 판단 재료로

### 🟡 P3. `flow` 팩터를 `investor-trading`으로 강화

현재 `flow`는 수급 랭킹 기반이고 결측이 잦아 `_effective_weights`가 재정규화한다
(2026-07-28에 그 재정규화가 소형주 momentum을 33% 증폭시키던 것을 제거한 이력이 있다).

```
GET /api/v1/stocks/{symbol}/investor-trading?count=10
→ records[]: date, individual/foreigner/institution{buyVolume, sellVolume, netBuyVolume},
             institution.breakdown(7분류), otherCorporation,
             foreignerHolding{holdingQuantity, limitQuantity, holdingRate},
             cfd{buyBalanceQuantity, buyBalanceRate, ...}
```

`count` 최대 100일, `STOCK_TRADING_TREND` **10/s**. 상위 25종이면 2.5초.
**외국인 보유율 추이**와 **기관 7분류**는 지금 없는 신호다.

### 🟡 P4. 달력 일일 대조 (근본 해결은 아님)

`market-calendar/KR`은 3영업일치라 우리 연간 `krx_holidays` 표를 대체할 수 없다.
그러나 **매일 아침 오늘/다음영업일을 대조**하면, `fallback_table`이 틀렸을 때
그날 안에 알 수 있다 — 지금은 틀려도 알 방법이 없다(백로그 "market_hours 경로가 관측 밖").

`integrated is null` → 휴장. 우리 `is_trading_day()`와 다르면 경보.

### ⭐ P5. (큰 결정) OCO 조건주문으로 손절을 브로커에 위탁

지금 손절·익절은 이 프로세스에만 있다. 그래서 "장중 재시작 금지"가 운영 원칙이고,
프로세스가 죽으면 포지션이 무방비다. 토스 `POST /api/v1/conditional-orders`의 **OCO**는
손절·익절을 한 쌍으로 브로커에 걸어둔다.

**이것은 API 추가가 아니라 아키텍처 변경**이다 — 주문 경로가 Kiwoom과 토스로 갈라지거나,
전체를 토스로 옮기는 결정이 필요하다. 별도 설계 대상으로만 기록한다.

---

## 6. 붙일 수 없는 것

| | 이유 | 대안 |
|---|---|---|
| PER · PBR · EPS | `/stocks` 응답에 없음 | Kiwoom `ka10001` 유지 |
| 뉴스 · 공시 | API 없음 | `services/news`(naver) 유지 |
| 연간 휴장일 표 | 3영업일치만 | `krx_holidays` 유지 + 일일 대조 |
| 재무제표 | 없음 | OpenDART (미구현) |

---

## 7. 배선 전 확인할 것

1. **`rankings` 실호출** — 스펙이 문서에 없다. 파라미터·응답·열거값을 실제로 찍어봐야 한다.
2. **IP 화이트리스트** — 현재 공인 IP 등록. 변경 시 전 API 403. `edge-blocked`를 조용히
   삼키지 않는 배선이 선결 조건이다.
3. **토큰 수명** — `overview.md`에 만료 시간이 명시되지 않았다. 실측하거나 401
   `expired-token`에서 자동 갱신하는 구조로.
4. **모의투자 여부** — 토스 Open API에 모의 환경이 있는지 문서에 없다. `KIWOOM_IS_MOCK=true`로
   주문만 모의로 돌리는 현재 구조와 어떻게 공존할지 확인이 필요하다. **주문 경로를 붙이기
   전에 반드시 확인할 것** — 실계좌에 바로 나가면 돌이킬 수 없다.
5. **`sharesOutstanding` 기반 시총** — Kiwoom `mrkt_tot_amt`와 대조해 단위(원/억원)를 확인.
   2026-07-18에 "시총 단위 버그"를 겪은 전례가 있다.

---

## 8. 권장 순서

```
1) 인증 + 레이트리밋 클라이언트 (services/toss/) — 403/429/토큰갱신을 명시적으로 구별
2) P1 index_daily 교체        — 효과 확실, 범위 작음, yfinance와 대조 검증
3) P2 warnings 승격 게이트     — 오늘 설계 중인 작업에 바로 얹힘
4) P3 investor-trading flow    — 팩터 재설계가 필요해 범위가 크다
5) P4 달력 일일 대조
— 이후 —
6) rankings 실호출 조사 → 발굴 유니버스 축소 검토
7) OCO 위탁 (별도 설계)
```
