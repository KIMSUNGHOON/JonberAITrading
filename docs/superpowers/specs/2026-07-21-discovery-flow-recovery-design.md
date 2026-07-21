# 발굴 flow 데이터 복구 (Discovery Flow Recovery) — 설계

**작성일**: 2026-07-21
**아크**: 발굴 승격 0 근본 수정 (#1 LLM 프롬프트 flow-missing 명시 + #2 ka10131 파싱 크래시 근본수정 + #3 regime_snapshot 개장 전 폴백)
**선행**: [[session-2026-07-21-discovery-manual-trigger]] — POST /trading/discovery/run 배포 후 라이브 발굴이 2622후보 정상완주했으나 **승격 0**. 3각도 적대적 workflow + 독립 재현으로 근본원인 확정.

---

## 1. 문제 (확정된 근본원인)

2026-07-21 개장 전 수동 발굴(2651종목, scan_ok=True, 2622후보)이 **승격 0**. 원장·로그·코드·raw API 캡처로 교차 확정한 인과 사슬:

1. **ka10131 파싱 크래시**: `services/kiwoom/client.py::_parse_float`(473-482)는 `+`·`,`만 strip한 뒤 `float(value)`를 호출한다. 그러나 Kiwoom ka10131(기관/외국인 연속매매)은 음수를 **이중부호** `--35`/`--3206`로 반환한다 → `float('--35')` **ValueError 크래시**.
2. **시장 전체 폐기**: `get_inst_foreign_flow`(720-748)는 rows 루프 전체를 하나의 try/except로 감싸, **한 행이라도 파싱 실패하면 그 시장 ~100행 전부를 버리고 None 반환**. 2026-07-21 07:34 KOSPI(001)·KOSDAQ(101) 양쪽 모두 이 크래시로 실패(nohup 로그 확증).
3. **flow 전면 0**: `scanner.py::_build_flow_map`(863-895)가 시장당 1콜만 하고 실패를 "flow 성분 0으로 수렴"으로 fail-open → flow_map={} → **1806/1806(100%) 랭크된 후보가 flow=0**(설계 가정 ~200/2622가 아님).
4. **LLM 거부**: `_build_llm_messages`(461-480)는 raw `flow={scores.get("flow",0.0):.3f}`를 LLM에 그대로 노출. LLM은 flow=0.000을 "수급 확인 전무"로 읽어 문턱 통과 3종(동일금속 0.5835·코웨이 0.5647·아이디피 0.5560)을 전부 `llm_not_suitable` 거부 → **승격 0**.

**확정 사실 (raw ka10131 캡처, 2026-07-21 09:08)**:
- `--N` = **-N** (음수). 산술 검증: 005935 `orgn_nettrde_amt=--35` + `frgnr_nettrde_amt=+122068` = `nettrde_amt=+122033` ✓.
- 부호 규약: `+N`=양수, `--N`=음수(이중부호), `-N`=음수(단일, 연속일수 필드), `-1.22`=음수 비율(단일).
- **실 Kiwoom 규약이며 mock 아티팩트 아님**. 만연함: KOSPI 100행 중 204건, KOSDAQ 266건 이중부호 → **매 스캔 100% 크래시**.
- 이 버그는 `get_inst_foreign_flow` 신설(efd94b8, Phase5 T1, 2026-07-16)부터 잠복 → 이후 모든 discovery run의 flow가 전면 0.

**판정**: 승격 0은 올바른 보수성이 아니라 **flow-missing 오독으로 인한 구조적 false-negative**. flow=0.000은 `factors._score_flow` 수식상 flow **결측**에서만 나오는 값(실측이면 presence≥0.333)이므로 "확인된 수급 부재"가 아니라 "데이터 없음"의 지문이다. binding gate는 LLM(4번), root cause는 파싱 크래시(1번). 레짐/문턱은 non-binding(반사실: bearish 0.52로 바꿔도 통과 후보 여전히 소수·전부 flow=0).

---

## 2. 목표

flow 데이터를 근본 복구하고, 복구 후에도 남는 "진짜 미커버" 종목의 flow 결측을 LLM에 정직하게 제시해, **리스크 규율(게이트·문턱·손절)을 훼손하지 않으면서** 발굴 승격이 데이터 아티팩트가 아닌 실제 적합성으로 결정되게 한다. 부수로 개장 전 실행의 레짐 정확성을 개선한다.

**비목표**: ka10131 페이지네이션(커버리지 확대)·LLM 신뢰도 문턱 완화·composite 문턱 조정. (모두 workflow에서 기각 — 오늘 원인은 커버리지·신뢰도·문턱이 아니라 파싱 크래시 + 결측 오독.)

---

## 3. 설계

### #2 — ka10131 파싱 근본 수정 (근원, 우선 구현)

**Fix A — `_parse_float` Kiwoom 부호 정규화** (`services/kiwoom/client.py:473-482`)
- `,` 제거 후 부호 정규화:
  - 선두 `--` → `-` 로 축약 (`--35` → `-35`).
  - 선두 단일 `+` → 제거 (`+122068` → `122068`).
  - 선두 단일 `-` → 유지 (`-2`, `-1.22`).
- 정규화 후 `float()`. 빈 문자열·None → 0.0 (기존 계약 유지).
- 공유 유틸이므로 **모든 음수 값 파싱이 함께 정상화**. 리스크: 다른 콜사이트가 현 크래시 동작에 의존할 리 없음(크래시는 의도된 적 없음). SDD 리뷰가 `_parse_float` 전 콜사이트를 확인해 회귀 없음을 검증.
- 정규화는 `+N`/`--N`/`-N`/`-1.22`/`+2.50`/`123`/`""`/`None`을 모두 올바르게 처리해야 한다.

**Fix B — `get_inst_foreign_flow` 행단위 fault-isolation** (`services/kiwoom/client.py:720-748`)
- rows 루프에서 각 행 파싱을 개별 try/except로 감싸, 한 행 실패 시 **그 행만 skip(warning 로그)하고 나머지 행은 살린다**. Fix A로 이번 크래시는 근본 해소되지만, 향후 다른 예기치 못한 포맷에도 시장 전체가 무너지지 않도록 하는 방어 심화.
- 전량 실패(모든 행 skip) 또는 응답 자체 실패 시에만 None/빈 리스트(기존 "실패-무해" 계약 유지).

**효과**: flow_map이 시장당 최대 100종목(ka10131 상위 랭킹) 실측 복구. 유니버스 전체(~2600)는 아니므로 top-100 밖 종목은 여전히 flow=None → #1이 담당.

### #1 — LLM 프롬프트 flow-missing 명시 (binding gate 해소)

**flow_present를 Candidate까지 스레딩** (`services/discovery/ranker.py`)
- `Candidate` 데이터클래스(108-129)에 `flow_present: bool = False` 필드 추가.
- `rank_candidates`(342-443)에서 이미 읽는 `factor.get('flow_present')`(414-427, 현재는 `_effective_weights`의 composite 재정규화에만 사용)를 Candidate에도 저장.

**`_build_llm_messages` 분기** (`services/discovery/ranker.py:461-480`)
- 현재: `flow={scores.get("flow",0.0):.3f}` (raw 숫자).
- 변경: `flow_present`가 True면 기존대로 `flow={value:.3f}`(실측), False면 **`flow: 수급데이터 미가용(ka10131 랭킹 미포함 — 부정신호로 해석 금지)`** 로 대체.
- **게이트 로직·composite 문턱·LLM JSON 응답 스키마 불변**. 이 수정은 문턱/신뢰도를 낮추지 않는다; LLM에 주는 **허위 음성 입력(결측을 0으로 오독)만 정정**한다. 승격은 여전히 momentum·pullback 등 실측 팩터로 LLM이 suitable=true를 내야 성립.

**주의**: composite 재정규화(DQ-2 `_effective_weights`)는 그대로 둔다 — flow 결측 종목의 composite는 이미 나머지 3팩터로 재정규화됨. #1은 오직 LLM 프롬프트 텍스트만 바꾼다.

### #3 — regime_snapshot 개장 전 폴백 (정확성, non-binding)

**`_get_regime_snapshot_for_date` 완화** (`services/discovery/ranker.py:229-245`)
- 현재: `snap['trade_date'] == trade_date` 완전일치만 채택, 없으면 None → `_extract_regime_label`(214-226)이 하드코드 `neutral`.
- 변경: 완전일치 우선, 없으면 **`trade_date ≤ 요청일` 중 가장 최근 스냅샷을, 요청일과의 간격이 7일(달력) 이내일 때만** 채택. 그보다 오래됐으면 None(→ neutral) 유지.
- 폴백 채택 시 로그(`discovery_regime_snapshot_fallback`, 사용한 snapshot의 trade_date + 나이)로 관측성 확보.
- 개장 전 실행(regime_snapshot이 EOD 후에만 생겨 당일 행 부재)이 전일 실측 레짐(예 07-20 risk_off/bearish)을 정당한 근사로 사용하게 됨. non-binding(승격 자체엔 무영향)이나 문턱·가중치 정확성 개선.

---

## 4. Global Constraints (모든 태스크 공통)

- **리스크 규율 불변**: composite 문턱, daily_cap, cooldown, 이미보유/워치 dedup, watch_cap, LLM suitable 요구, 손절 게이트 — 어느 것도 완화하지 않는다. #1/#2/#3은 **입력 데이터 정확성**만 고친다.
- **fail-open/무해 계약 유지**: 발굴·flow·regime 조회 실패는 절대 발주/거래를 막거나 예외를 전파하지 않는다(기존 never-raise/fail-open 패턴 준수).
- **성과추적 무침습**: 원장의 raw_scores·_weights 의미를 바꾸지 않는다(flow 실측이 복구되면 raw flow가 실제 값으로 채워지는 것은 정상이며, 기존 재정규화 로직과 정합).
- **부호 규약 확정값**: `--N`=-N, `+N`=+N, `-N`=-N. `_parse_float`는 이 세 형태 + 소수(`-1.22`)·순수숫자·빈값·None을 모두 처리.
- **TDD**: 각 수정은 실패 테스트 → 최소 구현 → 통과 → 커밋. 실 LLM/네트워크 호출 금지(mock/스텁).

## 5. 테스트

- **#2 Fix A**: `_parse_float` 파라미터화 테스트 — `--35`→-35.0, `--3206`→-3206.0, `+122068`→122068.0, `-2`→-2.0, `-1.22`→-1.22, `+2.50`→2.50, `123`→123.0, `""`→0.0, `None`→0.0, `1,234`→1234.0.
- **#2 Fix B**: `get_inst_foreign_flow` 행 복원력 — 정상 rows + 1개 불량 행 mock 응답 → 불량 행만 skip, 나머지 파싱됨. 전량 불량 → None/빈. (mock `_request`, 실 네트워크 없음.)
- **#1**: `_build_llm_messages`가 flow_present=False면 "미가용" 문구, True면 `flow=X.XXX` 숫자 포함. Candidate flow_present 스레딩(rank_candidates가 factor의 flow_present를 Candidate에 반영).
- **#3**: `_get_regime_snapshot_for_date` — 완전일치 있으면 그것, 없고 D-1 스냅샷 있으면 폴백, 7일 초과면 None. `_extract_regime_label`이 폴백 스냅샷의 레짐을 반영.
- **회귀**: 기존 discovery 스위트(ranker/orchestrator/factors/scanner) 전부 green. `_parse_float` 콜사이트 회귀(가격/비율 파싱 불변).

## 6. 배포 후 검증 (구현 밖, 운용)

1. 재배포(서버 재시작) 후 raw ka10131 재캡처 → flow_map이 시장당 ~100 실측 채워짐 확인.
2. discovery 재실행(POST /trading/discovery/run 또는 15:30 자연 마감 엣지) → 원장에서 flow 실측 종목의 composite 변별력 + LLM이 flow-missing 종목을 더 이상 flow=0으로 거부하지 않음 확인.
3. 승격 발생 시 워치리스트 반영 + 다음 개장 fire로 실증. **실행 타이밍(개장 중 수동 재트리거 vs 15:30 자연 실행)은 구현·배포 후 사용자와 결정** — 개장 중 재실행은 rate 경합(현재 포지션 0이라 저위험)·15:30은 07-22 개장 대상.

## 7. 파일 요약

- `services/kiwoom/client.py` — `_parse_float`(473-482, Fix A), `get_inst_foreign_flow`(720-748, Fix B).
- `services/discovery/ranker.py` — `Candidate`(108-129, flow_present 필드), `rank_candidates`(342-443, 스레딩), `_build_llm_messages`(461-480, 분기), `_get_regime_snapshot_for_date`(229-245, 폴백).
- 테스트: `tests/test_services/test_kiwoom_*`(파서/flow), `tests/test_services/test_discovery_ranker.py`(프롬프트·flow_present·regime 폴백).

관련: [[session-2026-07-21-discovery-manual-trigger]] [[session-2026-07-20-discovery-quality]]
