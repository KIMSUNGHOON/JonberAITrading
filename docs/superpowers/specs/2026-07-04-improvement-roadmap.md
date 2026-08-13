# JonberAITrading 개선 로드맵 (검증됨)

- **날짜**: 2026-07-04
- **근거**: 8-에이전트 검증·계획·합성 워크플로우(`improvement-roadmap`) — 감사 주장을 **현재 코드로 재검증**(전건 CONFIRMED, 백엔드는 2026-01-08 이후 실질 동결) + 3관점(효율/안전/quick-win) 로드맵 합성
- **관계**: [지능 레이어 스펙](./2026-07-04-intelligence-layer-restructure-design.md)은 이 로드맵의 **Phase 1**이며, 그 앞에 **Phase 0**가 선행함
- **동결 준수**: 실거래(`KIWOOM_IS_MOCK=false`) 및 장중 모의검증은 사용자 명시 요청 전까지 동결 — 로드맵은 이를 트리거하지 않음

---

## 진단 — 핵심 문제 (전건 현재 코드 검증됨)

**1. "에이전트 AI 트레이딩" 주장은 의사결정 계층에서 거짓 (사용자 목표 #2).**
모든 매수/매도 *시그널*은 ~6개 하드코딩 규칙 함수(RSI/PER/PBR threshold)에서 나오고 LLM은 나레이션만 씀. *전략적 행동*은 미사용보다 나쁨 — `decision_nodes.py:181`이 `llm.generate(...)`를 호출한 뒤 `:184`에서 그 결정을 `_signal_to_action_with_position(signal=consensus_signal)`(규칙기반 수치 평균)으로 **덮어씀**. `STRATEGIC_DECISION` 프롬프트는 모델에게 "최종 매매 결정을 내리라"고 지시하는데 코드는 그 답을 버리고 `response`(근거 텍스트)만 보관(`:255`). US(`nodes.py:442`)·coin(`coin_nodes.py:456`) 동일. **메인 그래프 의사결정의 0%가 LLM 것.**

**2. "컨센서스 트레이딩 완성" 주장은 거짓 — 게이트가 없음.**
`consensus_threshold`(0.75)의 비교 사이트가 레포에 **0개**(검증됨). 50/50 투표도 매매됨. 게다가 최종 그룹챗 행동은 모더레이터 산문에서 substring 파싱(`moderator_agent.py:392-410`), 반면 완성된 가중투표 집계기 2개(`get_majority_direction()`/`vote_to_action()`, `models.py:321-400`)는 계산 후 버려짐.

**3. 3중 중복 마켓 스택이 "비효율 구현"의 핵심 (사용자 목표 #1).**
KR/US/coin = 구조적으로 동일한 18-노드 그래프 3개에 걸친 **~6,676 라이브 LOC**, ~55% 공유 상태, 바이트 동일 헬퍼. 모든 시그널/노드/프롬프트/실행 수정이 지금은 **3곳**에 착지. 단일 최대 효율 레버(~3,000+ LOC 회수 가능), 사용자 불만의 직접 타깃.

**4. LLM이 로컬 Ollama 단일 백엔드에 묶여 있음 — 이것이 실제 LLM 의사결정이 안 만들어진 이유.**
단일 개발자 로컬 GPU에서 분석마다 실제 LLM 의사결정은 비용상 불가능했음. Phase 1 스펙이 정확히 이걸 해결: 고볼륨 분석 시그널은 저렴한 deepseek, 전략/리스크 종합은 정액 키리스 Claude opus. **라우터가 #1·#2의 경제적 잠금해제.**

**5. 올바른 Kiwoom 통합은 도달 불가, 도달 가능한 경로는 조용히 실패.**
`approval.py:120`이 맨 `graph.astream(None)`으로 재개하고 `update_state`가 없어 그래프 체크포인트가 `approval_status=None` 유지 → 실제 `execution.py` 노드가 절대 실행 안 됨. 승인 버튼에 실제 연결된 경로(`order_agent.py:360`)는 존재하지 않는 `place_order` 호출 → `AttributeError` → 조용한 거부. 순: Kiwoom 클라이언트가 있으면 **모의에서도 승인을 통한 주문이 전혀 발사 안 됨**.

**6. 확인된 데드코드 6,354 LOC (백엔드 10%), 함정 파일 포함.**
`services/agent_chat/agents.py`(661 LOC)는 `agents/` 패키지에 **import-shadow**됨 — 편집이 조용한 no-op이고, 이전 감사조차 *죽은* 파일의 버그를 인용함. 그 외 `*_old.py` 3개 모놀리스, 빈 `kr_stocks_new.py`. 제거 전엔 모든 편집을 오도함.

**7. 당일-사망 기능 3개 + 안전망 부재.**
coin 분석(100% ImportError), agent-chat 세션상세(투표된 세션마다 500), 전체유니버스 스캐너(조용히 15종목). CI 없음, ~3개 에이전트 테스트가 라이브 Ollama에 붙고 `pytest-timeout` 없음, 커버리지 비활성. `MemorySaver` 전면 사용 → 승인 중 재시작시 대기 매매 고아화. 프론트: WS 클라이언트 4개 분기, 2,035줄 스토어, `Math.random()` US 차트.

---

## 로드맵 (단계 표)

| Phase | 목표 | 공수 | 선행 | 가치 | 생략시 위험 |
|-------|------|------|------|------|-------------|
| **0 — 활주로 청소** | 3 기능수정 + 컨센서스 게이트 + 데드 6.3k LOC 제거 + CI 바닥 + 헬퍼 dedup + 이중마운트 통합 | S–M (3–5일) | 없음 | 최고 가치/공수: 기능 3개 + 안전게이트 1개 당일 복구, 이후 전부의 깨끗한 호출부·가드레일 | 라우터·이후 수정이 shadow/`*_old` 사본에 계속 착지; crypto/scanner/detail 계속 사망; 50/50 투표 여전히 매매 |
| **1 — 지능 레이어 라우터 (스펙)** | 멀티 백엔드 태스크 라우팅(deepseek + 키리스 Claude/Codex CLI + local), 예산가드, 방지전용 시크릿, 파사드 보존 | XL (1.5–2.5주) | P0 | 키스톤: 실제 LLM 의사결정을 감당가능하게 + 단일 목킹 seam; 즉각 스캐너 비용↓ | 로컬 Ollama 잠금; 실제 LLM 의사결정 비용불가; 목 seam 없음; P2/P3 차단 |
| **2 — 결정론적 테스트 하네스** | 라우터 seam 목킹 → 전 에이전트 스위트 오프라인; 커버리지 강제 | S–M (2–3일) | P1 | P3–P6 대형 리팩터의 회귀망; seam 이후엔 거의 공짜 | 고폭발반경 리팩터가 자동 안전망 없이 진행 |
| **3 — 의사결정 계층을 실제 AI로 (#1 주장 정정)** | 3개 전략노드에서 구조화 LLM action+confidence를 실제 소비; 그룹챗을 가중투표 수학으로; 거짓 프롬프트 정정 | M–L (1.5–2.5주) | P1, P2, P0 | 두 거짓 주장을 참으로; substring 파싱 의사결정 표면 삭제 — 최대 정확성 승리 | "AI가 결정" 마케팅 유지하며 규칙이 결정; 정액 opus가 최적 용도로 미사용 |
| **4 — 3중 마켓 스택 통합 (최대 효율 레버)** | 제네릭 그래프 + 마켓별 어댑터; 상태 통합; 동시 분석 | XL (2–3주) | P1, P3, P2 | ~3,000+ LOC 제거; 3×-수정 세금 종식(핵심 불만); LLM/주문/영속성의 단일 seam | 모든 미래 변경이 3중 유지; P3/P5 수정을 마켓마다 영원히 재적용 |
| **5 — 단일 실행경로 + HITL 정확성 (동결-라이브 기반작업)** | 단일 Kiwoom 주문 어댑터; HITL 재개 수정; 챗을 HITL 경유; AGENT_AUTO 게이트 | M–L (1.5–2주) | P4 | 승인→실행이 처음으로 동작; 깨진 주문 중복 2개 삭제; 결국의 라이브 안전 척추 | 승인 버튼 조용한 no-op/거부; 챗이 게이트 없이 매매; 장외 자동청산 무게이트 |
| **6 — 영속성 내구화 (재시작 생존)** | `SqliteCheckpointer` 완성+배선; `TradingState` 영속; 재시작/재개 검증 | M (1–1.5주) | P4, P5 | 재시작이 대기 승인/포지션 고아화 안 함; 기작성 284 LOC 재사용 | 승인 중 재시작시 매매 소실; 포지션/카운터 리로드마다 리셋 |
| **7 — 실시간/WS + 프론트 통합 (라스트마일)** | 통합 레지스트리 위 push; 단일 WS 프리미티브; 스토어 분할; 정직한 US 차트 | L (분할가능) | P4 | WS 구현 7→1; CPU/지연↓; 유지보수 스토어; 가짜 데이터 제거 | 3중-dict 폴링 + 7방 WS 드리프트 지속; 가짜 US 차트가 "실제 분석" 신뢰 훼손 |

---

## 단계별 상세

### Phase 0 — 활주로 청소 (스펙 준비)
**목표**: 라우터가 건드리기 전에 트리를 정직하게 + 호출부 인벤토리를 깨끗하게, 그리고 삭제·리팩터를 가드할 CI 바닥. LLM 불필요 → 즉시 착수.

- **당일 기능수정 3개** (각 ~몇 줄): (a) `analysis_unified.py:86` `coin_graph`→`coin_trading_graph`(crypto 분석 전체 복구); (b) `agent_chat.py:161-162` `v.weight`/`v.weighted_score`(`AgentVote`에 없음) 제거/재계산(그룹챗 히스토리 UI 복구); (c) `KiwoomClient._request`에 `cont_yn`/`next_key` 배선(또는 `extra_headers` 수용)해 `get_stock_list`의 `TypeError`→15종목 폴백 종식(전체 KOSPI/KOSDAQ 스캔 복구).
- **컨센서스 안전 게이트 (~5줄)**: shadow `agents.py` 삭제 후 라이브 `chat_room._make_decision`/모더레이터 경로에 `if consensus_level < session.consensus_threshold: force HOLD/NO_ACTION`.
- **데드코드 6,354 LOC 삭제**: `kr_stock_nodes_old.py`(1941), `kr_stocks_old.py`(1790), `coin_old.py`(1513), import-shadow된 `services/agent_chat/agents.py`(661), 빈 `kr_stocks_new.py`(0), 빈 `agents/subagents/`. **유지**: `sqlite_checkpointer.py`(P6 재사용). **주차(park)**: `parallel_analysis.py` — `kr_stock_nodes/__init__.py:22`/`__all__`에서 제거해 "배선됨" 거짓광고만 중단, 파일은 P4 동시성 참조로 보존.
- **CI 바닥** (전체 하네스 아님): `pytest-timeout`(하드 per-test 가드), ~3개 라이브-Ollama 테스트 마크/스킵, 최소 GitHub Actions(`pytest -m 'not slow'` + `vitest run`), `pytest.ini:31` `--cov` 리포트전용 재활성.
- **dedup 착수금**: 바이트동일 헬퍼 4개(`_signal_to_action`, `_extract_key_factors`, `_extract_bull_case`, `_extract_bear_case`)를 공유 모듈로.
- **v1/legacy 이중마운트 통합**(`main.py:191`/`:266`, 동일 14 라우터 ×2)을 단일 `(router, prefix)` 루프로(프론트 base URL 확인 후).

**종료조건**: coin/scanner/agent-chat-detail 200 반환; 50/50 챗투표 더는 매매 안 함; 백엔드 `wc -l` ~6.3k↓; PR CI green; shadow/`*_old` 없음; `/api/v1`·`/api` 이중마운트 해소.

### Phase 1 — 지능 레이어 라우터 (승인된 스펙) — 키스톤
[별도 스펙 문서](./2026-07-04-intelligence-layer-restructure-design.md) 참조. 1a–1f 스테이징, 빅뱅 금지. `scanner.py:931/1009` 먼저 태그(최대 즉시 비용절감), `GET /api/llm/stats` 추가.
**중요 성질**: 트레이드 루프에 **안전-중립**(나레이션 백엔드만 교체; 시그널/액션은 규칙기반 유지, 주문경로 무변경) → 그래서 정확성 작업을 미루지 않고 Phase 1에 위치 가능.

### Phase 2 — 결정론적 테스트 하네스
Phase 1 seam에서 LLM-라우터 목 픽스처(`conftest.py`)로 전 에이전트 스위트 오프라인화. 스펙의 `test_router`/`test_facade_compat` + `generate_structured` 스키마 테스트 완성. 커버리지를 리포트전용→강제 게이트로.

### Phase 3 — 의사결정 계층을 실제 AI로
- strategic_decision + risk를 opus에서 `generate_structured(DECISION_SCHEMA)`로 태우고 반환 action을 `decision_nodes.py:184`(KR)/`nodes.py:442`(US)/`coin_nodes.py:456`(coin)에서 `_signal_to_action(consensus)` 대신 **소비**. 규칙 시그널은 사전확률/정합성 경계로 유지(결정자 아님).
- `prompts.py:123/239/370`의 프롬프트-vs-행동 거짓 정정.
- 그룹챗: 최종 action을 `get_majority_direction()`+`vote_to_action()`에서 도출(현재 계산 후 폐기), `_parse_vote`/`_parse_confidence` substring/regex를 구조화 출력으로 교체, 분석가 4명은 저렴한 deepseek·모더레이터는 opus.
- (선택) ~6개 규칙 시그널 함수를 deepseek 구조화 출력 시그널로 승격(규칙 폴백).
**통합 전에 하는 이유**: 3개 스택이 아직 존재할 때 마켓별로 하면 각 마켓 독립 검증 가능; P4가 *이미 올바른* 유사 노드 3개를 병합 — 먼저 병합 후 의미 변경보다 저위험.

### Phase 4 — 3중 마켓 스택 통합
상태 통합(`state.py`/`kr_stock_state.py`/`coin_state.py`, 각 230–256 동일줄)→단일 제네릭 `TradingState`+마켓필드; 파라메트릭 그래프 빌더 1개(각 스택 18개 동일 add_node/add_edge); 라우터 세마포어로 동시 분석 편입(주차한 `parallel_analysis.py` 패턴, 지연 개선); 스트레치: 바이트병렬 `coin/`+`kr_stocks/` 라우트 패키지(~3,582 LOC) 통합.

### Phase 5 — 단일 실행경로 + HITL 정확성 (동결-라이브 기반작업)
`execution.py`의 올바른 `place_buy_order`/`place_sell_order`+`OrderResponse` 재사용하는 단일 주문 어댑터; 깨진 코디네이터 분기(`order_agent.py:360`)·깨진 수동 `kr_stocks/orders.py` 리다이렉트. HITL 재개 수정: `astream(None)` 전에 `graph.update_state(config, {approval_status:'approved', ...})`; `approval.py`의 no-op 이중작업 제거. agent-chat 결정을 공유 HITL 큐 경유(`on_trade_approved` 우회 차단). RiskMonitor `AGENT_AUTO` 청산을 장시간+확인 뒤로 게이트.

### Phase 6 — 영속성 내구화
`SqliteCheckpointer.alist`/`aput_writes` 완성(현재 스텁 — `put_writes`가 맨 `pass`; LangGraph는 올바른 interrupt/resume에 둘 다 필요), P4 단일 그래프 빌더로 1회 배선. `TradingState`를 `storage_service.save_checkpoint`/`get_checkpoint`로 영속·부팅시 로드. 승인-인터럽트→재시작→재개-실행 종단 검증.

### Phase 7 — 실시간/WS + 프론트 통합
`/ws/session`의 3-dict 0.3s 바쁜폴링을 통합 레지스트리 위 이벤트 push로; 백엔드 `ConnectionManager` 3개·프론트 WS 추상 ~4개를 단일 재연결/핑 프리미티브로; agent-chat WS를 코디네이터 이벤트 브로드캐스트로 배선하거나 연결된 no-op(333 LOC) 삭제; 2,035줄 Zustand 스토어를 피처 슬라이스로; 실제 US 캔들 소스 배선 또는 `Math.random()` 차트를 데모로 명시; (선택) 12-값 `currentView` 사다리를 실제 라우터로.

---

## 시퀀싱 근거 (관점 이견 해소)

**척추(3관점 합의)**: 저렴한 준비 단계(기능수정+데드코드 제거+CI)가 라우터에 선행 → 호출부 인벤토리 깨끗·리팩터 가드; 라우터 = Phase 1; 테스트망이 위험 리팩터에 선행; "AI 실체화"는 라우터 의존; 스택 통합은 최대 레버지만 최고 위험이라 라우터+테스트 뒤; 실시간/프론트 최후.

**해소된 이견 4가지**:
1. **CI 배치 — 절충**: 효율은 라우터 뒤(seam 후 목 거의 공짜), 안전/quick-win은 최우선. → **분할**: Phase 0에 저렴한 CI *바닥*(P0 삭제+P1 리팩터 가드), *전체 결정론적 목 하네스*는 Phase 2(거의 공짜인 지점).
2. **AI실체화 vs 실행정확성 — 최대 이견**: 안전우선은 실행/HITL을 라우터 직후(AI실체화 전)에 두려 함. → 효율/quick-win 쪽으로 해소(AI실체화 먼저, 전체 실행작업은 통합 후): (a) 사용자 우선순위가 효율·AI주장 정확성이고 라이브는 동결이라 실행준비가 지금 아무것도 안 막음; (b) AI실체화는 Phase 1 정액 opus가 산 보상; (c) 전체 실행수정은 통합으로 주문경로 1개가 되면 더 저렴. 안전의 정당한 우려는 (i) ~5줄 컨센서스 게이트를 Phase 0에, (ii) 단일-사이트 실행수정 2개(HITL 재개 + 코디네이터 주문경로)를 **Phase 0 당김 옵션**으로 존중.
3. **통합 타이밍**: 효율=P4(AI실체화 후·실행 전), 안전=최후, quick-win=최후. → 효율 슬롯 채택: Phase 3 후(이미 올바른 결정노드 3개 병합, 저위험) + 전체 실행/영속성 전(그것들을 통합 스택에서 1회 수정). 안전의 "통합 최후"는 거부 — 미루면 모든 중간 수정이 3중화(사용자가 제거하려는 바로 그 비효율).
4. **소소**: 컨센서스 게이트는 Phase 0(5줄, 마퀴 주장 복구, 대기 이유 없음). `parallel_analysis.py`는 주차(삭제도 유지-as-wired도 아님): `__all__`에서 제거해 거짓배선 중단, 파일은 P4 참조로 보존.

---

## 최고 ROI quick-win (Phase 0, 몇 시간)

1. **coin 분석**: `analysis_unified.py:86` `agents.graph.coin_graph`→`coin_trading_graph`(1줄; `get_coin_trading_graph`는 `coin_trading_graph.py:172`에 이미 export) — crypto 분석 100% 복구, 무위험.
2. **agent-chat 세션상세**: `agent_chat.py:161-162` `v.weight`/`v.weighted_score`(`AgentVote`에 없음, `models.py:110-123`) 제거/재계산 — 투표된 세션 500 중단.
3. **전체유니버스 스캐너**: `KiwoomClient._request`에 `cont_yn`/`next_key` 배선 — `client.py:1118`의 `TypeError`→15종목 폴백 종식.
4. **컨센서스 게이트(~5줄)**: 라이브 `chat_room`/모더레이터 경로에 threshold 비교 추가.
5. **데드 6,354 LOC 삭제**: 함정 파일 제거(`sqlite_checkpointer.py` 유지, `parallel_analysis.py` 주차).
6. **CI 바닥(오후 반나절)**: `pytest-timeout`, 라이브-Ollama 테스트 스킵, 최소 GH Actions, `--cov` 리포트전용.
7. **v1/legacy 이중마운트 통합**(`main.py:191`/`:266`) — ~78줄 제거, OpenAPI/WS 표면 절반.

---

## 미해결 결정 (사용자)

1. **정직한 승인 버튼 조기화?** — 단일-사이트 실행수정 2개(HITL 재개 `update_state`; 코디네이터 `place_order`→`place_buy_order/place_sell_order`)를 Phase 0에 독립 S 패치로 당겨 모의에서 승인→실행 지금 동작시킬지, Phase 5로 둘지. 3중화 아니라 조기 당김 저렴.
2. **프론트 base URL 확인**: `/api`(not `/api/v1`) 사용 + `/api/v1` 외부 소비자 없음 확인 후 이중마운트 통합. 아니면 둘 다 유지.
3. **예산 가드 기본**: deepseek 분석 트래픽에 ~$5/일 상한 수용 가능? (정액 Claude/Codex CLI가 고스테이크 담당)
4. **local Ollama**: 클라우드+CLI 이후 폴백 체인에 남길지 완전 은퇴할지 — *이미 "클라우드 우선(은퇴)" 확정*.
5. **US 차트(P7)**: 실제 캔들 소스 배선(공급자/키?) 또는 `Math.random()` 데모 명시.
6. **프론트 라우터+스토어 분할(P7)**: 단일개발자 데모에 할 가치 있는지, 무기한 연기할지.
7. **영속성 타이밍**: 재시작 내구화를 P6로 미룰지, 재시작이 지금 고통이면 통합 독립으로 조기화할지.
8. **Phase 3 깊이**: 전략/리스크 단계만 구조화 LLM action 소비(저렴·저위험), 아니면 ~6개 분석가 규칙 시그널도 deepseek 구조화로 승격(더 완전한 'AI', 파서검증 더 필요).
