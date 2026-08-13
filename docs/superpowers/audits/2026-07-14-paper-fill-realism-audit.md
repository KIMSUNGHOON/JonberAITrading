# 페이퍼 체결 사실성 실사 (2026-07-14, P2-4)

> 4-에이전트 READ-ONLY 실사 + 종합. HEAD 기준. 설계 제안(승인 전 구현 금지).

종합 완료. 4개 실사 결과를 검증·교차확인했고, 특히 설계에 결정적인 비대칭성(KR 헤드라인 수익률은 모의 브로커 자체 원장에서 나오지만 coin은 앱이 곧 원장)을 코드로 확인했다. 아래가 산출물이다.

---

# 페이퍼 체결 사실성 실사 종합 + 개선 설계 (P2-4)

## A. 체결 낙관 가정 지도

| 항목 | KR (Kiwoom 모의) | coin (Upbit paper) | 낙관판정 | 수익률 왜곡 방향 · 근거 |
|---|---|---|---|---|
| **체결 트리거** | 접수≠체결을 분리. `confirm_kiwoom_fill`이 실제 ka10076을 3회×0.5s 폴링, `ccld_qty>0` 행만 합산. 조회실패=0체결(허수 방지) | 브로커 콜 자체가 없음. `_execute_paper_order`가 `state:"done"` 리터럴로 즉석 생성. live도 접수응답 1회만 읽고 `wait`(미체결)까지 체결로 오판 | KR=**REALISTIC** / coin=**OPTIMISTIC** | coin은 "낼 수 없거나 안 잡힐 주문"이 100% 성사로 기록 → 성사율·참여율 과대. `fill_confirm.py:33-61`, `coin_nodes.py:702-738`, live 오판 `coin_nodes.py:867` |
| **체결가** | `avg_price=Σ(ccld_qty·ccld_uv)/filled_qty` = 브로커 보고 실체결단가. 요청가 대입 아님 | 데이터수집 시점 stale `ticker.trade_price`를 승인 지연(분~시간) 뒤 재조회 없이 그대로 체결가로 사용(`entry_price=float(current_price)`) | KR=**REALISTIC** / coin=**OPTIMISTIC** | coin은 승인지연 중 가격변동·스프레드가 통째로 소멸(반사실적 "분석시점가에 체결"). `fill_confirm.py:51-54` vs `coin_nodes.py:539-556,731` |
| **슬리피지** | `get_price_with_slippage()` 정의·export만, 프로덕션 호출자 0건(dead code). 손절/익절이 트리거가 그대로 LIMIT으로 발주 | 개념 자체 부재 | 둘 다 **OPTIMISTIC** | 진입·특히 방어적 청산가가 실제보다 유리. 모의서버가 순순히 채울수록 손실국면 리스크 과소. `market_hours.py:470-498`(호출자 0건 grep 확인), `risk_monitor.py:500-556`, `models.py:274`(기본 LIMIT) |
| **수수료·세금** | 헤드라인 실현: ka10074 `trde_cmsn/trde_tax` 반영, `net_pnl=realized-cmsn-tax`. **단** 실시간 미실현·포지션원가·손절트리거는 raw가(무비용) | 전 구간 `fee:0` 하드코딩. `calculate_position_pnl`도 순수 가격차, 저장된 live fee조차 소비 안 됨 | KR=**PARTIAL** / coin=**OPTIMISTIC** | coin 왕복 ~0.1%p 상시 과대. KR 실시간 지표는 청산비용(왕복 수수료+매도 거래세 ~0.2%대)만큼 상시 낙관. `paper_performance.py:152-154` vs `models.py:328-329`, `coin_nodes.py:734`, `coin/helpers.py:139-142` |
| **부분체결** | R5-P1로 실측. `_apply_sell_fill` 전량/부분/미체결 3분기, `PendingOrderTracker`가 누적 스냅샷 diff(이중계산 방지) | paper=무조건 전량. live=미체결(0)을 요청수량으로 폴백 대입 | KR=**REALISTIC** / coin=**OPTIMISTIC** | coin은 부분·미체결 위험 소멸. `coordinator.py:925-987` vs `coin_nodes.py:733,867` |
| **큐 위치** | 시간우선·호가잔량 모델 없음(모의서버 매칭엔진에 위임, 저장소 밖) | 동일하게 없음 | 둘 다 **UNKNOWN(범위 밖)** | 앱 코드 감사로 검증 불가. `coordinator` trade_queue는 제출순서일 뿐 거래소 큐 아님 |

