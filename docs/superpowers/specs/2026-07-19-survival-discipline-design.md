# 생존 규율 설계 — P1: 손절의 무조건성 + R-기반 사이징

- 날짜: 2026-07-19
- 상태: 설계 승인됨 (사용자 "승인합니다")
- 전제: HEAD `05a20ec`. 전략 검토 리스크/실행 감사(2026-07-19)+배선 지점 정밀 디스커버리 근거. 월요일 개장 전 배포 목표.
- 배경: 손절/익절 자동 실행 기본 OFF(도달=알림/토론만), 일일손실 브레이커가 방어 청산까지 차단하는 역설, 청산 경로 LIMIT 불일치(급락 미체결 갭), 사이징이 손절거리와 무관(두 병렬 공식).

## 0. 결정 레코드 (사용자)
| # | 결정 | 선택 |
|---|------|------|
| D1 | 손절 자동 범위 | **자율 모드만 자동 실행**, HITL=현행(알림/토론) — 게이트의 모드 재판독이 구조적으로 강제 |
| D2 | 익절 | **토론 유지 + 트레일링**: 익절 도달 후 되돌림 시 손절선을 본전+α로 인상(이익 보호), 익절 자동 실행은 OFF 유지 |
| D3 | 게이트 면제 | **리스크 축소만 면제**: SELL/REDUCE는 일일손실 브레이커 스킵(마스터·모드·paper 유지) — 공매도 부재라 SELL=항상 축소 |
| D4 | R 예산 | **0.75%**(계좌 5억 기준 1건당 최대 손실 ₩375만), 전략 합의 조정 바운드 [0.25, 1.5], 기존 캡들과 min() 병용 |

## 1. 실측 확정 사실 (디스커버리 — 구속)
- **스위치 현황**: PM `auto_execute_stop_loss/take_profit=False`(position_manager.py:248-250, 런타임 API 없음 — agent_chat.py:747-756의 config request는 소비 라우트 없는 데드 코드). RiskMonitor `stop_loss_mode/take_profit_mode=USER_APPROVAL`(models.py:245-246, PUT /trading/risk-params로 런타임 변경 가능 trading.py:321-357).
- **⚠️스냅샷 비대칭**: WatchConfig.stop_loss_mode는 진입 시점 1회 스냅샷(risk_monitor.py:161-189, coordinator.py:760/2101/2867에서 생성) — 모드 변경이 기존 포지션 미반영. take_profit_mode는 라이브 판독(risk_monitor.py:506-508) — 대칭화 필요.
- **모드 판독=게이트가 유일 소스**: PM 자동집행 3경로(:1044-1108/1293-1412/1525-1638)와 RiskMonitor AGENT_AUTO(coordinator.py:1034-1081) 전부 check_autonomy 호출, mode_provider가 매 호출 SQLite 재조회(gate.py:73-77) → 스위치 ON+HITL=매번 deny. `/halt` 즉시 반영 자동.
- **⚠️deny 미폴백**: PM은 게이트 deny 시 토론으로 폴백하지 않고 반복 거부만(position_manager.py:1068-1083/1344-1355) — HITL에서 스위치 ON이면 알림/토론 거동이 사라짐 → market_mode 거부 시 토론 폴백 필요.
- **게이트 체인**: 5~7번(coordinator_active/max_positions/notional)은 이미 POSITION_INCREASING_ACTIONS={BUY,ADD} 한정(gate.py:36,305-350). SELL/REDUCE에 걸리는 것은 **4번 daily_loss_breaker뿐**(gate.py:286-302, 액션 분기 이전) — 1파일 수정으로 D3 완성. SELL은 보유 수량 clamp라 항상 축소(coordinator.py:1990, position_manager.py:1327).
- **MARKET 지원 실증**: RiskMonitor 방어 청산이 이미 MARKET 상시 사용(risk_monitor.py:545-565/609-621, P2-4)+전용 테스트 존재. LIMIT 잔존 3경로=_close_position(coordinator.py:1926-1934)/_reduce_position(:2003-2011)/on_trade_approved 메인(:629-638)+리밸런스 SELL(portfolio_agent.py:338-344, price도 미지정).
- **트레일링 재료**: _check_trailing_stop(position_manager.py:851-881)이 highest_price 기반 존재하나 **버그 2건**: stop 직접 대입으로 _stops_sane 미적용+_schedule_persist_stops 미호출(재시작 시 인상분 소실). TAKE_PROFIT_HIT은 의도적 매 틱 refire — 도달 기록은 별도 필드 필요. PositionAction(TRAIL_STOP 등)은 참조 0 데드 코드.
- **사이징 2곳**: (a) 그래프 decision_nodes.py:300-359 — 가용현금×pct, stop_loss가 수량 계산 **이후** 인라인 산출(L348-352) → R 사이징엔 stop 선계산 재배치 필요. (b) portfolio_agent.py:105-299 — equity×max_single_position_pct×risk_factor(3단 버킷), **stop_loss가 이미 인자로 옴**(L53,99 — 미사용) → 소규모 변경.
- **RiskParameters 필드 관례**: STRATEGY_MAPPED_FIELDS(strategy_apply.py:47-53, (lo,hi) 클램프)+GATE_PROTECTED_FIELDS(:56-65 — stop_loss_mode/take_profit_mode 이미 봉인, 유지). 신규 risk_budget_pct는 게이트 미참조라 MAPPED에 (0.25,1.5)로.
- `/halt` 경계: 이미 check_autonomy 통과 후 브로커 호출 진입한 주문은 완주(정상) — "즉시 정지"의 의미 문서화.

