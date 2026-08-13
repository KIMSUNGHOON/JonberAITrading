# 세션 상태 단일 SSOT 통합 설계 (Store A/B/C/D/E → SessionManager)

- 날짜: 2026-07-16
- 상태: 설계 확정 대기 (사용자 결정 4건 반영 + 3-렌즈 적대적 리뷰 findings 15건 봉합 완료)
- 범위: 백엔드 세션 상태 저장소 통합 P0~P5 + FE WS 스톰 지혈
- 선행 진단: 2026-07-16 7-도메인 병렬 디스커버리 워크플로우 + 완전성 비평 + 3-렌즈 spec 리뷰 (라인 근거는 전부 HEAD `d69f9aa` 기준)

## 0. 사용자 결정 레코드

| # | 결정 | 선택 |
|---|------|------|
| D1 | 수정 범위 | 다중저장소 통합(근본) + Store A까지 전체 통합 (이전 세션 결정) |
| D2 | Store A 통합 방식 | **완전 병합** — ChatSession의 저장·조회·히스토리를 SessionManager로 완전 이관 (레지스트리 패턴 기각) |
| D3 | WATCH/AVOID/HOLD 승인 큐 처리 | **현행 유지** — action-blind 시맨틱 불변, 읽기 소스만 교체 |
| D4 | LangGraph 체크포인트 GC | **terminal 전이 시 삭제 + 고아 sweep** |
| D5 | 진행 방식 | 전체 P0~P5 일괄 spec, 구현·배포는 단계별(배포는 매번 사용자 명시 승인) |

## 1. 문제 — 세션 상태가 5개 계층에 분산

승인대기(awaiting) 파이프라인의 세션 상태가 서로 다른 생존정책·읽기우선순위를 가진 5개 저장소에 분산되어, 비원자 best-effort 이중쓰기와 교차 reconciliation 부재로 뷰가 발산한다.

| # | 저장소 | 위치 | 생존 | 읽는 곳 |
|---|--------|------|------|---------|
| A | agent-chat 토론 인메모리 | `services/agent_chat/coordinator.py:147` `_active_rooms`(ticker→ChatRoom), `:150` `_session_history`(List[ChatSession], 캡 100 `:449-452`) | 휘발(재수화 없음) | `/agent-chat/sessions`·`/sessions/{id}`·`/sessions/{id}/messages`(`agent_chat.py:383-444`→`coordinator.py:1067-1091`), PositionManager 동기 소비(`position_manager.py:914-946`) |
| B | legacy 분석 dict | `kr_stocks/constants.py:17` `kr_stock_sessions`, `coin/constants.py:15` `coin_sessions` | 휘발 + **청소자 전무(프로세스 수명 누수)** | `/approval/pending`(`approval.py:679-724`), `/pending/{id}`(`:743-758`), **`/decide` 그래프 선택·market 판별(`:311-314`,`:437` — B 멤버십 기반)**, WS legacy-first(`websocket.py:528-533`), 인젝터(`_autonomy_injector.py:291-300`), dedup helpers(`kr_stocks/helpers.py:41-56`, `coin/helpers.py:66-88`), **KR `GET /analysis/status/{id}`(B-first+SM폴백, `kr_stocks/analysis.py:340-350`)·coin `GET /analysis/status/{id}`(B 단독·SM 폴백 없음 → 재시작 후 404, `coin/analysis.py:311`→`coin/helpers.py:38-46`)** |
| C | SessionManager | `services/session_manager.py` → `data/sessions.db`(612MB), 테이블 `analysis_sessions`(`:226-241`) | **영속 + 재시작 복원(`:264-301`, running/awaiting만 로드 `:292-295`) + reconcile(`:333-483`)** | `/operations`(`trading.py:1367-1403`, C 단독), WS 폴백 |
| D | LangGraph 체크포인트 | `agents/graph/sqlite_checkpointer.py:30-58` → `storage.db` checkpoints 테이블 | 영속 + **GC 전무(1GB, `delete_checkpoints` 호출자 0 — `storage_service.py:758-770`)** | 그래프 resume(`approval.py:333-335`, `aupdate_state+astream(None)`) — **awaiting의 실행 진실** |
| E | analysis_limiter | `app/core/analysis_limiter.py` | 휘발 | **슬롯 세마포어(acquire/release)는 KR·coin 양쪽 라이브**(`kr_stocks/analysis.py:232,324`); **로컬 dict 사본(`active_sessions:44`, register/update_session_status)은 coin만**(`coin/analysis.py:197-198,255`) — 시장 비대칭. `_sync_active_sessions`는 본문 pass(`:47-56`, 죽은 코드) |