---

## B. 수익률 담보에 대한 실제 영향

**핵심 비대칭(설계의 출발점).** KR 헤드라인 누적수익률은 앱 포지션 계산이 아니라 **모의 브로커 자체 원장**에서 나온다 — 계좌평가액 `current_asset`(kt00004)과 실현손익 `net_pnl`(ka10074, 수수료·세금 이미 차감). 따라서 이 한 숫자는 앱의 무비용·무슬리피지 가정을 상속하지 않는다. 반면 **coin paper는 브로커 원장이 존재하지 않아 앱이 곧 원장**이다. 그래서 낙관의 무게중심이 완전히 다르다.

**가장 큰 왜곡원 (2개).**

1. **coin paper 전면 낙관 + 데이터 오염(치명).** fee=0 · stale 진입가 · 100% 전량체결이 겹쳐 coin "수익"은 구조적으로 부풀려진다. 더 심각한 건 낙관을 넘어선 **장부 붕괴 2건**: (a) 자율 SELL 경로가 `if side=="bid":`에 갇혀 `save_coin_position`을 SELL에서 호출하지 않음 → 이미 판 포지션을 옛 평단으로 무한정 "보유 중"으로 잡아 미실현손익을 계속 더함(`coin_nodes.py:741-750`); (b) `save_coin_position`이 `INSERT OR REPLACE`라 반복매수 시 가중평균이 아니라 마지막 매수가·수량으로 통째 덮어씀(`storage_service.py:692-739`). 여기에 coin 실현손익 집계 자체가 없다(paper_performance는 KR 전용). 즉 **coin 수치는 부풀림 이전에 신뢰 불가**.

2. **KR 실시간 지표·방어매도의 무비용/무슬리피지.** 헤드라인 실현수익률은 브로커-진실이지만, 사용자가 보유 중 보는 실시간 미실현 P&L과 손절/익절 트리거 판단은 왕복비용(수수료+매도 거래세 ~0.2%대)을 뺀 순손익보다 항상 낙관적이다. 박한 마진의 단기매매에서는 이 괴리가 승패 판정을 뒤집을 수 있다. 또 손절이 트리거 가격 그대로 LIMIT으로 나가 모의서버가 그 가격에 채워주면 실제 급락 라이브보다 유리한 손절가가 기록돼 손실국면 리스크가 과소평가된다.

**요약.** "요청가에 완전체결"이라는 최악의 가정은 KR에서 R5-P1이 이미 제거했다. 남은 낙관은 (i) coin 전면 시뮬레이션의 비현실성+장부오염, (ii) 슬리피지 완전 부재, (iii) 실시간 지표의 비용 무시다.

---

## C. 개선 설계 (사실성 반영)

### 설계 원칙 — 어디에 넣고 어디에 안 넣나
- **KR은 합성 시뮬레이션 금지.** 브로커(모의/라이브) 응답이 진실이고 헤드라인 원장(kt00004/ka10074)의 소스다. 앱이 avg_price에 슬리피지·수수료를 덧대면 브로커 원장과 **desync**되고 R5-P1 회귀 위험이 생긴다. KR 개선은 두 곳으로 제한한다: (1) **표시/결정 레이어**(실시간 미실현·트리거 비교에만 순비용 보정), (2) **주문 구성**(방어매도 order_type 변경 — 원장은 여전히 브로커가 보고).
- **coin paper만 시뮬레이션.** paper/live가 이미 `_execute_paper_order` vs `_execute_live_order`로 함수 분리돼 있으므로, 시뮬레이션 전부를 paper 함수 안에만 넣으면 **live는 실 Upbit 체결을 그대로 써서 이중계산이 원천 차단**된다.

