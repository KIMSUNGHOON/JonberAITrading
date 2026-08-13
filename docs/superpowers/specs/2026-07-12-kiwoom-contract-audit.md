# Kiwoom REST 클라이언트 계약 감사 리포트 (Paper-Proof Phase A1)

2026-07-12. 원본: 공식 `Kiwoom-REST-API/` 레포 3종 — `kiwoom_docs/*.md`(스펙 문서), `kiwoom/_data/kiwoom_api_spec.json`(기계판독 스펙), `kiwoom/core/*.py`(참조 구현). 5개 병렬 감사(종목정보·시세/차트/계좌/주문/공통 프로토콜) + 읽기 전용 모의서버 스모크로 교차 검증.

**근본 원인**: `tests/test_services/test_kiwoom/test_client.py` 픽스처가 클라이언트와 동일한 가공 키(`output`, `hldg_qty` 등)를 사용 — 클라이언트가 공식 계약이 아닌 자기 목에 대해 검증되어 옴. api-id↔endpoint 매핑은 12개 TR 전부 정확하며, 문제는 **요청 파라미터 값 체계와 응답 파싱 키**에 집중.

## CRITICAL (실주문·운용 차단급 — Phase A에서 수정)

| # | TR/레이어 | 결함 | 영향 |
|---|---|---|---|
| C1 | kt10002 정정 | body 필드명 전면 불일치: `org_ord_no`→`orig_ord_no`, `ord_qty`→`mdfy_qty`, `ord_uv`→`mdfy_uv`, `trde_tp`는 스펙에 없는 필드 (주문.md:185-194) | 정정주문 100% 거부 |
| C2 | kt10003 취소 | `org_ord_no`→`orig_ord_no`, `ord_qty`→`cncl_qty`('0'=잔량 전부 취소, 주문.md:263-268) | 취소주문 100% 거부 → 취소 실패=의도치 않은 체결 위험 |
| C3 | cancel_order 소비자 | `kr_stocks/orders.py:334`, `order_agent.py:486`이 인자 1개(`order_id`)로 호출 — 시그니처는 3개 필수 | 취소 경로 호출 즉시 TypeError (감사가 아닌 본세션 직접 발견) |
| C4 | kt00004 보유종목 | 파싱 키 불일치: 정답 `rmnd_qty`/`avg_prc`/`pl_amt`/`pl_rt` (계좌.md:2032-2037) — 우리 키(`hldg_qty`/`avg_buy_prc`/`evlu_pfls_*`)와 폴백 전부 스펙에 없음 | 보유 수량/평단/손익 항상 0 → 손절/익절·포지션 사이징 무력화 |
| C5 | kt00004 종목코드 | 응답 `stk_cd`가 `A005930` 형태(A 접두사, 계좌.md:2128) — 스트립 없이 6자리와 비교(data_collection.py:60) | 보유 종목을 "미보유"로 판단 → BUY/SELL 분기 오류 |
| C6 | ka10075 미체결 | 리스트 키 `oso`≠`output`(계좌.md:463) + 요청 3필드 무효: `all_stk_tp` 의미 반전(0:전체/1:종목), `stex_tp`에 무효값 "KRX"(정답 0/1/2), `trde_tp` docstring 매수/매도 반전 + 아이템 6/10 필드 불일치(`ord_pric`/`cntr_qty`/`oso_qty`/`tm`) | 미체결 주문 영구 은닉(빈 리스트) |
| C7 | ka10076 체결 | 필수 요청 `qry_tp`/`sell_tp`/`stex_tp` 미전송(**모의서버가 거부 — 스모크 실증**) + 리스트 키 `cntr`≠`output` + 아이템 6/9 불일치(`cntr_qty`/`cntr_pric`/`ord_tm`/`io_tp_nm`; `ccld_amt`/`ccld_dt`는 응답에 없음) | 체결 내역 조회 자체 불가 → Phase C 체결 확인 차단 |
| C8 | ka10004 호가 | 응답 키 전면 불일치: 1호가 `sel_fpr_bid`/`sel_fpr_req`, 2~10호가 `sel_{n}th_pre_bid`/`_req`, 매수측 `buy_*`, 총잔량 `tot_sel_req`/`tot_buy_req`(시세.md:97-135) — 우리 키(`sell_hoga_*`)는 자사 WS 모델·KIS에서 온 것 | 호가 10단·총잔량이 조용히 0/빈 리스트 (스모크 "OK"로 통과한 이유 = 키 부재가 기본값으로 흡수) |
| C9 | 연속조회(전 TR) | `cont-yn`/`next-key`는 **응답 HTTP 헤더**로 옴(4개 감사 상호 확증; 참조 구현 core/client.py:232-238) — 우리는 body에서 읽고(`client.py:1148-9`) `_request_once`가 헤더를 버림(:267,290) | 전 TR 페이징 구조적 불가 — ka10099 전종목이 첫 페이지로 잘린 채 1h 캐시 |

## MAJOR (운용 품질 — Phase A에서 수정)