## 2. 태스크 설계
### S-1 게이트 리스크 축소 면제
- gate.py: daily_loss_breaker 검사를 `action in POSITION_INCREASING_ACTIONS`일 때만 실행(마스터·모드·paper는 액션 분기 이전 — 자동 유지). 브레이커 발동 중에도 SELL/REDUCE 통과+BUY/ADD 차단 회귀 테스트. 호출자 3곳(injector/ChatCoordinator/PM) 무변경.

### S-2 손절 자동 실행 기본 ON + 모드 폴백
- PM `auto_execute_stop_loss=True`(익절 False 유지). RiskMonitor `stop_loss_mode` 기본 `AGENT_AUTO`(models.py 기본값).
- **스냅샷 대칭화**: _handle_stop_loss가 WatchConfig 스냅샷 대신 라이브 `self.risk_params.stop_loss_mode` 판독(take_profit과 동일 패턴) — 모드/파라미터 변경 즉시 반영. WatchConfig 필드는 하위호환 유지(판독만 전환).
- **HITL 폴백**: PM _execute_close_position/_execute_reduce_position의 게이트 deny 분기에서 `gate.check == "market_mode"`일 때만 기존 토론 트리거 경로로 폴백(1회 래치 유지 — 스팸 방지). 그 외 deny(paper 등)=현행 유지.
- GATE_PROTECTED_FIELDS 봉인 유지(전략 합의가 모드 못 끔 — 기존 테스트 확인).

### S-3 청산 MARKET 통일
- _close_position/_reduce_position/on_trade_approved(SELL·REDUCE 방향만)/리밸런스 SELL의 OrderRequest에 `order_type=OrderType.MARKET`. BUY/ADD는 LIMIT 유지. _reduce→_close 위임 경로 중복 없음(각자 생성).

### S-4 R-기반 사이징
- RiskParameters에 `risk_budget_pct: float = 0.75`(Field ge=0.1 le=3.0 — 하드 바운드는 여유, 전략 클램프가 실질) + STRATEGY_MAPPED_FIELDS에 `(0.25, 1.5)`.
- R 캡: `r_cap_value = equity × risk_budget_pct% ÷ stop_distance_pct` (stop_distance_pct=(entry−stop)/entry). 가드: stop None/entry≤stop/거리<0.5% → R 캡 미적용(기존 사이징 폴백, 로그).
- (b) portfolio_agent: _calculate_max_position_value에 stop_loss 전달, `min(기존 캡, r_cap_value)`.
- (a) 그래프 decision_nodes: stop_loss 산출을 수량 계산 앞으로 재배치(산식 불변 — 순서만) 후 동일 min() 결합. 기존 notional·현금 캡 전부 유지(최솟값 채택).

### S-5 익절 후 트레일링(본전+α)
- MonitoredPosition에 `take_profit_reached_at: Optional[datetime]` — TP 도달 시 1회 기록(refire 이벤트와 분리).
- 도달 후 가격 < TP로 되돌림 시: `new_stop = max(현 stop, entry × (1 + α))`, α=이익폭(TP−entry)의 30% 지점 비율(설정화 `trailing_lock_in_ratio=0.3`). `update_position` 경유(=_stops_sane 검증+영속).
- **기존 트레일링 버그 봉합**: _check_trailing_stop의 직접 대입→update_position 경유(검증+영속) — 재시작 시 인상분 소실 근절.

## 3. 비변경 불변식
- 익절 자동 실행 OFF·HITL 알림/토론 거동(폴백으로 복원)·진입 BUY LIMIT·게이트 마스터/모드/paper 체인·paper 하드코딩·GATE_PROTECTED_FIELDS 봉인·계보 배선(L 아크) 무변경.
- 테스트 실 네트워크·실 DB 금지(isolated_storage_service·tmp 픽스처, 트립와이어 206 불변).

## 4. 리스크
| 리스크 | 완화 |
|--------|------|
| 배포 직후 기존 보유에 자동 손절 발동 | 의도된 동작 — 계보·digest로 자연 실증. 배포 직전 보유·손절가 현황 사용자 보고 |
| MARKET 슬리피지 | 방어 청산 한정(진입 LIMIT 유지) — 미체결 갭보다 우선 |
| R 캡이 수량 0으로 축소 | 최소 1주 미만이면 스킵+로그(기존 관례 확인), 거리<0.5% 가드 |
| HITL 폴백이 토론 폭주 | 기존 쿨다운 30분·1회 래치 유지 |
