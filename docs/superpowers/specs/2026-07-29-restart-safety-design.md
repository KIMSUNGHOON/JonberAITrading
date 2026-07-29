# 재시작 안전 — 부팅 시 자동 방어 복원 설계

**작성일**: 2026-07-29
**상태**: 승인됨 (설계 확정, 구현 대기)

## 문제

실 포지션을 보유한 채 백엔드를 재시작하면, 사람이 `POST /api/trading/start`를
칠 때까지 **손절·익절 방어가 전혀 없는 창**이 열린다.

복원 기계는 이미 전부 존재한다. `TradingCoordinator.start()`가
`_restore_state()`로 포지션과 손절을 `risk_monitor`에 재등록하고,
`ChatCoordinator.start()`가 `PositionManager.restore_stop_overlay()`로 스탑
오버레이를 되살린다. **없는 것은 단 하나 — 부팅 시 아무도 `start()`를
부르지 않는다.**

`app/main.py`의 `lifespan`은 LLM·스토리지·SessionManager·스캐너 고아정리·
레짐 마이그레이션·autonomy rearm·홀리데이·US신호까지 여덟 갈래를 되살리지만
트레이딩 방어만 빠져 있다. 프론트엔드에도 자동 호출이 없다 —
`frontend/src/api/client.ts`의 `/trading/start`·`/agent-chat/start`는 버튼
핸들러뿐이다.

2026-07-29 배포에서 이 갭이 그대로 재현됐다. 재시작 후 방어를 되살리기 위해
운영자가 손으로 두 줄을 쳐야 했다:

```
POST /api/trading/start
POST /api/agent-chat/start  {"max_concurrent_discussions": 10}
```

### 부수 문제 — ChatCoordinator는 상태를 전혀 영속하지 않는다

`ChatCoordinator._running`, `.check_interval`, `.max_concurrent`는 모두
인메모리다(`services/agent_chat/coordinator.py:386-413`). 재시작하면
생성자 기본값(`check_interval_minutes=1`, `max_concurrent_discussions=3`)으로
되돌아간다. 운영자가 동시 토론을 10으로 올려도 재시작이 3으로 되돌린다.
위 두 번째 명령에 `max_concurrent_discussions: 10`을 매번 손으로 넣어야 하는
이유이며, 이 설계가 함께 해소한다.

## 범위

**포함**: 두 코디네이터(트레이딩·에이전트챗)의 부팅 자동 재개 + 재개에 필요한
상태 영속.

**제외 — 코인 손절 모니터**: 별도 아크로 미룬다. 근거는 셋이다.
1. 코인 포지션 0개 (`GET /api/coin/positions` → 빈 배열)
2. Upbit API가 `401 no_authorization_ip`로 막혀 있어 실행 자체가 불가
3. 자율 파이프라인에 코인 경로가 없다 — `services/trading/coordinator.py`,
   `services/agent_chat/`, `services/discovery/` 통틀어 `MarketType.COIN`
   참조가 **0건**

즉 지금 코인 감시자를 만들면 자율 시스템이 만들 수 없는 포지션을 지키는,
실포지션으로 검증 불가능한 코드가 된다. Upbit IP 등록과 코인 자율 경로가
생길 때 함께 설계한다.

## 설계

### 1. 배치

책임을 둘로 나눈다. **"내가 활성이었나"를 아는 것은 각 코디네이터**(상태를
소유한 객체가 자기 복원을 책임진다), **"되살릴지 말지"를 정하는 것은
lifespan**(킬스위치·타임아웃·예외격리가 한곳에 모인다).

```
app/main.py  lifespan
  └─ [부팅 재개 블록]   킬스위치 · 60s 타임아웃 · never-raise · 로그
       ├─ await trading_coordinator.resume_if_persisted()
       └─ await chat_coordinator.resume_if_persisted()
```

새 모듈은 만들지 않는다. lifespan 블록은 같은 파일의 기존 복원 블록(스캐너
고아정리, autonomy rearm, 레짐 마이그레이션)과 동일한 관용구를 쓴다.

### 2. 영속 스키마