Store A의 durable 원장(`agent_chat_decisions`/`agent_chat_votes`, storage.db)은 세션 저장소가 아니라 **완료 시 1회 기록되는 분석 원장**이며(`decision_log.py:160-177`) — 결정 요약+투표만 저장하고 **메시지·라운드 전문은 미보존**(`storage_service.py:294-335`) — EOD 폐루프(전략 P1~P5)가 의존한다. R5-P1 coordinator blob(`trading:coordinator_state`, `trading/coordinator.py:1052-1177`)도 세션 저장소가 아니다 — 둘 다 이번 통합의 **비변경(additive 확장만) 대상**(§7).

### 1.1 실증된 발산 시나리오 (디스커버리 확정)

1. **C 생성 실패 시 세션 유령화**: `create_session` 예외 시 로그만(`kr_stocks/analysis.py:182-198`) → 이후 모든 mirror가 in-membership 가드(`session_manager.py:582,608`)로 조용히 no-op → C에 영구 부재, 재시작 시 세션 완전 증발.
2. **노드 delta 미러 유실**: B는 `state.update(node_output)` 성공, 직후 `mirror_session_state` 실패가 삼켜지면 그 delta는 C에 영영 반영 안 됨(delta-only 미러) → B.state ⊋ C.state 영구. **trade_proposal/awaiting_approval이 C에 도달하는 유일한 경로가 이 미러다**(`kr_stocks/analysis.py:274,291`).
3. **취소 미러 실패 → 좀비 부활**: B=cancelled 전환 후 C 미러 실패 시 C row는 AWAITING_APPROVAL 잔존 → 재시작 시 B 소멸·C만 부활 → 좀비 제안 재노출(코드 주석이 라이브 2회 확인 명시, `kr_stocks/analysis.py:466-488`). coin 취소는 mirror_failed조차 미노출(`coin/analysis.py:425-431`, KR과 비대칭).
4. **resume 중 approved-미확정 창**: 최종 status 미러가 resume 끝(`approval.py:466`)에만 있어 긴 resume 중 C는 stale AWAITING_APPROVAL 노출.
5. **rearm/adopt 이중 복사본 status 분열**: 인젝터 rearm 클로저 세션(`_autonomy_injector.py:311-335`)과 `_adopt_session_from_manager`(`approval.py:801-880`)가 각각 별도 `to_legacy_dict()` 복사본 생성 — state는 C와 참조공유되나 status 문자열은 분열.
6. **역방향 retention 발산 + 진행형 SQLite 누수**: cleanup 태스크(`main.py:132` → `analysis_limiter.py:256-299`)의 1h TTL 삭제(`session_manager.py:38,698-727`)는 **인메모리 `_sessions`에 추적 중인 terminal 행만** 지운다. 재시작 로드는 running/awaiting만(`:292-295`)이므로 **terminal 전이 후 1h 이내에 재시작된 행은 영구 잔존** — sessions.db 612MB 비대의 근본 원인이며 1회성 정리 후에도 같은 메커니즘으로 계속 자란다. B는 아무도 안 지움. retention 4원화: B=프로세스 수명 / C=1h(추적 중일 때만) / 원장=영구 / 체크포인트=무한.

### 1.2 WS 재연결 스톰의 정확한 메커니즘 (급성 증상)

complete 프레임은 `completed/cancelled/error`에서만 발사되고(`websocket.py:722`) awaiting은 close하지 않는다 — "awaiting을 완료로 오판"이 아니다. 또한 **유령 카드 purge는 이미 구현되어 있다**: `rehydrateKiwoomSessions`가 서버 미등재 non-terminal 카드를 제거하고(`kiwoomSessionHandlers.ts:346-355`), WS drop→recover 시마다 재수화가 트리거된다(`:208-213`). 실제 스톰:

1. 재시작으로 B 소멸, C의 stranded 세션이 reconcile로 terminal(ERROR/CANCELLED) 전이.
2. FE 카드는 purge되지만 **소켓은 잔존**: `removeKiwoomSession`이 `wsManager.disconnect`를 호출하지 않아(`store/index.ts:1071-1104`) 카드 제거가 소켓을 종료시키지 않는다(유일한 disconnect 호출자는 AnalysisQueueWidget `:359`).
3. 서버는 접속마다 신규 `_SessionFrameCursor`(`:537`)로 전체 프레임 재전송 → complete → `COMPLETE_LINGER_SECONDS=2.0`(`:35,833`) 후 close.
4. FE ManagedSocket은 서버발 close를 장애로 보고 재연결 — **연결 성공이 백오프 예산을 리셋**(`wsCore.ts:206-223`)하므로 세션당 ~2초 주기 무한 재연결 × 잔존 소켓 수만큼 동시 스톰. 재연결 회복마다 재수화가 재트리거되어 `/operations` 콜까지 증폭.
5. 스냅샷 자체가 없는 세션(not-found)은 서버가 close도 안 하고 1s 세이프티 폴로 무한 유지 — 좀비 커넥션.

