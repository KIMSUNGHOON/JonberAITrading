# 자율 사이징 심화 — 계좌비례 notional 상한 + 영속 risk-params + 전체 UI (설계)

> Status: DESIGN (brainstorming 산출물). 2026-07-16. 사용자 최종목표 = **완전 자율 매매 시스템**.
> 실사 근거: PortfolioAgent 사이징 실코드·gate.py notional 체크·strategy_apply denylist·영속 패턴.

## 목표 (Goal)
자율 포지션 사이징을 무력화하던 **고정 ₩1,000,000 per-trade notional 상한**을 **계좌 총평가액 비례(%)** 상한으로 바꾸고, 전략이 그 상한을 **하드 바운드 내에서 적응적으로 조정**하게 하며(사용자 결정 B — 완전 자율), 모든 risk-params를 **재시작 넘어 영속**시키고 **UI 패널로 노출**한다.

**전제 정정:** 자율 포지션 사이징은 이미 존재한다 — `PortfolioAgent._calculate_buy_allocation`이 예수금(가용자본 = 예수금−최소현금)·총평가액·리스크점수로 포지션 크기를 산출한다(`position_value = min(가용자본, max_position_value); quantity = position_value/진입가`). 문제는 그 위의 고정 ₩1M notional 상한이 gate에서 잘라내 전부 거부시킨 것. 이 설계는 "자율 사이징 구축"이 아니라 그 **안전 상한을 계좌비례·적응형·사용자설정 가능**하게 만든다.

## 결정 B의 안전 프레이밍 (중요)
사용자는 **B**(전략이 notional 상한을 적응적으로 조정)를 명시 선택했다 — 이유: 완전 자율 매매가 최종 목표. Phase 4는 `max_trade_notional_krw`를 `GATE_PROTECTED_FIELDS`에 봉인해 LLM 전략의 self-deregulation을 막았는데, B는 이 봉인을 푼다. **책임 있는 구현**: 완전 해제가 아니라 **기존 allowlist 4필드와 동일한 하드 바운드(KNOB_BOUNDS) 클램프**를 적용 — 전략은 `[5%, 30%]` of equity 내에서만 notional 상한을 조정할 수 있고 그 밖으로는 물리적으로 못 나간다. "완전 자율 + 하드 클램프 안전바닥/천장". 열화·적대적 LLM도 1건당 최대 30% of equity를 넘지 못한다.

## 아키텍처 (4 컴포넌트)
```
[UI RiskParams 패널] ──PUT /risk-params──▶ coordinator.risk_params (in-place) ──▶ app_settings 영속
        ▲ GET /risk-params                                    │
        └──────────────────────────────────────  startup ──restore_state──┘
                                                              │
autonomy gate notional 체크: quantity×entry_price  vs  total_equity × max_trade_notional_pct/100
                                                              │
EOD 전략 합의 ──strategy_apply(allowlist+bounds)──▶ max_trade_notional_pct 적응 조정 ──▶ 영속
```

## 컴포넌트 & 스키마