| 키 | 변경 | 내용 |
|---|---|---|
| `trading:coordinator_state` (기존) | 필드 1개 추가 | `"mode": "active" \| "paused" \| "stopped"` |
| `agent_chat:coordinator_state` (신규) | 신규 | `{"running": bool, "check_interval": int, "max_concurrent": int}` |

`mode` 값은 `TradingMode` enum의 문자열 값과 정확히 일치한다
(`services/trading/models.py:17-21` — `ACTIVE="active"`, `PAUSED="paused"`,
`STOPPED="stopped"`).

`TradingCoordinator._persist_state()`는 이미 상태 변경마다 호출되므로
blob에 `mode` 필드를 추가하는 것만으로 저장 경로가 따라온다.
`ChatCoordinator`는 `start()`/`stop()` 끝에서만 쓴다 — 설정이 그때만 바뀐다.

**하위호환**: 저장된 blob에 `mode`가 없으면 **재개하지 않는다**. 추측해서
되살리는 것보다 안전하다. 배포 후 운영자가 `/trading/start`를 한 번 치는
순간 `mode="active"`가 기록되고, **그 다음 재시작부터 자동**이다.
`_restore_state()`는 `mode`를 무시한다 — 재개 판단은 `resume_if_persisted()`
전용이며, 수동 `start()`는 기존대로 무조건 ACTIVE로 간다.

### 3. 재개 규칙

| 저장된 mode | 부팅 동작 |
|---|---|
| `"active"` | `start(drain_queue=False)` |
| `"paused"` | `start(drain_queue=False)` 후 `pause("restart resume")` |
| `"stopped"` · 없음 · blob 없음 | no-op |

`paused`를 `start`+`pause` 조합으로 푸는 것이 핵심이다. `pause()`는 감시를
유지하므로(`app/api/routes/trading.py:205` — "Pause auto-trading (keeps
monitoring)") 일시정지 상태로 껐어도 손절 방어는 되살아나고 신규 진입만
잠긴 채로 남는다.

`ChatCoordinator.resume_if_persisted()`는 저장된 `running`이 `True`일 때만
`check_interval`/`max_concurrent`를 복원한 뒤 `start()`한다.

두 메서드 모두 시그니처는 `async def resume_if_persisted(self) -> bool`이며,
반환값은 **실제로 재개했는지**다(no-op이면 `False`). lifespan 블록은 이 값을
로그에 싣는다.

### 4. 큐 드레인 스킵

`TradingCoordinator.start()`에 `drain_queue: bool = True` 인자를 추가한다.
`True`(기본)면 현재 동작 그대로 — 장중이고 큐가 비어 있지 않으면 즉시
`process_trade_queue()`. **부팅 재개 경로만 `False`**를 넘긴다.

근거: `QueuedTrade`에 만료 개념이 없고(`services/trading/models.py:424-455`
— `queued_at`만 있고 `expires_at` 없음) `process_trade_queue()`에 신선도
검사가 없다. 사람이 앞에 없는 장중 재시작이 몇 시간 묵은 가격으로 주문을
내는 것을 막는다. 방어(손절/익절)는 `drain_queue`와 무관하게 즉시 살아난다.

기존 오버나잇 대기 동작은 손대지 않는다 — 장이 열릴 때
`_queue_scheduler_loop`가 처리하는 경로는 그대로다.

`ChatCoordinator`의 `next_run_time=datetime.now()`(부팅 즉시 워치리스트 체크
1회, `services/agent_chat/coordinator.py:475`)는 **그대로 둔다**. 토론
트리거는 주문이 아니며 시세를 새로 읽으므로 stale 가격 위험이 없다.

### 5. 실패 처리

- **킬스위치**: `BOOT_AUTO_RESUME_ENABLED: bool = True` (`app/config.py`).
  `False`면 블록이 즉시 return하고 현재 동작(수동 재발행)으로 되돌아간다.
  레포의 기존 킬스위치 관용구를 따른다(`DISCOVERY_LIQUIDITY_GATE_ENABLED`,
  `LIQUIDITY_SIZING_CAP_ENABLED`).
