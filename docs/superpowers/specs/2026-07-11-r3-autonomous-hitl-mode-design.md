# R3: Autonomous | HITL 모드 선택 — 설계 스펙

- **날짜**: 2026-07-11
- **상태**: 사용자 승인됨 (설계 A안 + 4개 노브 확정)
- **범위**: P0(안전레일·모드 저장·FE 토글) + P1(페이퍼 한정 자율 승인). P2(관찰)·P3(라이브 전환)은 별도 후속 결정.
- **선행**: R1 dead-code 대청소, R2 US 스택 제거 완료 (마켓 = kiwoom·coin 2개). P0-P7 로드맵 완료 상태.

## 1. 배경과 목표

시스템은 현재 HITL 전용이다: 분석 그래프가 `approval` 노드 앞 인터럽트에서 멈추고, 사람이 `/api/approval/decide`로 승인해야 실행 노드가 돈다. 사용자는 **Autonomous | HITL 두 모드의 선택권**을 원한다.

접근법 4안(A: 인터럽트 지점 auto-approve 주입 / B: 무인터럽트 그래프 변형 / C: coordinator 자율만 / D: A+C 하이브리드) 중 **A안이 승인**되었다. 근거: 그래프·인터럽트 무변경, P5/P6에서 확립한 단일-실행자 불변식 유지, 모든 자율 거래가 체크포인트에 승인 기록으로 남는 감사 추적, approval.py의 실행 후 알림(Telegram + WS trade-notifications) 100% 재사용, HITL 모드 무변경.

확정된 노브 (사용자 선택):
| 노브 | 결정 |
|---|---|
| 모드 범위 | **마켓별 토글** (kiwoom·coin 독립, 기본 둘 다 `hitl`) |
| 유예 창 | **60초 고정** (모듈 상수, 테스트에서 패치 가능) |
| P1 자율 액션 범위 | **전체 액션** (BUY/SELL/ADD/REDUCE/HOLD/WATCH — 페이퍼 한정이므로) |
| 안전레일 기본값 | **일일 손실 한도 3% / 최대 동시 포지션 5 / 거래당 금액 캡 ₩1,000,000** |

핵심 안전 원칙: **autonomous+live는 코드상 불가능** (게이트에 페이퍼 강제 하드코딩; P3에서만 그 줄을 의도적으로 수정한다).

## 2. 아키텍처

### 2.1 공유 자율 게이트 — `backend/services/autonomy/gate.py` (신규)

모든 자율 실행 요청이 통과해야 하는 **단일 정책 지점**. 소비자는 정확히 둘: ① 분석 파이프라인의 auto-approve 주입기, ② `ChatCoordinator`의 실행 직전. 두 자율 엔진(분석 그래프 + agent-chat coordinator)이 같은 정책을 공유한다 — "양 엔진 유지" 결정의 귀결.

```python
@dataclass
class GateDecision:
    allowed: bool
    reason: str           # 거부 사유 (허용 시 "ok")
    check: str            # 실패한 체크 이름 (허용 시 "all")

async def check_autonomy(
    market: str,                    # 'kiwoom' | 'coin'
    *,
    action: str,                    # BUY/SELL/ADD/REDUCE/HOLD/WATCH
    quantity: int | float | None,
    entry_price: float | None,
    # 주입 가능한 프로바이더 (테스트 시임; 기본값은 실제 구현)
    mode_provider=...,              # (market) -> 'hitl' | 'autonomous'
    daily_loss_provider=...,        # (market) -> float  (당일 실현손익, 음수=손실)
    positions_count_provider=...,   # (market) -> int
) -> GateDecision
```

검사 체인 (순서 고정, 첫 실패에서 deny):
1. **마스터 게이트**: `settings.AUTONOMY_ENABLED` (env, 기본 `False`)
2. **마켓 모드**: `mode_provider(market) == 'autonomous'`
3. **페이퍼 강제 (하드코딩)**: kiwoom → `KIWOOM_IS_MOCK is True`, coin → `UPBIT_TRADING_MODE == 'paper'`. 런타임 설정 오버라이드(kiwoom_singleton의 runtime is_mock)까지 확인한다. 이 검사는 설정으로 우회 불가.
4. **일일 손실 서킷 브레이커**: 당일 실현 손실이 계좌 평가액의 3% 초과 시 deny. 매 요청마다 재계산되므로 별도 상태 불필요 — 검사 자체가 브레이커다. 당일 첫 발동 시에만 Telegram 알림(메모리에 마지막 알림 날짜 기록, 스팸 방지).
5. **최대 동시 포지션**: `positions_count_provider(market) >= 5` 시 deny (BUY/ADD에만 적용; SELL/REDUCE/HOLD/WATCH는 포지션을 늘리지 않으므로 통과).
6. **거래당 금액 캡**: `quantity × entry_price > ₩1,000,000` 시 deny (BUY/ADD에만 적용).

한도 값은 `RiskParameters`(`services/trading/models.py`)에 필드 추가(`max_daily_loss_pct=3.0`, `max_open_positions=5`, `max_trade_notional_krw=1_000_000`)로 두고 기존 `PUT /api/trading/risk-params`로 변경 가능하게 한다.

