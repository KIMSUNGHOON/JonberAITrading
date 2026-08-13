# F4a: 세션 수명주기 정합화 — 설계

- **날짜**: 2026-07-14 (개장 전)
- **상태**: 설계 승인됨 (사용자, 2026-07-14 — 승인대기 복원 + F4a 우선 + age 게이트 6h 결정 포함)
- **근거**: 전면 기능 리뷰(2트랙, 52건 확정 — 수명주기 34 + 자율 18)의 P0 봉합. 자율(F4b)은 F4a 직후 별도 아크.

## 1. 문제 (라이브 실증)

C1 페이퍼 운용 중 백엔드를 8회 재시작하며 수정을 배포하는 과정에서 반복 발생:

- **6488fbec** (SK하이닉스 HOLD 승인 시 `Session not found`): 재분석(reject→re-analysis) 도중 재시작이 죽인 세션. DB `status=running` / `state.awaiting_approval=true` / `approval_status=rejected` / HOLD 제안 보유. 화면(열린 탭)엔 승인 카드로 보이지만 승인 클릭 → **404**.
- **dcc3d542**: 분석 도중(next=('decision',)) 죽음. `status=running` / `state.awaiting=false`. 2026-07-10 생성 후 3일간 매 재시작마다 재로드되는 불멸 행.
- **부활 좀비**(어제): cancel 결정의 DB 미러가 조용히 실패 → 재시작 후 승인 가능해 보이는 좀비.

## 2. 근본 원인 (리뷰 검증, HEAD 103fba8)

| # | 원인 | 근거 |
|---|---|---|
| S1 | **기동 시 세션 정합화 부재** — `_load_active_sessions`(session_manager.py:237)가 running+awaiting 행을 그대로 로드, 작업 재개도 정리도 없음. `cleanup_expired_sessions`(:505)는 completed/error/cancelled만 수거 → running 행 불멸 | session_manager.py:237, 505 |
| S1' | running-status sm 행은 **모든 엔드포인트에서 404** — KR status/cancel은 레거시 딕셔너리 전용(helpers.py:16), `/decide`는 adoption 게이트(approval.py:714)가 status!=awaiting를 None 반환→404. 404 raise가 zombie-cancel 분기(:143)보다 앞서 실행 | approval.py:135-170, 714 |
| S3 | FE `rehydrateKiwoomSessions`가 **add-only** — 서버에 없는 세션 카드 잔류, WS 재연결이 좀비 제안 재광고 | kiwoomSessionHandlers.ts:184 |
| F2 | approve→발주→최종 미러(:381) 이전 kill → sm `status=awaiting`+approved 잔류. zombie-cancel이 이를 "취소됨" 200으로 위장(실제 브로커 포지션 존재 가능) | approval.py:144, 214-223, 381 |

체크포인트 각도(라이브 검증): 6488fbec의 LangGraph 체크포인트는 `next=('approval',)`로 approval 인터럽트에 durable 파킹(P6 영속화) → flip 후 표준 `aupdate_state(decision)+astream(None)` resume 성립. dcc3d542는 `next=('decision',)`(분석 중) → flip은 함정(approve 요청 내 LLM 재실행).

## 3. 사용자 결정

1. **6488fbec형(체크포인트가 approval 파킹) → 승인대기 복원**(flip). 보드에 다시 떠서 사용자가 승인/거부/취소 직접 결정.
2. **BUY/SELL 제안 age 게이트 = 6시간**: 제안 생성 후 6시간 초과 시 flip 대신 ERROR(낡은 가격 제안 자동 부활 방지). 당일 장중 세션은 살리되 전일 이월은 폐기. HOLD/WATCH/AVOID는 execute 노드 no-trade라 age 무관 flip.
3. **F4a 우선, 자율(F4b)은 직후 별도 아크**.

## 4. 컴포넌트 설계

### 4.1 기동 시 세션 정합화 (P0-1, 근본 수정)

`services/session_manager.py`에 `async def reconcile_stranded_sessions() -> ReconcileReport` 신설. `initialize()`가 `_load_active_sessions` 직후 1회 await 호출(app.main lifespan은 initialize만 호출하므로 추가 배선 불필요). 로드된 각 세션을 shape별 처리(로드된 in-memory 세션 + `_save_session`으로 DB 반영):

| # | Shape (status / state.awaiting / approval_status / proposal) | 처리 |
|---|---|---|
| R1 | `running` / true / (any incl. stale 'rejected') / **proposal 있음** (6488fbec형) | **→ awaiting_approval flip**. 선택적 `graph.aget_state`로 `next==('approval',)` 확인 후 flip(확인 실패 시 R2로 강등). **BUY/SELL: proposal `created_at` 6h 초과 → R2(ERROR)**. HOLD/WATCH/AVOID/기타 무거래 액션은 age 무관 flip. `approval_status` 클리어(새 결정이 덮어씀), `auto_approve_at` 클리어, **자율 injector 재무장 안 함** |
| R2 | `running` / false / — / — (dcc3d542형), 또는 R1의 age초과/체크포인트 미파킹 강등 | **→ ERROR** `error="서버 재시작으로 분석 중단"` (TTL이 수거) |
| R3 | `awaiting` / false / **approved** (실행 중 kill) | **→ ERROR** `error="실행 중단 — 체결 확인 필요"` (P1-4에서 ka10076 정산 승격 — 본 스펙은 ERROR까지) |
| R4 | `awaiting` / true / **cancelled** (반쪽 미러 실패, ed56505 클래스) | **→ CANCELLED 정정** (state가 진실 — 좀비 자가치유) |
| R5 | `awaiting` / true / (none) / proposal 있음 (정상) | **유지** (4d2b005 restart-adoption 대상) |
| 공통 | 모든 복원 세션 stale `auto_approve_at` 클리어. status/state/approval_status 3자 불일치는 warning 로그. `ReconcileReport(flipped, errored, cancelled, kept)` 반환(로그/테스트) |