### 1.3 소비자단 발산 방어 코드 (분류 주의)

- `/operations`의 `actionable` 좀비가드(`trading.py:1292-1296,1400`): 발산 방어 — P3에서 단순화(필드는 FE 호환 위해 유지).
- WS proposal 이중 게이트(`websocket.py:645-655`): 발산 방어 — P3에서 단순화.
- **auto_approve_at 상태 재전송 트리거(`websocket.py:609-617`)는 방어가 아니라 기능 요건** — 인젝터가 awaiting 전이 *이후에* auto_approve_at을 쓰므로(`_autonomy_injector.py:74-88`) 이 트리거가 없으면 연결 중인 클라이언트가 60s 카운트다운을 영영 못 받는다. **통합 후에도 유지**(제거 시 자율 거부권 가시성 안전 회귀).
- `reconcile_stranded_sessions`(`session_manager.py:333-483`): 재시작 shape 복구 — **유지**(SSOT의 정식 기능으로 승격).

저장소 통합 **전에** 방어를 제거하면 라이브에서 좀비 제안 재노출 사고가 난다. 제거/단순화는 P3에서만.

### 1.4 ID 네임스페이스 이원성

`position.analysis_session_id`는 진입 경로에 따라 서로 다른 uuid 공간을 담는다: 그래프/HITL 경로 = 라우트 session_id(C 공간, `kr_stocks/analysis.py:92`, `execution.py:439-447`), 자율 토론 경로 = ChatSession.id(A 공간, Phase1 T3 스레딩). 완전 병합으로 두 공간이 SM 한 색인에 들어오면 이 컬럼의 조인이 어느 경로든 레지스트리에서 풀린다.

### 1.5 중첩 aliasing 주의 (특성화 테스트 함정)

`to_legacy_dict()`는 state를 참조공유하고, B/C가 같은 node_output dict를 각자 `update()`하므로 **중첩 가변객체는 이미 aliasing** 상태다(`session_manager.py:117,614-621`). "미러 실패=B/C 완전 독립 불일치" 모델로 특성화 테스트를 쓰면 잘못된 거동을 핀한다 — top-level 키 단위로만 발산이 성립한다.

## 2. 목표 아키텍처

**SessionManager = 모든 세션 종류(KR 분석 · coin 분석 · agent-chat 토론)의 단일 저장소 + 이벤트버스.** 6개 읽기 표면(`/approval/pending`+`/pending/{id}`, `/operations`, `/ws/session`, `/agent-chat/sessions`류, KR·coin `GET /analysis/status/{id}`)과 인젝터·helpers가 전부 C만 읽고, producer는 C에 직접 쓴다(미러 아님, fail-loud). B와 E의 로컬 dict는 삭제.

권위 규칙 3줄:

1. **UI/승인 자격 = SM이 이긴다.** pending/operations/WS는 SM 상태만 신뢰한다.
2. **resume 역학 = 체크포인트가 이긴다.** 단, SM이 AWAITING_APPROVAL인 세션만 resume 시도 자격이 있다(자격 판정은 SM).
3. **terminal 전이 = 체크포인트 동기 삭제 + sweep 백스톱.** 훅이 커버하는 전이 사이트에서 `delete_checkpoints(session_id)`를 호출하고, 훅을 우회하는 경로(§P5의 전이 사이트 전수 참조)는 주기 sweep이 회수한다.

상태 어휘: SM `SessionStatus` 5-값(RUNNING/AWAITING_APPROVAL/COMPLETED/ERROR/CANCELLED) **유지**. FE 5-Literal 계약(`schemas/kr_stocks.py:213,217`, `schemas/coin.py:180,182`)과 그래프 TypedDict 핀(`kr_stock_state.py:288,364`, `coin_state.py:263,333`)을 깨지 않는다. 토론의 세부 단계는 state JSON의 `sub_status`로 담고 agent-chat API 경계에서만 기존 어휘로 노출한다(§P4).

동시성 모델: 단일 uvicorn 프로세스 전제(run_dev). SM의 단일 `asyncio.Lock`(비재진입 — `session_manager.py:271-274` 문서화된 제약) 유지. 규칙: 공개 메서드만 락 획득, 내부 `_locked` 헬퍼는 공개 메서드를 재호출하지 않는다. approval의 `_session_decision_lock` 유지.