**Fail-closed**: 프로바이더 예외·조회 실패 등 게이트 내부의 모든 예외는 `GateDecision(allowed=False, reason=...)`으로 변환된다. 자율은 언제나 "확실할 때만".

기본 프로바이더 구현:
- `mode_provider`: storage_service의 `app_settings` 조회 (2.2)
- `daily_loss_provider`: storage_service trades 테이블에서 당일(로컬 날짜) 실현손익 합산 ÷ 계좌 평가액(브로커 클라이언트). 데이터 없음 = 손실 0 = 통과; 조회 실패 = fail-closed.
- `positions_count_provider`: 기존 브로커 클라이언트(kiwoom singleton / upbit)로 보유 포지션 수 조회. 실패 = fail-closed.

### 2.2 모드 저장 — `app_settings` 테이블 (storage_service)

현재 런타임 설정은 전부 인메모리(재시작 소실)다. R3의 선결로 storage_service(SQLite)에 범용 key-value 테이블을 신설한다:

```sql
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)
```

- helpers: `get_app_setting(key, default)` / `set_app_setting(key, value)`
- 키: `trading_mode:kiwoom`, `trading_mode:coin` — 값 `'hitl' | 'autonomous'`, **행 부재 시 기본 `'hitl'`**
- API: `GET /api/settings/trading-mode` → `{kiwoom, coin, master_enabled}` / `PUT /api/settings/trading-mode` body `{market, mode}` (검증: market∈{kiwoom,coin}, mode∈{hitl,autonomous})

### 2.3 submit_decision 추출 (approval.py 리팩터)

`POST /approval/decide` 본문을 재사용 가능한 코루틴으로 추출한다 — **동작 무변경**:

```python
async def submit_decision(session_id, decision, feedback=None, modifications=None, actor: str = "user")
```

라우트는 얇은 래퍼. `actor`는 결정 상태에 `approval_actor` 키로 기록된다(레거시 state + sm 미러 + 그래프 resume_update) — 모든 자율 거래가 체크포인트·세션 기록에 `approval_actor='system'` 감사 흔적을 남긴다. 응답 스키마·FE 계약은 불변.

### 2.4 Auto-approve 주입기 (kr_stocks/analysis.py + coin/analysis.py)

백그라운드 분석 태스크가 `awaiting_approval` 상태를 쓰는 지점(양 파일의 기존 미러 위치) 직후:

```
if (게이트 사전 체크 통과):
    legacy state + sm 미러에 auto_approve_at = now + 60s 기록
    reasoning_log에 "[System] 60초 후 자율 승인 예정 — 레일에서 REJECT로 거부 가능" 추가
    Telegram 공지 (best-effort)
    asyncio.create_task(_auto_approve_after_grace(session_id, market))
```

`_auto_approve_after_grace`:
1. `await asyncio.sleep(AUTONOMY_GRACE_SECONDS)`  # 모듈 상수 60.0
2. **재확인**: 세션이 여전히 `awaiting_approval`인가(레거시 dict)? 유예 중 사용자가 수동 승인/거부/취소했으면 조용히 종료 — 수동 결정이 항상 이긴다.
3. **게이트 재확인**: `check_autonomy(...)` 재호출(유예 중 모드 off·브레이커 발동 반영). deny면 reasoning_log에 사유 기록 후 종료(세션은 HITL로 남음).
4. `await submit_decision(session_id, "approved", actor="system")`
5. 모든 예외는 로그 + 세션을 awaiting_approval 그대로 둠(**fail-closed** — 기존 HITL 흐름으로 자연 복귀).

수동 개입 race: 주입기와 사용자가 동시에 결정해도 `submit_decision`의 기존 `awaiting_approval` 검사(400)가 두 번째 호출을 거부한다 — 멱등 안전.

### 2.5 ChatCoordinator 게이트

`coordinator._handle_decision`에서 실행 분기(BUY/SELL/ADD/REDUCE) 직전에 `check_autonomy('kiwoom', ...)` 호출. deny 시: 실행 skip, 세션 기록은 유지, 로그 + Telegram "게이트 거부: {사유}" 알림. **의도된 행동 변화**: 기존에는 coordinator를 시작하면 무게이트로 실행했다 — 이제 자율 실행은 반드시 마스터 게이트+모드+페이퍼+한도를 통과해야 한다.

### 2.6 WS status 프레임 확장 (additive)

`_SessionFrameCursor`의 status 프레임 data에 **선택 필드** `auto_approve_at`(ISO 문자열)을 추가한다 — state에 있을 때만 포함. `awaiting_approval` 전환과 같은 순간에 기록되므로 그 전환의 status 프레임에 실려 나간다. 기존 FE 소비자는 미지의 필드를 무시하므로 계약-안전.

### 2.7 FE

