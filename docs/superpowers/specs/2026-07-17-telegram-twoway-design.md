# Telegram 양방향 설계 — 원격 거부권·긴급 정지·조회 명령 (autonomous 운용 전제)

- 날짜: 2026-07-17
- 상태: 설계 확정 (가치 판단 위임분 포함 — 사용자 "판단해 보고 plan 작성" 지시)
- 전제: HEAD `ff7738b`. python-telegram-bot **22.5** 설치 확인(핀은 >=20.0 — 본 아크에서 `~=22.5`로 강화). 2-트랙 디스커버리(2026-07-17) 근거.

## 0. 가치 판단 (autonomous 기본 모드 전제)

| 우선 | 기능 | 근거 |
|------|------|------|
| 1 | **승인/거부 인라인 버튼** | 자율 모드의 유일한 인간 개입 창=60초 유예가 현재 PC 전용 → 폰에서 거부/조기승인 = 자율 운용의 감독 반경 완성 |
| 2 | **/halt 원격 긴급 정지** (+2-스텝 /auto 재개) | 자율→HITL 전환은 fail-safe 방향이라 원격 허용이 안전. 이상 징후 시 폰에서 즉시 자율 차단 |
| 3 | **조회 명령** /status /positions /pending /report | 외출 중 상황 인지, 읽기 전용 저위험 |
| 제외 | 전량 청산·주문 발주·리스크 파라미터 변경 | 위험 대비 가치 불충분 — fail-closed 원칙상 보류 |

## 1. 아키텍처

**수신**: 신규 `services/telegram/receiver.py` — PTB `Application.builder().token().build()` **별도 인스턴스**(공존 방식 A: 기존 TelegramNotifier(송신)는 무변경 — fail-soft 관례 유지, getUpdates는 Application이 유일 소비자라 충돌 없음). FastAPI lifespan 통합은 PTB 22.5 공식 비블로킹 경로: startup에서 `await app.initialize()` → `await app.updater.start_polling()` → `await app.start()`, teardown에서 역순(`updater.stop()`→`stop()`→`shutdown()`) — `run_polling`은 자체 루프 기반이라 금지. **전 과정 best-effort**(미구성/토큰 오류/409 Conflict(이중 폴링) = 수신만 비활성+error 로그, 발송·서버 기동 무영향).

**보안 불변식**:
- 모든 update는 `effective_chat.id == TELEGRAM_CHAT_ID`(기존 단일 설정 재사용) 검사 — 불일치 시 **무응답+warning 로그**(chat_id·명령 기록).
- 미지 명령/일반 텍스트 = 무응답(또는 /help 안내 1회) — fail-closed.
- 특권 액션(승인/거부/모드 전환)은 chat_id 검사 + (버튼) proposal 피닝 + (자율 재개) 2-스텝 확인.
- 모든 핸들러 never-raise(개별 try/except → 오류 답장), `HTTPException`은 detail을 답장으로 변환.

## 2. 기능 설계

### F1. 승인/거부 인라인 버튼 (우선 1)
- **발송 지점**: producer의 awaiting 커밋 성공 직후 — `_finalize_awaiting_transition` 성공 경로(kr_stocks/analysis.py:228-229 부근, coin/analysis.py:209 부근). 디스커버리 확정: 이 지점이 session_id+SM 저장된 trade_proposal.id 모두 확정·HITL/자율 양쪽 커버·타이밍 갭 없음(그래프 내부 통지 :445는 awaiting 커밋 전이라 부적합 — 기존 상세 통지로 유지).
- **신규 `send_approval_request(session_id, market, proposal, auto_approve_at)`**(service.py 타입드 메서드): 제안 요약 + `[✅ 승인] [❌ 거부]` InlineKeyboard. 자율(auto_approve_at 존재)이면 "N초 후 자동승인 — 거부하려면 지금" 문구. **injector `_notify_pending`(:242-254)은 이 통지로 대체**(중복 발송 방지 — HITL도 이제 버튼 통지를 받으므로 상위 호환).
- **callback_data**: `a:{session_id}:{pid8}` / `r:{session_id}:{pid8}` (2+36+1+8=47B ≤ 64B 제한). pid8=proposal.id 앞 8자.
- **콜백 핸들러**: chat_id 검사 → `await query.answer()` → SM 라이브 세션 재조회, 현 proposal.id가 pid8로 시작하는지 대조(불일치=「제안이 변경되어 처리 불가」 편집) → `approval.submit_decision(session_id, "approved"|"rejected", actor="telegram", expected_proposal_id=<라이브 전체 id>)` **직접 호출**(injector 선례 :233, 동일 이벤트루프·자체 락) → 성공/HTTPException(404·409 등)을 `edit_message_text`로 원 메시지에 결과 반영+버튼 제거(이중 클릭 방지).
- **피닝 actor 확장**: approval.py:168의 stale-proposal pin 검사 `actor=='system'` → `actor in ("system","telegram")` — 텔레그램발 결정도 "내가 본 그 제안"만 유효. `approval_actor="telegram"`으로 감사 구분(FE·로그에 자율승인과 구별 표시).
- **rejected 재-arm**: 거부→재분석→새 proposal로 재-awaiting 시 producer 지점이 다시 발화하므로 **새 버튼 메시지가 자동 발송**(기존 메시지 버튼은 pid8 불일치로 무해 실패) — 구조적으로 성립, 테스트로 핀.