## 3. 단계 계획

각 단계는 독립 배포 가능 단위. 구현은 SDD(태스크별 구현→적대적 리뷰→봉합), 배포는 매번 사용자 명시 승인.

### P0 — WS 스톰 지혈 (최소·즉효)

- **P0-1 (FE)**: 세션 WS 어댑터가 `complete` 프레임 수신 시 소켓을 "정상 종료"로 마크하고 disconnect — 이후 서버발 close에 재연결하지 않는다. ManagedSocket 코어 정책(재연결/부활)은 불변, 세션 어댑터 레벨에서만 final 마크.
- **P0-2 (BE)**: `_get_session_snapshot`이 None을 일정 시간(기본 10s, config) 지속 반환하면 `{"type":"not_found"}` 프레임 + 전용 close 코드(4404)로 닫는다. 현재는 무한 세이프티 폴 유지(좀비 커넥션).
- **P0-3 (FE)**: **카드 제거 ↔ 소켓 해제 결합** — `removeKiwoomSession`(및 rehydrate purge 경로)이 `wsManager.disconnect(sessionId)`를 동반 호출. 4404/`not_found` 수신 시 카드 드롭 + 재연결 금지. (유령 카드 purge 자체는 기존 구현 유지 — `rehydrateKiwoomSessions`의 authoritative-guard 스윕.)
- 효과: 잔존 소켓발 재연결 스톰과 좀비 커넥션이 저장소 통합 전에 종식. FE-only 변경은 HMR, BE 변경은 재시작 필요.

### P1 — 읽기 통일 (뷰 발산 즉시 근절)

읽기 표면을 C 단독으로 전환. **시맨틱 보존이 원칙** — 판정 술어는 현행과 동일하게 유지하고 소스만 교체한다 (D3).

- `/approval/pending` + `/pending/{id}`: B 병합 스캔 → SM 스캔. **판정 술어는 현행 동일: `state.awaiting_approval` && `trade_proposal` 존재 (status 무검사, action-blind).** status 조건 접합은 도입하지 않는다 — 미러 시대(P1~P2 사이)에 status-미러-실패 세션을 배제해 invisible 창을 넓히기 때문. status 접합 강화는 P2(직접 쓰기로 status/state가 원자 갱신) 이후 선택 과제.
- WS `_get_session_snapshot`: legacy-first 제거 → `sm.get_session_dict` 단독.
- **KR·coin `GET /analysis/status/{session_id}`**: SM 단독으로 전환. coin은 현재 SM 폴백조차 없어(재시작 후 404) P1 전환이 곧 재시작 내성 개선.
- 인젝터 `rearm_awaiting_approvals`: legacy dict 스캔 제거 → SM 스캔 단독. "legacy 우선" tie-break(`_autonomy_injector.py:273-275`) 의미 소멸.
- **dedup helpers(`find_active_kr/coin_session`)는 P1에서 제외 — 현행(B-first) 유지.** 이유: B의 동기 placeholder 예약(`kr_stocks/analysis.py:100-125`, P4-T1 TOCTOU 가드)이 dedup의 원자성을 담보하는데, 읽기만 SM으로 바꾸면 예약이 보이지 않아 동시 시작 창이 재개방된다. 전환은 P2의 원자적 SM 예약과 함께.
- **동반 필수 조치 — awaiting-critical 전이의 write-through 승격 (P1의 최중요 항목):** 읽기가 C-only가 되는 순간, "C에 안 닿은 쓰기"는 코스메틱 발산이 아니라 **운용 정지급**(그래프는 인터럽트에 파킹돼 있는데 어느 표면에도 안 보이는 '보이지 않는 인터럽트' / 취소 미러 실패 시 C-only 뷰에 좀비 카드 즉시 노출)이 된다. 따라서 다음 3종 전이는 P1부터 best-effort 미러가 아니라 **fail-loud write-through(실패 시 1회 재시도, 최종 실패 시 B·C 양쪽 ERROR로 fail-closed 전이 + 에러 로그)** 로 승격한다:
  1. trade_proposal 세팅 + AWAITING_APPROVAL 전이 (`kr_stocks/analysis.py:290-291`, `coin/analysis.py:255-256`)
  2. 취소 (`kr_stocks/analysis.py:458-495`, `coin/analysis.py:372-435` — coin도 KR처럼 mirror_failed 노출로 통일)
  3. 승인/거부 결정 진입·재-arm (`approval.py:274-308,435-466`)
  - `create_session` 실패는 분석 시작 자체를 **fail-fast** 중단(현행: 로그만 하고 legacy-only 진행).
  - 그 외 노드 delta 미러(reasoning 등)는 P1에서는 현행 best-effort 유지(P2에서 직접 쓰기로 해소).