- **store**: 작은 슬라이스 `tradingModes: {kiwoom, coin} | null` + `autonomyMasterEnabled` + fetch/set 액션. 앱 마운트 시 1회 조회.
- **SettingsModal**: 마켓별 Autonomous|HITL 토글 섹션. 마스터 게이트 off면 토글 비활성 + "AUTONOMY_ENABLED=false — .env에서 활성화 필요" 안내. PUT 실패 시 토스트.
- **OrderTicketRail**: ① 해당 마켓 모드가 autonomous면 idle 헤더에 `AUTONOMOUS` 배지(mono, accent). ② active 제안에 `auto_approve_at`이 있으면 카운트다운("자율 승인까지 N초") 표시 — 기존 [REJECT] 버튼이 즉시 거부권으로 그대로 동작(신규 버튼 없음). 카운트다운 도달 후에는 "자율 승인 처리 중…"으로 전환(서버 결정이 WS로 도착하면 기존 흐름대로 갱신).
- **상태 라인**(TerminalShell): 현재 활성 마켓의 모드 칩 `HITL` | `AUTO` (기존 PAPER 배지 옆).

## 3. 데이터 흐름 (P1 자율 승인 해피 패스)

```
분석 그래프 → awaiting_approval (인터럽트, 기존 그대로)
  → 주입기: 게이트 사전 체크 ✓ → auto_approve_at 기록 → WS status 프레임(카운트다운) + Telegram
  → 60s 유예 (사용자는 레일에서 언제든 REJECT/APPROVE — 수동이 이김)
  → 재확인(awaiting_approval? 게이트?) ✓
  → submit_decision(actor='system') → 그래프 resume → 실행 노드(페이퍼) → 기존 알림 전파
```

## 4. 파일 맵

| 파일 | 변경 |
|---|---|
| `backend/services/autonomy/{__init__,gate}.py` | 신규 — GateDecision, check_autonomy, 기본 프로바이더 |
| `backend/services/trading/models.py` | RiskParameters에 한도 3필드 추가 |
| `backend/services/storage_service.py` | app_settings 테이블 + get/set 헬퍼 |
| `backend/app/config.py` | `AUTONOMY_ENABLED: bool = False` |
| `backend/app/api/routes/settings.py` | GET/PUT /settings/trading-mode |
| `backend/app/api/routes/approval.py` | submit_decision 추출 + approval_actor |
| `backend/app/api/routes/kr_stocks/analysis.py`, `coin/analysis.py` | 주입기 |
| `backend/app/api/routes/websocket.py` | status 프레임 auto_approve_at (additive) |
| `backend/services/agent_chat/coordinator.py` | 실행 직전 게이트 |
| `frontend/src/store/index.ts` | tradingModes 슬라이스 |
| `frontend/src/api/client.ts` | getTradingMode/setTradingMode |
| `frontend/src/components/settings/SettingsModal.tsx` | 모드 토글 섹션 |
| `frontend/src/components/terminal/OrderTicketRail.tsx` | 배지 + 카운트다운 |
| `frontend/src/components/terminal/TerminalShell.tsx` | 상태 라인 모드 칩 |

## 5. 에러 처리 원칙

- 게이트/프로바이더의 모든 실패 = deny (fail-closed)
- 주입기의 모든 실패 = 세션을 awaiting_approval로 남김 (HITL 자연 복귀)
- 설정 조회 실패 시 FE는 모드 미상으로 표시하고 토글 비활성
- 서킷 브레이커 발동은 로그 + Telegram(일 1회) — 자율만 멈추고 HITL·분석은 정상

## 6. 테스트 계획

- **게이트 단위**: 체인 6단계 각각 (마스터 off / 모드 hitl / 라이브 강제 deny — kiwoom is_mock=False와 coin live 각각 / 브레이커 / 포지션 한도(BUY만) / 금액 캡(BUY만)), fail-closed(프로바이더 raise), SELL/REDUCE/HOLD/WATCH는 한도 5·6 미적용(포지션을 늘리지 않음)
- **저장**: app_settings set/get 왕복 + 기본값 hitl + 재시작 생존(새 커넥션)
- **submit_decision 추출**: 기존 approval 테스트 무회귀 + actor 기록(sm 미러 포함)
- **주입기**: 유예 후 자동 승인 / 유예 중 수동 결정 시 no-op / 유예 중 모드 off 시 no-op / 게이트 deny 시 reasoning 기록 / submit 예외 시 awaiting 유지 (유예 상수 패치)
- **coordinator 게이트**: deny 시 미실행 + 알림, allow 시 기존 경로
- **WS**: status 프레임에 auto_approve_at 포함 (있을 때만)
- **FE**: 토글 렌더/비활성 조건, 레일 배지·카운트다운 렌더, store 슬라이스

## 7. 범위 밖 (명시)

- P2 관찰 운영, P3 라이브 자율(별도 명시 동의 + sell-side 우선 + 이 스펙의 페이퍼 강제 라인 수정)
- 유예 창 설정화(60s 고정), 액션별 자율 범위 세분화
- StrategyEngine/트레이드 큐의 게이트 통합(coordinator 외 rule-엔진 경로는 현행 유지 — 시작 안 하면 휴면)
- 알림 채널 추가