### F2. /halt · /auto (우선 2)
- `/halt`: kiwoom `trading_mode:kiwoom → hitl` (settings의 set 로직 재사용 — SQLite 영속, 게이트가 요청마다 재조회라 **즉시 반영**, 진행 중 60초 카운트다운도 유예 만료 시 게이트 재검(:204-218)에서 자동 stood_down). 확인 없이 즉시 실행(fail-safe 방향) + 결과 답장("자율 매매 정지됨 — 이후 제안은 수동 승인 필요").
- `/auto`: hitl→autonomous — **2-스텝**: 1차 응답에 `[⚠️ 자율 재개 확인]` 버튼, 콜백에서 전환 + **`rearm_awaiting_approvals()` 재호출**(디스커버리 함정: startup 전용이라 이미 awaiting 세션에 카운트다운이 안 걸림 — idempotent·fail-closed 확인됨) + 결과 답장. master 게이트(env AUTONOMY_ENABLED)가 꺼져 있으면 "env 마스터 게이트 OFF — 재시작 필요" 정직 답장.
- **이름 규칙**: 기존 `POST /trading/pause·resume`(코디네이터 일시정지 — 다른 의미)과 혼동을 피해 /halt·/auto 채택. 범위는 kiwoom만(coin 자율 미사용 — 후속).

### F3. 조회 명령 (우선 3)
- `/status`: 모드+master(settings의 응답 빌더 재사용)+coordinator active/daily_trades(:229-244)+agent-chat 하트비트(:216)+장 상태(:517).
- `/positions`: /operations holdings 소스(pnl·stop/take 포함, :1563 경로의 수집 함수 재사용).
- `/pending`: /operations awaiting(auto_approve_at 포함, :1460-1494) — 각 항목에 **F1과 동일한 승인/거부 버튼 재발송**(버튼 메시지를 놓친 경우 복구 수단).
- `/report`: 최신 eod_review 행 → 기존 `send_daily_summary` 포맷 재사용.
- `/help`: 명령 목록.
- 전부 기존 함수 직접 호출(FastAPI 의존성 없는 일반 async 함수임을 디스커버리 확인 — dependencies.py:147 등), HTTP 루프백 금지.

## 3. 비변경·안전 불변식
- TelegramNotifier(송신) 754줄 계약 무변경(공존 방식 A). 기존 통지 전부 유지(단 `_notify_pending`→`send_approval_request` 대체 1건).
- `submit_decision`은 check_autonomy 미호출(테스트 봉인) — 텔레그램발 수동 결정은 게이트 무관, 기존과 동일.
- 마스터 게이트(env)는 텔레그램으로 변경 불가. 모드 전환은 kiwoom 한정.
- 수신 실패·미구성이 서버 기동/발송/승인 파이프라인에 영향 0 (best-effort 격리).
- 실 폴링·실 발송은 테스트 금지 — 목 Update 직접 await(리포 AsyncMock 관례, PTB 객체 frozen이라 실객체 속성 교체 불가 주의).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 폴링 이중 기동(재시작 겹침) 409 Conflict | best-effort 격리 — 수신만 비활성+로그, 다음 재시작에서 회복 |
| 버튼 오클릭 승인 | 거부는 즉시, 승인도 피닝+라이브 대조로 "본 제안"만 — 오클릭 시에도 기존 HITL 승인과 동일한 안전성(게이트·paper 하드코딩 불변). 승인 버튼에 확인 스텝은 두지 않음(60초 유예 내 신속성 우선 — 사용자 판단 위임분) |
| /auto 오발 | 2-스텝 확인 버튼 |
| PTB 업그레이드 브레이킹 | `python-telegram-bot~=22.5` 핀 강화 |