### C1. 계좌비례 notional 상한 (gate + models)
- **`RiskParameters`(models.py:206)**: `max_trade_notional_krw: float = 1_000_000` **제거** → `max_trade_notional_pct: float = Field(default=15.0, ge=0.5, le=50.0)` 신설(총평가액 대비 %). 필드 하드 리밋 [0.5, 50]은 절대 물리 상한(전략 바운드 [5,30]과 별개, PUT/전략 모두 이 필드 범위 안).
- **`gate.py` notional 체크(320-328)**: `total_equity`를 브레이커가 쓰는 동일 소스(`balance.evlu_amt + balance.d2_ord_psbl_amt`, gate.py 브레이커 랩)에서 얻어 `cap = total_equity × params.max_trade_notional_pct / 100`; `if notional > cap: deny`. **fail-closed**: 계좌 조회 실패/`total_equity <= 0`이면 deny(브레이커와 동일 규약). 계좌평가액 provider를 브레이커 로직에서 추출해 재사용(중복 조회 회피 — 게이트 1회 fetch 공유).
- **불변**: "quantity/entry_price unknown = fail-closed" 가드(직전 세션 #3 결정) 그대로 유지.

### C2. 전략 적응형 notional (바운드 내) — 결정 B
- **`PositionSizingRules`(strategy.py:91)**: `max_trade_notional_pct: float = Field(default=15.0, ge=0.5, le=50.0)` 추가. 4프리셋(strategy.py:176/219/261/301 등)에도 값 지정(보수=10, 공격=20 등).
- **`strategy_apply.py`**:
  - `GATE_PROTECTED_FIELDS`에서 `max_trade_notional_krw` **제거**(더 이상 존재 안 함).
  - `STRATEGY_MAPPED_FIELDS`에 `"max_trade_notional_pct": (5.0, 30.0)` 추가(하드 바운드 클램프).
  - `_source_values`에 `"max_trade_notional_pct": strategy.position_sizing.max_trade_notional_pct` 추가.
- **테스트**: `test_gate_protected_fields_never_move`에서 notional 제거(이제 mapped). 신규 `test_strategy_notional_pct_clamped_to_bounds`(전략이 40 제안→30 클램프, 2 제안→5 클램프).
- **문서화**: strategy_apply 도크스트링에 "notional_pct는 결정 B로 allowlist화 — self-deregulation 완화이나 [5,30] 하드 바운드로 봉쇄" 명시.

### C3. 영속 risk-params (SQLite)
- **`coordinator._persist_state`(R5-P1)**에 `risk_params`(model_dump JSON) 추가 → app_settings. **`_restore_state`**에서 복원(startup).
- **PUT /risk-params(trading.py:317)**: in-memory 갱신 후 `await self._persist_state()`(또는 risk_params 전용 persist) 호출.
- **복원 순서/우선순위**: startup → 영속 risk_params 복원(in-place setattr, rebind 금지) → 그 뒤 `_restore_strategy`가 allowlist 필드를 전략값으로 매핑(전략이 SSOT인 필드는 전략이 이김, Phase 4 규약). 사용자설정 비전략 필드(max_daily_loss_pct·max_open_positions·모드 등)는 영속값 유지.
- **RiskParamsUpdateRequest(trading.py:110-)**: `max_trade_notional_krw` 필드 → `max_trade_notional_pct: Optional[float] = Field(None, ge=0.5, le=50.0)`.

### C4. 전체 risk-params UI 패널 (frontend)
- **신규/확장 RiskParams 패널**(TradingDashboard.tsx 또는 신규 컴포넌트, /trading 또는 설정): 컨트롤 —
  - `max_trade_notional_pct`(슬라이더/입력, % + **계산된 ₩ 표시** = pct × 현재 총평가액)
  - `max_single_position_pct`, `min_cash_ratio`(%)
  - `max_daily_loss_pct`, `max_open_positions`
  - `stop_loss_mode`, `take_profit_mode`(user_approval/auto 등 셀렉트)
- **배선**: `client.ts` GET/PUT /risk-params + `types/index.ts` RiskParams 타입에 notional_pct. 로드→편집→저장, 저장 후 갱신된 risk_params 반영.
- **표시**: 현재 유효값(전략이 적응했을 수 있음) + notional의 ₩환산. 전략-소유 필드는 "전략 적응 중" 힌트(선택).

## 데이터 흐름 (요약)
1. UI 로드 → GET /risk-params → 현재값 표시(+notional ₩환산).
2. 사용자 편집 → PUT /risk-params → coordinator.risk_params in-place 갱신 + app_settings 영속.
3. gate BUY 체크: `notional > total_equity × pct/100` → deny/allow(계좌비례).
4. EOD 전략 합의 → strategy_apply가 notional_pct를 [5,30] 내 적응 조정 + 영속.
5. 재시작 → risk_params 복원 → 전략 재적용.

## 에러 처리 & 불변식
- **fail-closed**: notional 체크의 계좌평가액 조회 실패/≤0 → deny(깜깜이 금지, 브레이커 규약 일치). quantity/entry_price None → deny(불변).
- **하드 바운드 이중화**: 필드 물리 리밋 [0.5,50](RiskParameters) ⊃ 전략 적응 바운드 [5,30](strategy_apply). 어느 경로도 필드 리밋 밖 불가.
- **in-place 규약**: risk_params는 PortfolioAgent/RiskMonitor/TradingState와 참조 공유 — 복원·PUT·전략매핑 전부 **setattr in-place, rebind 금지**(Phase 4 함정).
- **영속 실패 무해**: risk_params 영속 실패가 매매를 막지 않음(로그+계속).
- **coin 범위 밖**: notional %상한은 KR(kiwoom) 게이트 대상(기존 KRW 필드와 동일 KR 지향). coin은 별도(후속).

## 테스트 (TDD)
- **C1**: gate notional 체크가 `total_equity × pct`로 스케일(equity ₩426M·pct 15 → 상한 ₩63.9M, notional ₩50M allow / ₩70M deny). 계좌조회 실패→deny. equity 0→deny.
- **C2**: strategy_apply가 notional_pct를 [5,30] 클램프(40→30, 2→5). `test_gate_protected_fields_never_move`에서 notional 제외(회귀). set_strategy(None)→모델 기본 15 복귀.
- **C3**: PUT→_persist_state→재시작 복원 시 notional_pct 유지. 전략 복원이 그 위에 매핑. in-place(참조 동일성) 검증.
- **C4**: 패널 GET 로드/PUT 저장, notional ₩환산 표시(pct×equity), 잘못된 범위 거부(FE 검증).
- **회귀**: 기존 gate/strategy_apply/coordinator/risk-params 테스트 PASS(특히 notional 필드명 변경 전수 반영: gate.py·models.py·strategy_apply.py·trading.py·FE).

## 범위 밖 (후속)
- coin(Upbit) notional %상한.
- 매도 체결 배선 버그(R5-P4, 별개 — 사용자 보류).
- risk-params UI의 실시간 전략-적응 애니메이션/이력 시각화.
- notional 필드 rename의 DB 마이그레이션(risk_params는 app_settings JSON이라 스키마 마이그레이션 불요 — 구 KRW 키는 복원 시 무시, 신 pct 키 없으면 모델 기본 15).

## 마이그레이션 노트
- `max_trade_notional_krw` → `max_trade_notional_pct` **전역 치환**: models.py·gate.py·strategy_apply.py(denylist→allowlist)·trading.py(PUT 스키마+핸들러)·FE(client/types/컴포넌트). grep `max_trade_notional_krw`로 전수 확인.
- 영속 risk_params(app_settings JSON): 구 배포가 남긴 `max_trade_notional_krw` 키는 복원 시 무시(모델에 없음), 신 필드는 기본 15로 시작. 무손실.