- `_adopt_session_from_manager`는 P1에서 **유지** — /decide의 그래프 resume이 아직 B의 state dict로 구동되므로(쓰기 경로), 제거는 P2.
- 킬스위치: config `SESSION_SSOT_READS`(기본 True) — False면 기존 B-first 읽기로 즉시 롤백. **유효 기간은 P2 배포 전까지**(§P2 참조).

### P2 — 쓰기 통일 (최고위험 — 그래프 핫패스)

producer가 SM에 직접 쓴다. 단일 상태 객체, upsert 아님 — **생성은 fail-fast, 갱신은 fail-loud**.

- 대상 write 사이트 전수(디스커버리 확정): `kr_stocks/analysis.py`(:110,158,171,241-243,273-274,290-291,302-306,319-321,458-495), `coin/analysis.py`(:129,142-158,197-198,237-238,255-256,268-273,288-289,372-435), `approval.py`(:274-308,339-343,351,435-466,620-622,240-244), `_autonomy_injector.py`(:81-101,120-187,311-335).
- **[리뷰 CRITICAL 봉합] /decide의 그래프 선택과 market 판별을 B 멤버십 → SM `market_type` 기반으로 교체**: `approval.py:311-314`(`if session_id in kr_stock_sessions: kr graph else coin graph`)와 `:437`(market 문자열)은 P2에서 B가 비면 **모든 KR 세션이 coin 그래프로 resume되는 치명 경로**다. `session.market_type`(KIWOOM→kr graph/'kiwoom', COIN→coin graph/'coin')으로 판별하고 그 외 market_type은 fail-closed 거부. 특성화 테스트로 "KR 세션 /decide가 KR 그래프로 resume"을 핀.
- **원자적 dedup 예약**: B의 동기 placeholder를 대체하는 SM 예약 — SM 락 안에서 "동일 ticker 활성 세션 check + RUNNING placeholder create"를 단일 연산으로 제공(`create_session_if_no_active` 형태), **dedup 체크 직후·모든 네트워크 조회(stock_info/balance) 이전**에 수행. stk_nm 등 후속 정보는 update_state로 채움. 실패 시 fail-fast(P4-T1 TOCTOU 시맨틱 보존). dedup helpers(`find_active_*`)의 SM 단독 전환은 이 예약과 함께 이 단계에서.
- B 쓰기 전면 제거. `_adopt_session_from_manager` 삭제 — /decide는 SM 세션의 state를 직접 사용.
- SM 갱신 시맨틱 변경: `update_state`/`update_status`의 in-membership 조용한 no-op(`:582,608`)를 **예외 발생(fail-loud)** 으로 전환. 세션 없이 갱신이 오는 건 버그다.
- **flush 모델(성능)**: 인메모리 SM이 라이브 읽기 진실. SQLite flush는 (a) status 전이·proposal 세팅·awaiting 플래그 변경 시 즉시, (b) reasoning_log 등 append성 delta는 ~1s 디바운스. pub/sub notify는 인메모리 기준 즉시(현행 유지). 현재의 "매 update마다 전체 state_json rewrite"(`:608-636`)를 핫패스에서 디바운스로 완화.
- 인젝터: rearm 클로저가 `to_legacy_dict()` 복사본 대신 SM 세션을 직접 참조 — status 분열(시나리오 5) 구조적 소멸. `auto_approve_at`·카운트다운은 SM 직접 쓰기로 전환(WS 재전송 트리거는 유지 — §1.3).
- resume 최종 status는 전이 즉시 SM 반영(시나리오 4의 stale 창 축소).
- **킬스위치 무효화**: P2 배포와 동시에 `SESSION_SSOT_READS`는 무효(True 강제/무시) — False로 내리면 아무도 쓰지 않는 빈 B dict를 읽어 pending 0건이 되는 "롤백처럼 보이는 장애 스위치"가 되기 때문. **P2부터 롤백 수단은 코드 리버트뿐**임을 배포 노트에 명시. 스위치 삭제는 P3.

### P3 — Store B·E 은퇴 + 방어코드 단순화