| # | 대상 | 결함 |
|---|---|---|
| M1 | kt00004 계좌 합계 | `lspft_amt`=**누적투자원금**을 손익으로 보고(정답 `tdy_lspft`/`lspft`); 평가금액에 `aset_evlt_amt`(예수금 포함)→현금 이중 계상(정답 `tot_est_amt`); `_parse_signed_price`의 `abs()`가 손익 음수를 양수로 뒤집음 |
| M2 | ka10001 종목정보 | `acml_tr_pbmn`은 ka10001 응답에 없는 키(항상 0); `lstg_stqt`→정답 `flo_stk`(항상 None이었음) |
| M3 | ka10099 판정 | `is_kospi`가 marketCode "10"을 코스피로 판정 — 스펙상 10=**코스닥**; is_kosdaq의 "20"은 존재하지 않는 값 |
| M4 | ka10081 차트 | `upd_stkpc_tp` 기본 "0"(원주가) — 액면분할 시 가짜 갭 캔들로 기술 분석(스펙 JSON이 삼성전자 2018 분할 예시로 명시 경고); `trde_prica` 단위 백만원인데 하류가 원으로 취급(mock 경로와 10^6배 불일치) |
| M5 | 인증 | `expires_dt`를 KST 지정 없이 naive 비교(UTC 컨테이너에서 9h 지연); `/oauth2/revoke` body에 `appkey`/`secretkey` 누락; 401/토큰만료(8005 등) 재발급-재시도 부재; 비-JSON 오류 응답 미처리 예외 |
| M6 | errors.py | 음수 에러코드 체계(-100~-903)는 실서버에 존재하지 않음 — 실제는 양수(1700 레이트리밋, 8001-8031 인증/모드) → `is_retryable`/`is_auth_error` 영구 불발 |

## MINOR (선별 수정/기록)

- kt10002/03 응답의 `base_orig_ord_no`·정정/취소수량 버림(주문 체인 추적 불가) / LIMIT+가격없음 클라이언트 가드 없음 / 모의서버 KRX-only인데 NXT/SOR 차단 없음
- kt00001 D+1/D+2 라벨이 실제로는 출금가능금액(`d1_pymn_alow_amt`) — 예수금은 `d1_entra`
- 비숫자 return_code를 client.py는 0(성공), auth.py는 -1(실패)로 상호 모순 처리 / 레이트리밋 판정이 예외 문자열 substring("1700" 오탐 가능) / rate_limiter 선언 5/s vs 실효 1.4/s 모순(공식 계약엔 수치 제한 명시 없음 — 보수적이라 안전)
- 죽은 폴백 키 다수(KIS/한투식 이름) — 무해하나 오해 소지 / docstring 반전·오기 여러 건

## OK로 확인된 것

kt10000/kt10001 매수·매도(시장가 `ord_uv:""` 포함 스펙과 바이트 단위 일치), trde_tp 코드표 18종, ka10001 핵심 시세 필드, ka10081 요청/응답 키(위 M4 제외), ka10099 요청/응답 키, kt00001 예수금, 토큰 발급 필드/응답, 요청 헤더 규격(Content-Type charset·소문자 authorization·api-id), return_code=0 성공 판정, Base URL 2종.

## 스모크 결과 (A2, 장외 1회차)

`scripts/kiwoom_readonly_smoke.py` — 7/8 PASS (유일 실패 = C7 ka10076, 모의서버가 필수 파라미터 누락 거부). 주문 메서드 몽키패치 봉쇄 가드 자체 검증 포함. 수정 완료 후 재실행 + 장중 1회차 예정.

## 수정 결과 (Phase A1 완료, 2026-07-12)

| 커밋 | 범위 | 해소 |
|---|---|---|
| `1235dd2` | 전송 계층 | C9(헤더 연속조회+ka10099 페이징), M5(토큰 KST/revoke body/401·8005 재발급-재시도/비-JSON 방어), M6(양수 에러코드+is_rate_limit·is_token_expired), MINOR(1700 substring→코드 비교, 비숫자 return_code 통일) |
| `f99638a` | 계좌 4 TR | C4(보유종목 스펙 키+부호 보존), C5(A 접두사 스트립), C6(ka10075 요청·파싱+매수/매도 정규화), C7(ka10076 필수 요청+cntr 파싱), M1(tot_est_amt 기반 합계·평가손익 계산), kt00001 D+1/D+2 라벨 정합 |
| `85cefba` | 주문 정정/취소 | C1(kt10002 orig_ord_no/mdfy_qty/mdfy_uv, trde_tp 제거), C2(kt10003 cncl_qty, 0=전량), C3(취소 라우트 stk_cd 확보+404, order_agent 시그니처 정합), MINOR(base_orig_ord_no 파싱) |
| `32716c1` | 시세/차트 | C8(호가 *_fpr_*/*_{n}th_pre_* 체계), M2(flo_stk/acml_tr_pbmn), M3(marketCode 판정), M4(수정주가 기본 1+거래대금 백만원→원) |

**게이트**: kiwoom 스위트 272 pass + 신규 계약 테스트 4파일(프로토콜 13/계좌 9/주문 4/시세 6), broad 스윕 673 pass(실패 4 전부 기존), **모의서버 스모크 8/8 PASS**(ka10076 실서버 검증 포함). 장중 스모크 1회차는 다음 개장 시 Phase C 시작 전 실행 예정.

**미수정(기록만)**: LIMIT+가격없음 클라이언트 가드 없음(서버 거부에 의존), 모의서버 KRX-only인데 NXT/SOR 차단 없음(기본 KRX라 기본 경로 안전), order_agent 내부 UUID≠브로커 ord_no(호출자 없는 경로, 주석 명시), rate_limiter 선언 5/s vs 실효 1.4/s(보수적 방향이라 안전), 죽은 KIS 폴백 키 일부 잔존(무해).