### 우선순위 1 — 수수료·세금 (가장 결정적, 구현 단순)
- **coin paper (`coin_nodes.py:_execute_paper_order`)**: `fee = entry_price*quantity*coin_fee_bps`를 계산해 `total_krw`·`avg_entry_price`에 반영(매수는 원가 가산). SELL 청산 실현손익에서 `entry_fee+exit_fee` 차감. 신규 **coin 실현손익 집계**(청산 시 realized row 적재)를 최소 형태로 추가 — 현재 전무하므로.
- **KR**: 헤드라인은 이미 반영돼 있으니 원장은 손대지 않는다. 대신 **display-layer helper**(신규 `effective_pnl(avg_price, current_price, qty, side)`)를 만들어 실시간 미실현 P&L 표시와 손절/익절 트리거 비교에만 왕복 순비용을 반영. `ManagedPosition.unrealized_pnl`·`fill_confirm`·`coordinator`의 원가 계산은 **그대로 둔다**(R5-P1 정합).

### 우선순위 2 — 슬리피지
- **coin paper only**: 진입가를 실행 시점에 **재조회**(stale 제거) 후 side별 adverse 조정(buy +bps, sell −bps). `get_price_with_slippage`의 로직을 coin용으로 재사용/이식.
- **KR**: app-side 합성 슬리피지는 금지(원장 desync). 대신 **방어매도(stop_loss/take_profit) order_type을 MARKET(또는 슬리피지-버퍼 aggressive LIMIT)으로** 전환(`risk_monitor.py:500-556`). 그러면 모의 브로커가 실제 불리가에 체결→ka10076이 그 실체결가를 보고→원장과 자동 정합. 이건 시뮬레이션이 아니라 주문구성 교정이라 라이브에서도 올바른 동작이다.

### 우선순위 3 — 부분체결 / 큐 위치 (가장 복잡)
- **KR**: R5-P1이 이미 실측·처리. 확장 불필요.
- **coin 최소**: live-mode `executed_volume` 오독 버그 수정(미체결 0을 요청수량으로 폴백하는 `coin_nodes.py:867`). paper는 전량체결 유지(또는 후속으로 fill-probability 도입).
- 거래소 큐 위치 시뮬은 최대안에서만.

### 설정화
`app/config.py`에 fee/slippage 설정이 전무(grep 0건)하므로 **신규 `PaperFillSettings`**: `kr_commission_bps`, `kr_sell_tax_bps`, `coin_fee_bps`, `slippage_bps`(마켓/사이드별). env 또는 app_settings 관리, 기본값은 보수적(실제 이상). 정확한 KRX 거래세율은 연도별로 변하므로 코드에 상수 박지 말고 설정으로 뺀다.

### 대안 3안 · 트레이드오프

| 안 | 범위 | 장점 | 한계 |
|---|---|---|---|
| **최소** | coin paper 수수료 + KR 실시간 표시 순비용 보정 | 노력 최소, 헤드라인 왜곡 즉시 완화 | coin 장부오염·방어매도 realism 미해결 |
| **중간(추천)** | 최소 + coin paper adverse 슬리피지·진입 재조회 + KR 방어매도 MARKET화 + coin live executed_volume 버그 수정 | 무비용·무슬리피지·미체결오판을 모두 봉합, 이중계산 원천차단 | coin 큐/부분체결 정밀 시뮬은 미포함 |
| **최대** | 중간 + coin 부분체결/큐 확률모델 + coin 실현손익 완전 집계 | 완결적 | 복잡·검증부담 큼, C2 일정 지연 |