- `kr_stock_sessions`/`coin_sessions` 정의·게터·re-export·`get_kr_stock_session`/`get_coin_session` 헬퍼의 B 경로 삭제.
- `SESSION_SSOT_READS` 킬스위치 삭제.
- analysis_limiter 정리: 로컬 dict 표면(`active_sessions`, sync `register_session`/`update_session_status`/`get_analysis_stats`) 삭제 — coin 경로 4번째 사본 소멸. 슬롯 세마포어는 SM 위임 단일화, `release_analysis_slot`의 폴백 이중 세마포어(`:63-100`) 제거. `cleanup_old_sessions`는 SM cleanup 호출만 남김. **KR·coin 양쪽 start 경로의 슬롯 acquire/release 회귀 테스트 필수**(세마포어는 양 시장 라이브 — §1 E행).
- 소비자단 방어 단순화: `/operations` `actionable`은 응답 필드로 유지(FE 호환)하되 단일 소스에서 계산, WS **proposal 이중 게이트(`:645-655`)만** 단순화. **auto_approve_at 재전송 트리거는 기능 요건으로 유지(§1.3).**
- Store B 형태를 핀하는 테스트 9파일 이관: test_analysis_dedup, test_analysis_position_exists, test_approval_notification_honesty, test_approval_reschedule, test_approval_restart_resume, test_autonomy_injector, test_coin_analysis_sm_migration, test_kr_analysis_sm_migration, test_websocket_session (+ SM 계약 테스트 갱신).

### P4 — Store A 완전 병합 (D2)

ChatSession의 저장·조회·히스토리를 SM으로 완전 이관. ChatRoom 런타임 실행 핸들만 인메모리에 남는다(분석 세션의 asyncio task 핸들과 동격 — 실행 중 객체는 SQLite에 넣을 수 없음).

- **스키마**: `analysis_sessions`에 `kind` 컬럼('analysis'|'discussion', 기본 'analysis') — 리포 관례인 `_ensure_columns` PRAGMA+ALTER 패턴으로 추가(마이그레이션 기구 부재 전제).
- **상태 매핑**: SM status 5-값 유지. INITIALIZING/ANALYZING/DISCUSSING/VOTING → RUNNING + `state.sub_status`, DECIDED → COMPLETED, CANCELLED/TIMEOUT → CANCELLED. agent-chat API 경계에서 `kind=='discussion'`이면 `sub_status`를 기존 SessionStatus 어휘로 되돌려 노출 — **FE agent-chat 응답 shape 불변, 분석용 5-Literal 계약도 불변**.
- **[리뷰 봉합] kind 오염 차단**: 토론 세션이 같은 테이블에 들어오므로 **모든 SM 전역 스캔 소비자는 `kind='analysis'` 필터가 기본** — dedup helpers(`find_active_*`), `/operations` RUNNING 나열(`trading.py:1384-1391`), `/approval/pending` 스캔, 인젝터 rearm. `get_all_sessions`에 kind 파라미터 추가. 필터 없으면 (a) 진행 중 토론이 수동 분석 시작을 duplicate로 흡수, (b) watch 5분 주기 토론마다 /operations에 유령 "분석중" 카드가 뜬다.
- **쓰기 배선**: room 시작 시 `sm.create_session(session_id=ChatSession.id, kind='discussion', ...)`; 메시지/라운드/투표 append는 ChatSession 직렬화 → `state_json` 디바운스 flush(P2 모델 재사용); finalize 시 status 전이 + 원장 기록.
- **[리뷰 봉합] 직렬화 경계**: state_json에는 `ChatSession.model_dump(mode="json")` 결과만 넣는다 — 현행 `_save_session`의 `json.dumps(default=str)`(`session_manager.py:554`)는 `MarketContext.indicators`/`AgentMessage.data`의 numpy 스칼라 등을 문자열로 뭉개고 Any 필드라 model_validate가 조용히 통과시킨다. 왕복 테스트는 numpy/datetime 포함 실데이터 fixture로 재구성 동등성까지 단언.
- **[리뷰 봉합] 토론 전문(트랜스크립트)의 영속 — 원장 확장**: `agent_chat_decisions`에는 메시지·라운드가 없어 "영구 원장이 히스토리 담당"이 현행 스키마로는 성립하지 않고, FE는 `/agent-chat/sessions/{id}`(rounds+messages)와 `/sessions/{id}/messages`를 실소비한다(ChatSessionViewer.tsx:356, DebatePanel.tsx:129). **선택: persist 시 messages/rounds 직렬화 블롭을 원장에 additive 영속**(`agent_chat_transcripts` 테이블 또는 additive 컬럼, `_ensure_columns` 패턴) — 트랜스크립트가 영구화되어 재시작·TTL과 무관해지고, 사용자의 원래 목표("과거 매매+agent-chat 기록 정제→전략")에도 부합. 현행(프로세스 생존 중 최근 100세션만) 대비 순개선.
- **읽기 배선**: `/agent-chat/sessions` 목록 = SM(진행중, kind=discussion) + 원장(종료분, 영구) 병합 — **id 기준 dedup(SM 행 우선)**(finalize 직후 1h TTL 내에는 SM terminal 행과 원장 행이 공존). 상세/메시지 = SM 진행중 세션은 state_json, 종료 세션은 원장 트랜스크립트. **P4 이전의 기존 원장 행은 신규 필드가 NULL — 0/None-안전 기본값으로 채워 FE shape 보존**(ChatSessionList가 total_messages/total_rounds를 직접 렌더). `_session_history`(캡 100) 삭제. `/status`의 total_sessions는 원장 카운트로.
- **재시작**: reconcile이 kind-aware로 확장 — in-flight discussion(RUNNING)은 CANCELLED 처리(LLM 토론은 중간 재개 불가; 현행 "무기록 소실"이 "기록된 취소"로 개선). 분석 세션용 기존 reconcile 분기(체크포인트 검증·6h staleness)는 kind=analysis에만 적용.
- **불변 계약**: PositionManager `wait=True` 동기 소비(`position_manager.py:935-946`)는 그대로 — room.start()가 여전히 실행을 소유. `_active_rooms`는 실행 핸들 맵으로 역할 축소(ticker당 1 토론 유일성 가드는 핸들 맵 가드 유지). 승인 시 `add_to_watch_list` 접점, `_handle_decision`→autonomy gate 체인, decision_log/calibration 원장 소비 전부 무변경.
- **ID**: ChatSession.id(uuid)가 SM session_id로 등록 — A/C 네임스페이스가 한 색인에 통합(§1.4 해소).