- **타임아웃**: 재개 전체를 `asyncio.wait_for(..., timeout=60)`으로 감싼다.
  `start()`가 `_refresh_account_info()`로 키움을 호출하므로 API 장애 시
  부팅이 영원히 멈출 수 있다.
- **await 실행**: fire-and-forget이 아니다. 부팅 몇 초 지연이 무방비 몇 분보다
  낫다. (US 신호 갱신이 fire-and-forget인 것과 의도적으로 다르다 — 그쪽은
  캐시가 비어도 무해하지만 이쪽은 방어다.)
- **never-raise**: 재개 실패는 `logger.error` 후 부팅 계속. 단, **무성 실패는
  금지** — 방어를 켜지 못했다는 사실을 로그와 Telegram 양쪽에 남긴다.
  Telegram은 기존 `TelegramService.send_system_status()`
  (`services/telegram/service.py:581`)를 쓰고, 알림 전송 실패가 부팅을 막지
  않도록 그 호출도 자체 try/except로 감싼다.
- **위치**: lifespan의 autonomy rearm 블록 **이후**. 승인 대기 세션이
  카운트다운을 먼저 받아야 하고, SessionManager가 초기화돼 있어야 한다.

### 6. 부수 수정 — mode 설정 순서

현재 `TradingCoordinator.start()`는 `_persistence_active = True`(:384)를
`_state.mode = TradingMode.ACTIVE`(:390)보다 **먼저** 실행한다. 그 사이에
persist가 트리거되면 직전 mode(보통 `STOPPED`)가 저장돼, 다음 부팅이 재개를
건너뛴다.

`_state.mode = TradingMode.ACTIVE`를 `_persistence_active = True` **앞으로**
옮긴다. 원 주석의 요구("드레인보다 앞")는 그대로 만족한다.

### 7. 활동 로그 구분

부팅 자동 재개는 수동 시작과 구별되어야 사후 추적이 된다.
`_log_activity(ActivityType.SYSTEM_START, ...)` 메시지에 재개 경로임을
표시하고, `details`에 `{"boot_resume": true, "restored_mode": "<mode>"}`를
싣는다.

## 테스트

| 대상 | 검증 |
|---|---|
| 영속 라운드트립 | `mode` 저장→복원. `mode` 없는 기존 blob을 파싱해도 예외 없음 |
| `resume_if_persisted` (trading) | `"stopped"`/없음/blob없음 → `start` 미호출. `"active"` → `start(drain_queue=False)` 1회. `"paused"` → `start` 후 `pause` |
| 드레인 인자 | `drain_queue=False` → `process_trade_queue` 미호출. 기본값 → 장중+큐 있을 때 호출 |
| 킬스위치 | `BOOT_AUTO_RESUME_ENABLED=False` → 두 코디네이터 모두 미호출 |
| 부팅 견고성 | `resume_if_persisted`가 raise해도, 60s를 넘겨도 lifespan이 통과 |
| mode 순서 | `start()` 중 persist가 끼어들어도 저장된 mode가 `"active"` |
| agent-chat | `max_concurrent=10`·`check_interval=5` 저장 → 재시작 → 동일 값 복원 |
| agent-chat 미실행 | `running=False`면 `start` 미호출 |

## 바꾸는 파일

- `backend/app/config.py` — `BOOT_AUTO_RESUME_ENABLED`
- `backend/services/trading/coordinator.py` — `mode` 영속, `start(drain_queue)`,
  `resume_if_persisted()`, mode 설정 순서
- `backend/services/agent_chat/coordinator.py` — `_persist_runtime_state()`,
  `resume_if_persisted()`
- `backend/app/main.py` — lifespan 부팅 재개 블록
- 테스트: `backend/tests/`

## 검증 (배포 후)

실 포지션을 보유한 상태에서 **장 마감 후** 재시작하고, 사람이 아무것도 치지
않은 상태에서 다음을 확인한다:

1. `GET /api/trading/status` → `mode == "active"`
2. `GET /api/trading/positions` → 보유 종목과 손절가가 복원됨
3. `GET /api/agent-chat/positions` → PM 스탑 오버레이 복원됨
4. 로그에 `boot_resume` 활동 기록이 남음

장중 재시작은 실 포지션이 있는 동안 하지 않는다.
