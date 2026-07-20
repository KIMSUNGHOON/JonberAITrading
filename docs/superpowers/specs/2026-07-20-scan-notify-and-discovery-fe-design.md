# 스캔 통지 게이트 + 발굴 결과 가시화 설계 — FI

- 날짜: 2026-07-20
- 상태: 설계 승인됨 (사용자 "승인")
- 전제: HEAD `51100e8`(오늘 6개 아크 배포됨, PID 21541). 사용자 보고 2문제(partial 통지 반복 스팸·발굴 결과 FE 부재)의 근본 수정.
- 배경(2트랙 진단 2026-07-20 밤): ①stop_scan이 partial Telegram 통지를 무조건 발송(notify_progress·수동/자동·DB영속 어느 것도 게이트 안 함) — 오늘 4276종목 EOD 스캔 타임아웃이 notify_progress=False인데도 통지 발송 실증(scan_sessions 20260720153027 status='running' 영구 고아). ②발굴 결과 FE 3중 부재: (A)discovery_candidates 조회 API 자체 없음 (B)EOD 리포트 discovery 섹션은 백엔드 배선됐으나 FE 타입·렌더러에 discovery 키 누락 (C)워치 FE가 source('discovery') 미표시.

## 0. 결정 레코드 (사용자)
| # | 결정 | 내용 |
|---|------|------|
| FI-D1 | FE 노출 범위 | **전용 발굴 조회 페이지까지** — EOD 패널 노출+워치 배지+신규 discovery 조회 라우트/페이지 |
| FI-D2 | 통지 정책(컨트롤러 확정) | partial 통지 스팸 근절: notify_progress 게이트+수동 정지 억제. EOD 자동 스캔 부분완주는 EOD 요약(scan_coverage_pct)이 커버(중복 통지 제거) |
| FI-D3 | 고아 세션 | 기동 시 status='running' 잔재를 'aborted'로 리컨실(오늘 20260720153027 포함) |