**추천 = 중간안. 단, 전제조건으로 coin 장부오염 2건 수정(SELL 미갱신 + INSERT OR REPLACE 가중평균)과 coin 실현손익 최소 집계를 선행한다.** 이유: 이 두 버그는 낙관이 아니라 "수치 신뢰 불가"라, 어떤 수수료·슬리피지 정확도보다 우선한다. 오염된 장부 위에 정밀 fee를 얹는 건 무의미하다.

### R5-P1과의 정합
새 로직은 (a) `_execute_paper_order`(coin), (b) 신규 display-layer cost helper(KR 표시·트리거 전용), (c) 방어매도 order_type 스위치(risk_monitor), (d) 신규 config에만 한정된다. `confirm_kiwoom_fill`/`_apply_sell_fill`/`ka10076`/`PendingOrderTracker` 등 R5-P1 실측 경로는 **읽지도 고치지도 않는다** → 중복·충돌 없음.

---

## D. 리스크 · 검증

**건드리는 핵심 파일**: `agents/graph/coin_nodes.py`(paper 함수), `services/storage_service.py`(save_coin_position 가중평균 + SELL 삭제경로), `app/api/routes/coin/{positions.py,helpers.py}`, `app/config.py`(신규 설정), `services/trading/risk_monitor.py`(방어매도 order_type), 신규 KR cost helper. **KR 원장 계산 경로(`fill_confirm.py`, `coordinator.py`의 avg_price/_apply_sell_fill, `paper_performance.py`)는 불변** — R5-P1 회귀 위험을 구조적으로 회피.

**회귀 위험**:
- coin 변경은 KR 테스트에 무영향(경로 분리).
- KR 방어매도 order_type 변경은 `coordinator`/`risk_monitor` 테스트의 어댑터 호출 인자 기대치 갱신 필요.
- display-layer helper는 원장을 바꾸지 않으므로 실현손익·avg_entry 테스트 불변.

**검증 방법**:
1. coin: fee 적용 전후 실현손익 단위테스트(왕복 fee만큼 감소 확인).
2. coin: slippage 적용 시 `buy_fill>mid`·`sell_fill<mid` 단위테스트.
3. coin: 자율 SELL 후 `GET /positions`에서 해당 포지션 제거 확인(오염 회귀 방지 — 현재 실패해야 정상).
4. KR: 방어매도가 MARKET 인자로 어댑터에 도달하는지 호출 인자 검증.
5. **KR rlzt_pl gross/net 이중차감 검증**: 실사에서 미해결로 남은 항목 — `net_pnl=realized-cmsn-tax`가 이중차감인지 실제 모의서버 응답 1건으로 확인. **자기목 픽스처 금지**(Paper-Proof Phase A 사고의 근본원인). 이건 낙관과 반대 방향(과소평가) 오류라 방향이 반대지만 "수익률 신뢰"에는 똑같이 치명적.

**C2 자율 실증 진입 게이트 (최소선)**: "수익률 신뢰"가 서려면 최소 (1) coin SELL 장부오염 수정(안 하면 미실현 P&L이 무한 오염되어 어떤 수치도 못 믿음), (2) coin paper 수수료 반영, (3) KR rlzt_pl net/gross 실응답 검증 — 이 셋이 선행돼야 한다. 슬리피지·부분체결은 그다음 단계로 나눠도 신뢰가 무너지지 않는다. 즉 **최소안 + coin 장부버그 수정이 C2 진입 게이트**, 중간안은 C2 병행/직후 목표로 권고.

---

*본 문서는 설계 제안이며, 승인 전 구현 금지. C의 세 우선순위는 각각 독립 실행 단위로 착수 가능하되, coin 장부오염 수정은 우선순위 1과 묶어 선행할 것을 권고한다.*