### P5 — retention/GC 단일화 (D4)

- **terminal 전이 사이트 전수와 훅/스윕 배정** (리뷰 봉합 — reconcile은 `update_status`를 우회해 직접 대입한다):
  - `update_status`(terminal 값) → **훅에서 `delete_checkpoints` 동기 호출**
  - reconcile의 직접 대입 4분기(`session_manager.py:443-445,451-454,461-467`) → **훅 호출 추가**(재시작 좌초 세션이 고아 체크포인트 최대 생산자)
  - `remove_session`·`cleanup_expired_sessions`(`:698-727`) → **훅 호출 추가**
  - 그 외 우회 경로 → **주기 sweep 백스톱**(권위 규칙 3)
- awaiting/running 체크포인트는 보존(resume 필요). sweep: SM에 행이 없거나 terminal인 session_id의 체크포인트를 유예(24h) 후 삭제.
- **sessions.db 고아 terminal 행 sweep 추가** (§1.1-6 진행형 누수 봉합): cleanup 주기에서 인메모리 순회와 별개로 SQLite 직접 `DELETE WHERE status IN (completed,error,cancelled) AND updated_at < now-TTL`.
- retention 정책 명문화: awaiting=무기한(수동 취소/reconcile만이 종결), terminal 세션(분석·토론 공통)=1h TTL — **토론 트랜스크립트는 P4에서 원장에 영구화되므로 SM 행 TTL과 무관**. 원장(agent_chat_decisions·transcripts·strategy_revisions 등)=영구.
- 기존 비대분(sessions.db 612MB, storage.db 1GB checkpoints)은 **별도 1회성 운영 스크립트**로 정리 — 이 spec의 코드 변경과 분리, 실행은 사용자 승인 후. `data/analysis_sessions.db`(0바이트 유령 파일) 삭제 포함.

## 4. 테스트 전략

- 단계별 타깃 pytest만(conda agentic-trading, `cd backend && python -m pytest tests/...` — 전체 스위트 hang 금지 관례).
- **P2 전 특성화 테스트**: 발산 시나리오 1·3·5의 현행 거동을 핀하되 §1.5 aliasing 모델 주의 — top-level 키 단위로만 단언.
- **P1**: write-through 3종 전이의 fail-closed 거동(미러 실패→양쪽 ERROR), pending 술어 현행 동일성(state 플래그 기반, status 무검사), coin status 라우트 재시작 내성.
- **P2**: KR 세션 /decide가 KR 그래프로 resume(CRITICAL 핀), 동시 start 2건 → 그래프 1회 실행(원자 예약 핀), fail-loud 갱신, flush 디바운스 하 pub/sub 즉시성.
- 좀비 부활 회귀: 취소+쓰기실패 → 재시작 시뮬 → awaiting 재노출 없음.
- WS: complete-final(재연결 중단)·not_found 4404·카드 제거 시 소켓 해제 — FE vitest + BE 스냅샷 테스트.
- **P4**: ChatSession↔state_json 왕복 lossless(numpy/datetime 실데이터 fixture), kind 필터(dedup/operations/pending/rearm 4 소비자), 재시작 reconcile kind-aware, PositionManager wait=True 계약 불변, /agent-chat 병합 읽기 dedup + 레거시 행 NULL-안전.
- **P5**: terminal 전이 사이트 전수의 checkpoint 삭제(직접 대입 분기 포함), awaiting 보존, 고아 sweep 유예, sessions.db terminal 행 sweep.