## 1. 실측 확정 사실 (진단 — 라인은 태스크 시작 시 재확인)
- **통지 무조건 발송**: scanner.py:1834-1895 stop_scan이 `if self._running:`만 가드, partial 통지(:1891) 무조건. notify_progress는 start_scan 파라미터로만 존재·self에 미저장(grep). 다른 발송 지점(:458 시작·:684 정상완료)은 notify_progress 게이트 있음(불일치). 정상완료=_send_scan_summary(:685).
- **호출자**: 자동=coordinator.py:2854(_run_discovery_scan 타임아웃, :2815 notify_progress=False). 수동=app/api/routes/scanner.py:210-214(POST /scanner/stop←FE DiscoverySection.tsx:403-414). 둘 다 동일 stop_scan(reason 파라미터 없음).
- **DB 디커플링**: _save_session_partial(:1849-1857 SC-1) best-effort, 실패해도 통지 발송. 오늘 고아=stop 커밋(0ae121d)이 SC-1(1e60799) 조상이라 partial 로직 부재.
- **60종목**: 재현 경로 부재(유니버스 4276~4277·폴백 15·custom_stocks만 임의개수). 로그 커밋해시 덮어쓰기로 증거 소실 — 숫자 출처 미특정, 메커니즘은 확정.
- **FE (A)**: app/api/routes 전체에 discovery_candidates/get_discovery_performance/scan_coverage_pct 0건. /discovery/* 라우트 없음. get_discovery_performance(ledger.py:219)는 strategy_panel.py:125 내부 소비만.
- **FE (B)**: eod_digest.py:369-451 _build_discovery_section이 report.digest.discovery 반환(trading.py:1037-1060). frontend/src/types/index.ts:1630-1642 EodDigest는 watch/account/holdings/strategy/regime 5키만(discovery 없음). PerformancePanel.tsx:351-360 EodDigestFallback 렌더러도 discovery 블록 없음(narrative 없는 비-LLM 경로에서 소실).
- **FE (D)**: WatchedStock.source(models.py:504·ranker.py:816 'discovery')가 GET /trading/operations watching에 포함되나 OperationsPanel.tsx:298-336 WatchingColumn이 source 미읽음. GET /trading/watch-list(trading.py:1294)는 client.ts:2117 getWatchList 호출부 0(죽은 API).
- **FE (E)**: scan_coverage_pct는 regime.py:109-139 계산·regime_snapshot 저장(SC-3)하나 eod_digest.py:352-366 _build_regime_section이 label/index 3필드만 반환 → EOD 응답 도달 전 백엔드에서 잘림.
- **currentView**: 이 프로젝트 FE는 라우터 없이 currentView Zustand store로 패널 전환(메모리 frontend-architecture).

## 2. 태스크 설계
### FI-1 스캔 통지 게이트 + 고아 리컨실
- start_scan에서 `self._notify_progress = notify_progress` 저장. stop_scan 통지 발송(:1891) 앞에 `if self._notify_progress:` 게이트(다른 지점과 통일). _send_scan_summary(정상완료) 무접촉.
- stop_scan에 `reason: str = "manual"` 파라미터. coordinator.py:2854=reason="timeout"(어차피 notify_progress=False라 게이트에서 막힘), route=reason="manual"(수동 정지=통지 억제, 자기 행동 재알림 불요). 결과=partial 통지 실질 발송 0.
- 고아 리컨실: 기동 시(app.main lifespan 또는 scanner init) scan_sessions status='running' 행을 'aborted'로 UPDATE(이전 프로세스 잔재만 — 현 프로세스가 방금 시작한 running은 없음, best-effort never-raise). regime/ranker의 status IN('completed','partial')는 aborted 제외(SC-1 게이트 무변경).

### FI-2 discovery 조회 백엔드 라우트
- `GET /trading/discovery/candidates` (trade_date·promoted·limit·offset optional) → storage.get_discovery_candidates(실시그니처 확인). Pydantic 응답 모델.
- `GET /trading/discovery/performance?days=14` → ledger.get_discovery_performance(storage, days).
- eod_digest.py:352-366 _build_regime_section 반환에 `scan_coverage_pct: row.get("scan_coverage_pct")` 추가(EOD 응답 도달).

### FI-3 EOD discovery FE + 워치 source 배지
- types/index.ts EodDigest에 `discovery` 키(백엔드 _build_discovery_section 반환 shape: promoted[]·skip_counts·total_candidates·prev_day)+EodDigestRegime에 scan_coverage_pct.
- PerformancePanel EodDigestFallback에 EodDiscoveryBlock(승격 리스트·스킵 카운트·전일 fwd_1d 요약)+regime 블록에 커버리지 표시.
- OperationsPanel WatchingColumn이 w.source 읽어 "발굴" 배지(source='discovery'만, manual=무표시).

### FI-4 전용 발굴 조회 페이지
- 신규 패널 컴포넌트(예: DiscoveryLedgerPanel.tsx) — currentView store에 뷰 등록(기존 패널 등록 관례). FI-2 candidates·performance 라우트 소비: 날짜 선택·승격 필터·후보 테이블(ticker·composite·최고전략태그·skip_reason·close_price·fwd 1d/5d/20d)·전략별 성과 요약. api/client.ts에 fetch 함수 추가.
- 진입: 기존 네비/커맨드(⌘K 또는 패널 탭)에 등록. 로딩/빈 상태/에러 처리.

## 3. 비변경 불변식
- 스캔 수집 로직·discovery 승격 게이트 7종·EOD 체인·계보·정상 완료 통지(_send_scan_summary)·rate limiter 무접촉.
- 기존 FE 패널·operations 응답 스키마(source 이미 포함)·EOD 라우트 응답(discovery 이미 포함) 무변경 — FE는 이미 오는 데이터를 읽기만.
- 실 네트워크·실 DB 테스트 금지(tmp·목·vitest).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 통지 게이트가 정상 완료 통지도 막음 | _send_scan_summary는 별도 경로·게이트 무접촉, partial(stop)만 대상 |
| 고아 리컨실이 현 프로세스 running 스캔 오정리 | 기동 시점(스캔 시작 전)만 실행, 현 프로세스 세션 없음. aborted는 regime 게이트 밖 |
| 신규 라우트 인증/오류 | 기존 trading.py 라우트 관례(의존성·에러)·빈 결과 정상 응답 |
| FE 신규 페이지 currentView 미배선 | 기존 패널 등록 관례 준수·진입점 명시 |
| FE 테스트 인프라 제한 | vitest 가능 범위(타입·순수 함수·배지 로직) 핀, 렌더 통합은 수동 확인 |
