# 스캔 완주 신뢰성 설계 — SC: 부분반영 + 동적 타임아웃

- 날짜: 2026-07-20
- 상태: 설계 승인됨 (사용자 "승인")
- 전제: HEAD `998c7e9`(P2 배포됨, PID 10061). 오늘 첫 discovery EOD 스캔 90분 타임아웃 사건의 근본 수정.
- 배경(실측): 2026-07-20 스캔 15:30:27~17:00:27(정확히 5400s=90분) stop, 3700/4276 저장(84.2%). ⭐핵심 반전: stop_scan이 status='running' 영구 고아 남김 → regime.py/ranker.py의 status='completed' 게이트가 0건 반환 → **84% 스캔이 통째로 버려짐**(breadth 0% 반영·랭킹 스킵). 90분 캡은 구조적 초과(4276×2콜×0.7s=99.8분 이론 소요; "예상 2500"은 시총 필터 통과 후 수치=2513, 실제 API 대상은 필터 전 원시 4276).

## 0. 결정 레코드 (사용자)
| # | 결정 | 내용 |
|---|------|------|
| SC-D1 | 스코프 | **타임아웃+부분반영** — 고아 버그 수정+partial breadth 반영+동적 타임아웃. 유니버스 사전 축소(전날 factor_json 재활용)는 별도 아크(신규 예외 처리 복잡), 속도 개선(rate limiter)은 규제 리스크로 범위 밖 |
| SC-D2 | 타임아웃 | **동적** — universe × 1.5s × 안전계수 + 여유. 정적 130/180분 아님. 하드 상한·하한 클램프 |
| SC-D3 | partial의 소비 범위 | breadth·랭킹(관찰)엔 반영, **승격(실행)은 완주 기준 유지** — 부분 스캔은 상위 종목 미관찰 가능성, 실행 보류가 안전 |

## 1. 실측 앵커 (디스커버리 확정 — 라인은 태스크 시작 시 재확인)
- 타임아웃: coordinator.py:71 `_DISCOVERY_SCAN_TIMEOUT_SECONDS=5400.0`·:72 poll 5.0s. 대기 :2756-2758 asyncio.wait_for → :2766 stop_scan. **제약=없음**(마감~개장 17.5h=63,000s 여유, 90분은 스펙 자의값).
- **고아 버그**: scanner.py:1770-1786 stop_scan이 `_cancel_event.set()`+status=IDLE+`_task.cancel()`뿐 — `_save_session_complete`(status='completed' 기록, :483-510,606-612)는 정상 완주 경로 끝에서만. status='failed'/'partial' 경로 부재 → 타임아웃/취소 시 scan_sessions row 영구 status='running' 고아(오늘 DB 실증).
- **소비 게이트**: regime.py:49-115 compute_regime_snapshot `WHERE status='completed' AND date(started_at)=?` → 오늘 0건. ranker.py:200-201 `WHERE status='completed' AND scan_mode='discovery'` → 랭킹도 0(승격만이 아님). orchestrator.py:157-158 backfill은 in-memory get_results 읽어 status 무관(부분분 활용됨).
- **처리율**: rate_limiter.py:40,150-157 `_query_bucket.min_interval=0.7`(전 조회 API 공유 단일 버킷) — 종목당 2콜×0.7s=1.4s/종목 이론, 실측 1.46s(4% 오차). semaphore=3(scanner.py:113)은 무영향(토큰 0.7s당 1개). use_llm=False(discovery). per-api 1.0s는 비바인딩.
- **유니버스**: scanner.py:289-293 get_all_stocks(KOSPI+KOSDAQ, exclude_warnings) — is_normal은 order_warning만 필터(우선주·스팩·관리종목 포함) → 4276 원시. 시총 하한(factors.py:36 500억)은 ka10001 호출 **후** 사후 적용(API 비용 이미 지불). ka10099 응답에 시총 필드 없음(client.py:1412-1420).
- **EOD 체인 순차**: _run_discovery_scan은 _check_queue_on_market_open(coordinator.py:2783) 내 동기 await → _queue_scheduler_loop(30s tick, :3218-3232) → 스캔 대기 중 write_daily_snapshot~run_eod_review~consensus~reconcile~discovery_pipeline~notify(2832-2856) 전부 블록. 타임아웃 상향=이 후속 지연폭 확대(하드 상한으로 제한).

## 2. 태스크 설계
### SC-1 고아 종결 + partial 상태 + 부분 breadth 반영
- scanner.py stop_scan: `_task.cancel()` **전에** 현 세션을 status='partial' 종결 기록(completed=현재 저장 수·completed_at·breadth 카운트 확정). 정상 완주=기존 'completed' 불변. 취소로 도달 못하던 종결을 stop 시점에 명시 기록.
- regime.py·ranker.py 게이트를 `status IN ('completed','partial')`로 확장(부분분도 breadth·랭킹 소비). 신규 세션 우선(최신 started_at) 유지.
- **승격은 scan_ok(완주=True) 기준 유지** — orchestrator run_discovery_pipeline의 rank/promote 분기가 partial일 때: rank는 수행(관찰·원장 기록)하되 promote는 scan_ok=False로 스킵(현행 타임아웃 경로 재사용 — partial도 완주 아님). 근거 SC-D3.

### SC-2 동적 타임아웃
- _run_discovery_scan 트리거 시 유니버스 크기(스캔 시작 시 scanner가 로드한 total_stocks — 접근 경로 실확인, 없으면 get_all_stocks len 사전 조회) 읽어 `timeout = clamp(universe × 1.5 × 1.3 + 600, 하한 5400, 상한 14400)`. 오늘 4276→8,340s≈139분.
- 산출 근거 로그(universe·이론 소요·적용 타임아웃).

### SC-3 관측성·정합
- partial 종결 시 로그·Telegram(있으면)에 "부분 완주 N/M(X%) — breadth 반영, 승격 보류" 명시(오늘 "분석 중지" 혼동 해소).
- regime_snapshot에 스캔 완주율 기록(source 메타 문자열 확장 또는 신규 nullable 컬럼 scan_coverage_pct — _ensure_columns 관례) — 사후 감사 "이 날 breadth는 X% 표본" 구분.

## 3. 비변경 불변식
- 스캔 수집 로직·rate limiter 정책(속도 개선 범위 밖)·discovery 승격 게이트 7종·EOD 체인 순서 무접촉. 정상 완주(status='completed') 경로 byte-불변.
- 실 네트워크·실 DB 테스트 금지(tmp scanner DB·목).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 동적 타임아웃 과대→EOD 후속 지연 | 하드 상한 14400s(4h, 17.5h 여유 대비 안전). ×1.5s는 실측 이론치 근거 |
| partial breadth가 상위 편향(스캔 순서=종목코드순이라 특정 섹터 과표집?) | 승격은 완주 기준 유지(관찰만 partial), regime_snapshot에 coverage 기록으로 사후 인지 |
| status='partial' 신규 상태를 다른 소비자가 미인지 | 소비처 전수 grep(regime/ranker 외 status 읽는 곳)+partial 처리 명시 |