**checkpoint flip 안전성**: R1의 flip 대상은 반드시 "체크포인트가 approval에 파킹된 것"만 — age 게이트와 (선택적) `next` 확인이 이중 안전. R2로 보내는 것이 fail-closed 기본값.

### 4.2 WS 제안 프레임 상태 게이트 (P0-3)

`app/api/routes/websocket.py`의 제안 프레임 송출 조건(현재 `state.awaiting_approval`만 확인, ~:644)에 `session.status == "awaiting_approval"` 추가(AND). 정합화가 원천 running 행을 없애지만, 재시작 사이 열린 탭이 재연결할 때 stranded 제안 재광고를 이중 방어.

### 4.3 FE 스토어 정리형 재수화 (P0-2)

`frontend/src/api/kiwoomSessionHandlers.ts`:
- `rehydrateKiwoomSessions`: 서버 operations 응답(analyzing∪awaiting session_id 집합)을 받아, **스토어의 비터미널 kiwoom 세션 중 그 집합에 없는 것을 제거**(또는 error 마킹 — 제거로 결정: 좀비 카드/제안 소멸이 목적). 기존 add 로직은 유지.
- WS 재연결 시에도 재수화가 돌도록 배선(ManagedSocket onOpen 또는 SessionBridge 진입 시). 서버가 재시작돼 세션이 사라진 경우 재연결이 곧 정리 트리거.
- OrderTicketRail/OperationsPanel은 스토어 정리로 좀비 카드가 사라지므로 별도 수정 불필요(정리가 소스). 단 정리 후에도 `actionable=false` 게이트(ed56505)는 유지.

### 4.4 실행 중 kill 위장 방지 (P0-4)

`app/api/routes/approval.py` zombie-cancel 분기(~:144): 세션의 `approval_status=='approved'`면 취소를 **거부**(HTTP 409 `"실행 중일 수 있어 취소 불가 — 체결 확인 필요"`) 대신 순수 종결 마크 안 함. 4.1 R3의 ERROR 처리와 짝 — 재시작을 안 거친 in-flight(같은 프로세스 내 approve 진행 중 다른 탭 취소) 케이스 방어. (참고: d75b888 세션별 락이 같은 프로세스 내 동시성은 이미 직렬화하나, approved 마크와 최종 미러 사이 kill/취소 경합의 정직성 보강.)

## 5. 데이터 흐름 (재시작 스토리보드)

```
재시작 → SessionManager.initialize()
  → _load_active_sessions (running+awaiting 로드)
  → reconcile_stranded_sessions()  [4.1]
      6488fbec: running+awaiting+HOLD → awaiting_approval flip → 보드 승인대기 재등장
      dcc3d542: running+!awaiting → ERROR → TTL 수거
  → trading/start (사용자) → 코디네이터 blob 복원 (기존)
FE 로드/재연결 → rehydrateKiwoomSessions [4.3]
  → 서버에 없는 스토어 세션 제거 → 좀비 카드 소멸
승인 클릭 → /decide → R5 adoption 또는 R1 flip된 세션 정상 승인 (404 없음)
```

## 6. 테스트

- **정합화 TDD**(신규 `tests/test_services/test_session_reconcile.py`): 실 SQLite(temp fixture) + 각 shape 행 시딩 → `reconcile_stranded_sessions()` → 상태 검증. R1(HOLD flip / BUY age초과→ERROR / age내→flip), R2, R3, R4, R5(무변), auto_approve_at 클리어. 체크포인트 flip 안전성은 실 LangGraph 체크포인트 1케이스로.
- **WS 게이트**: status=running 세션의 제안 프레임 미송출 핀.
- **FE 정리 재수화**(kiwoomSessionHandlers.test.ts 확장): 서버 목록에 없는 스토어 세션 제거, 있는 것 유지, 재연결 트리거.
- **approval 409**: approved 상태 세션의 cancel 거부.
- **라이브 검증**: 재시작 후 6488fbec형 승인대기 부활 + dcc3d542형 ERROR 소멸 + FE 좀비 카드 소멸 + 승인 클릭 200.

## 7. 범위 밖 (별도)

- **F4b 자율**(직후): 유예 타이머 TOCTOU 자동승인(CRITICAL), AGENT_AUTO 손절 게이트 우회(check_autonomy 미배선), max_positions 캡의 F3 미체결 맹점, 텔레그램 오보, injector 재시작 고아 등 18건.
- **P1**: 미러 정직화(P1-1, ed56505 패턴 전 미러 이식), update_status 무음 no-op 관측성(P1-2), cancel 출처 기록(P1-3, c23b86dd 원인)+RUNNING ✕ 확인 다이얼로그, awaiting+approved의 ka10076 정산(P1-4, R3 승격).
- **P2**: 터미널 행 SQL-side sweep(P2-1), WS 스냅샷 캡 회귀 핀(P2-2), 정합화 불일치 감사 리포트(P2-3).