## 5. 리스크와 완화

| 리스크 | 완화 |
|--------|------|
| P1 읽기 전환 후 '보이지 않는 인터럽트'/즉시 좀비 노출 (미러 유실이 운용 정지로 격상) | awaiting-critical 3종 전이의 fail-loud write-through + 실패 시 양쪽 ERROR fail-closed(§P1) + create fail-fast + `SESSION_SSOT_READS` 킬스위치(P2 전까지) |
| /decide 그래프 오선택 (B 멤버십 판별) | P2에서 market_type 기반으로 교체 + fail-closed + 특성화 테스트 핀 (CRITICAL) |
| dedup TOCTOU 재개방 | dedup helpers는 P1 제외, P2에서 SM 락 내 원자 예약(check+create)을 네트워크 조회 이전에 배치 |
| P2 핫패스 성능(락+전체 state_json rewrite) | 인메모리 진실 + 상태전이 즉시/append 디바운스 flush 분리, pub/sub 인메모리 즉시 |
| SM 락 비재진입 데드락 | 공개 메서드만 락, 내부 헬퍼 재호출 금지 규칙 + 리뷰 체크 항목 |
| 방어코드 조기 제거로 좀비 재노출 / 카운트다운 소실 | 제거는 P3에서만, auto_approve_at 트리거는 영구 유지(기능 요건) |
| P4 FE/그래프 breaking | status 5-값 유지 + sub_status + API 경계 매핑, kind 필터로 분석 표면 오염 차단, 그래프 TypedDict 무변경 |
| P4 토론 트랜스크립트 소실 회귀 | 원장에 트랜스크립트 additive 영속(영구) — TTL·재시작과 무관 |
| 체크포인트 삭제 오발(awaiting 세션) | terminal 전이 훅에서만 삭제, sweep은 24h 유예 + SM 대조 |
| 원장/EOD 폐루프 회귀 | agent_chat_decisions 스키마·persist 경로 additive만, calibration/eod 테스트 회귀 게이트 |
| 킬스위치 오사용(P2 후 False=pending 전멸) | P2 배포와 동시에 스위치 무효화, P3에서 삭제, 배포 노트에 "P2부터 롤백=코드 리버트" 명시 |
| 테스트 9파일 대량 수정 중 시맨틱 유실 | 파일별 이관 시 "무엇을 핀하는 테스트인지" 주석 유지, 의도된 delta는 P1 write-through fail-closed뿐(명시 기록) |

## 6. 배포 게이트

- 각 단계 종료 시: 타깃 회귀 클린 + 적대적 리뷰 통과 → 커밋. **배포(재시작)는 사용자 "배포" 명시 승인 필수**(라이브 자율 스택 핵심 경로).
- 권장 배포 순서: P0+P1 묶음 배포 → 라이브 관찰(스톰 소멸·pending/operations 일치 확인) → P2 배포 → 관찰 → P3 → P4 → P5.
- 라이브 검증 항목: 유령 소켓 0·WS 재연결 루프 0, `/approval/pending`과 `/operations` awaiting 집합 일치, coin status 라우트 재시작 후 200, 재시작 후 awaiting 카운트다운/승인 정상, KR /decide가 KR 그래프로 resume(P2 후), 토론 히스토리 재시작 생존(P4 후).

## 7. 명시적 비변경

- `agent_chat_decisions`/`agent_chat_votes` 원장과 전략 폐루프(P1~P5 EOD 리뷰·캘리브레이션·합의) — additive 확장(트랜스크립트·summary 컬럼)만, 기존 컬럼·persist 경로 무변경.
- R5-P1 coordinator blob(`trading:coordinator_state`) — 세션 저장소 아님. `positions[].analysis_session_id` 값 형식도 불변(P4로 조인 가능성이 좋아질 뿐).
- FE status 5-Literal 계약, 그래프 resume 방식(`aupdate_state`+`astream(None)`), 그래프 TypedDict 채널.
- autonomy gate 체인(fail-closed)·인젝터 60s 유예·proposal_id 피닝·auto_approve_at WS 재전송 트리거.
- 단일 프로세스 배포 형상(다중 워커 도입 시 락 모델 재설계 필요 — 스코프 밖).
