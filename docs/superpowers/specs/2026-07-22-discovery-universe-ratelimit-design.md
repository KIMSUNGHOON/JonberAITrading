# 발굴 유니버스 레이트리밋 복구 — 설계 기록

**날짜:** 2026-07-22
**Goal:** Kiwoom `return_code=5`(유량 초과) 오분류로 EOD 발굴이 15개 폴백 유니버스로 축소되는 문제를 근본 수정. 발굴이 전체(또는 부분) 유니버스를 스캔해 실질 승격 후보를 낼 수 있게 한다.

## 근본원인 (3각도 진단 확정)

Kiwoom가 rate-limit을 `return_code=5`("허용된 요청 개수를 초과 [유량=1]")로 반환하는데 **데이터 조회 경로가 치명·재시도 불가로 오분류**:
- `errors.py:18` `RATE_LIMIT_CODES = frozenset({1700})` — 코드 5 미포함 → `is_rate_limit=False`(errors.py:90-92).
- `client._request` 재시도 루프(1s/2s/4s, client.py:286-301)가 `if e.is_rate_limit:`를 건너뛰고 `else: raise` → **재시도 0회 즉시 폴백**.
- ⭐**비대칭 버그**: 인증경로(`auth.py:203`)는 `return_code==5`를 rate-limit으로 처리하나 데이터경로 미이식. 또한 `is_token_expired`(errors.py:106-110)는 이미 **중첩 메시지 마커 검사** 패턴 사용 — is_rate_limit에 동일 적용하면 됨.
- 연쇄: KOSPI 2480 성공 → KOSDAQ 첫 페이지 즉시(간격 없음) 유량 초과 → 재시도 없이 전체 폐기(2480도 버림) → 15개 하드코딩 폴백(scanner.py:326-330) → 승격 정당 억제(ranker.py:832).

## 사용자 확정 (AskUserQuestion)
**T1+T2+T3, 부분 승격허용** — 분류 수정 + KOSPI 부분 보존(승격 허용, 15개 fallback과 구분) + 스페이싱.

## 수정 설계

### T1 — 코드 5 rate-limit 분류 (errors.py) — THE fix
`is_token_expired`의 중첩 메시지 패턴 미러. **오탐 방지: 명확한 마커 있을 때만.**
```python
RATE_LIMIT_MSG_MARKERS = ("유량", "허용된 요청 개수")
# is_rate_limit:
#   code in {1700} or code == -903 → True (기존)
#   그 외: message에 rate-limit 마커 있으면 True (코드5 유량 포함)
```
`is_retryable = ... or is_rate_limit`(errors.py:131)이 자동 상속 → 기존 client 재시도/백오프(1s/2s/4s)가 KOSDAQ 유량에 발동 → 대부분 회복. **client/rate_limiter 무변경**(분류 한 곳).

### T2 — 부분 유니버스 보존 (client + scanner + ranker) + 시장 간 스페이싱
`client.get_all_stocks`(client.py:1543-1576)를 **시장별 회복력**으로:
- KOSPI/KOSDAQ 각각 try/except(개별 KiwoomError 포착). 성공분만 누적, 실패 시장은 `missing`에 기록.
- **반환 시그니처 변경**: `list` → `(stocks: list, missing_markets: list[str])`. 호출부 lockstep 갱신(census 필요, 주 호출=scanner._load_stock_list).
- KOSPI↔KOSDAQ 사이 `await asyncio.sleep(_INTER_MARKET_DELAY)`(T3 스페이싱, 기본 1.0s).
- 기존 필터(exclude_warnings·exclude_etf_etn) 보존.

`scanner._load_stock_list`(scanner.py:305-330):
- `stocks, missing = await client.get_all_stocks(...)`.
- `stocks` 비어있음(양 시장 실패) → 15개 fallback, `universe_fallback=True`(승격 억제, 현행).
- `stocks` 있고 `missing` 있음(부분, 예 KOSDAQ 결측) → **실제 유니버스로 사용**, `universe_fallback=False`, 신규 `universe_partial` 기록(승격 **허용**). `logger.warning("universe_partial", missing=..., count=...)`.
- `missing` 없음 → 전체 유니버스(현행).

scan_sessions 신규 컬럼 `universe_partial`(TEXT, 결측 시장 콤마조인 또는 빈문자). `_init_db` 마이그레이션(scanner.py:268 관행)·`_save_session_start` 기록. **승격 억제 안 함**.

ranker: `universe_fallback` 게이트(ranker.py:832) **불변**(양 시장 실패만 억제). `universe_partial`은 억제 미배선(승격 허용). 관측용으로 후보에 partial 기록(선택).

### T3 — ka10099 per-API 간격 상향 (rate_limiter + config)
현재 `KIWOOM_PER_API_MIN_INTERVAL=1.0`(config.py:102) 단일 스칼라가 전 api_id 균일. **ka10099(무거운 리스트 API)용 override**:
- config `KIWOOM_PER_API_OVERRIDES: dict[str,float] = {"ka10099": 2.0}`(또는 JSON env).
- `rate_limiter._acquire_per_api_then_global`(rate_limiter.py:194-228)가 `self._per_api_overrides.get(api_id, self._per_api_min_interval)` 사용.
- (T2의 시장 간 sleep과 함께 예방 2중.)

## 스코프 / 태스크
- **T1**(errors.py): 코드5 rate-limit 분류 + 테스트. THE fix, 최소.
- **T2**(client·scanner·ranker·scan_sessions): 부분 유니버스 보존 + 시장 간 스페이싱 + 승격정책(partial 허용) + 테스트.
- **T3**(config·rate_limiter): ka10099 per-API override + 테스트.

## 비목표 / 안전
- 15개 fallback 유니버스는 여전히 승격 억제(진짜 유니버스 아님). partial(KOSPI 2480)만 승격 허용.
- 기존 재시도 상수(MAX_RETRY_ATTEMPTS=3)·global 버킷·token 처리 무변경. 분류 마커는 명확어("유량"·"허용된 요청 개수")만 — 다른 code 오탐 방지.
- 실 네트워크 테스트 금지(KiwoomError 객체·모킹으로 분류·재시도·부분보존 검증).

## v-next 백로그(비포함)
ka10099 Kiwoom 실제 창 실측·ka10131 페이지네이션·per-API override JSON env화·유니버스 캐시(일 1회 실패 시 전일 재사용).
