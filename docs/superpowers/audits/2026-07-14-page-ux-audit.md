# Position / Agent Group Chat 페이지 UX 실사 (2026-07-14)

> 3-에이전트 READ-ONLY 실사 + 종합 재검증. HEAD 58cf272 기준.

근거 교차검증 완료. 핵심 사실이 모두 온디스크 코드로 확인됐다(3중 코디네이터 컨트롤: AgentChatDashboard:90/103, DebatePanel:181, TradingDashboard:222/230 / 수동 토론은 CommandPalette:60 단 1곳 / PositionsPanel은 `p.stop_loss` 렌더인데 KR은 하드코딩 None / HoldingColumn만 /operations로 SL/TP 보강 trading.py:1348). 아래가 최종 설계안이다.

---

# 자율 매매 앱 — Position / Agent Group Chat 페이지 UI/UX 진단 + 개선 설계안

> 전제: 이 문서는 **설계 제안**이며 승인 전 구현 금지. 각 개선은 독립 실행 가능한 단위(P-Unit / A-Unit)로 쪼갰다. 근거는 전부 현재 HEAD `58cf272` 온디스크 코드 인용(실사자 3인 결과를 재검증한 뒤 확정).

---

## A. Position 페이지 진단 + 개선안

### A-1. 현재 레이아웃 (실제 구조)

`PositionsPage.tsx`는 **좌우 2단이 아니라, 위(Crypto)/아래(KR) 두 섹션을 세로로 쌓고, 각 섹션 내부에서만 좌우 2열**을 쓴다.

```
┌─ Crypto Positions (upbit 설정 시) ────────────────┐
│  [CoinAccountBalance]   |   [CoinPositionPanel]   │  ← 좌: 실계좌 원장 / 우: 앱 추적 포지션
│  [────── CoinOpenOrders (전체폭) ──────]           │
├─ Korean Stock Positions (kiwoom 설정 시) ─────────┤
│  [KiwoomAccountBalance] |  [KiwoomPositionPanel]  │  ← 좌: 계좌잔고+"보유 종목" 미니리스트 / 우: "보유 종목" 풀카드
│  [────── KiwoomOpenOrders (전체폭) ─────]          │
└───────────────────────────────────────────────────┘
```
근거: `PositionsPage.tsx:57-82` (섹션+그리드), `App.tsx`의 `/positions` 라우트.

사용자가 지적한 **"오른편에 또 있는 보유종목 layout"** = KR 섹션 우측 `KiwoomPositionPanel`(제목 "보유 종목"). 그리고 **좌측 `KiwoomAccountBalance` 카드 안에도** 동일 제목의 "보유 종목" 미니 리스트가 있다(`KiwoomAccountBalance.tsx:216-236`, 종목명·수량·손익률만). 즉 한 화면 한 섹션 안에 "보유 종목"이라는 이름의 표시가 **2개** 있다.

### A-2. 오른편이 비어 있는 정확한 정체 + 근본 원인

**정체**: 우측 `KiwoomPositionPanel`은 `getKRStockPositions()` → `GET /kr_stocks/positions`를 소스로 쓴다.

**근본 원인은 코드 결함이 아니라 "실행 중 프로세스 노후(stale process)" 런타임 아티팩트다.** 온디스크 `kr_stocks/positions.py`는 이미 고쳐져 있다:
- `get_positions()`가 `get_shared_kiwoom_client_async().get_account_balance()`(kt00004)를 쓴다(`positions.py:51-52`) — 좌측 `GET /kr_stocks/accounts`와 **동일한 브로커 호출**. 코드 주석(`positions.py:37-41`)이 과거 버그를 명시: 예전엔 `storage.get_kr_stock_positions()`(존재한 적 없는 메서드)를 호출→AttributeError를 조용히 삼켜 **항상 빈 배열**을 반환했다.
- 이 수정은 커밋 `91d9438`(KR 포지션 소스=브로커 balance 단일화)에서 들어왔고, `git diff HEAD -- positions.py`는 빈 diff(온디스크=HEAD, 조작 없음).

따라서 우측이 비는 건 **`--reload` 없이 뜬 백엔드 프로세스가 `91d9438` 이전 구코드를 메모리에 물고 있기 때문**이다(실사자 라이브 재현: 같은 캐시 윈도우 내 연속 curl에서 accounts는 2종목, positions는 `[]`). **백엔드를 재시작하면 우측 패널은 즉시 좌측과 같은 보유종목으로 채워진다.**

**단, 재시작해도 남는 진짜 문제 2가지:**
1. **중복이 드러난다**: 우측이 채워지면 좌측 미니리스트와 **동일한 브로커 보유종목을 두 번** 그린다(빈 게 아니라 중복이었던 것).
2. **KR SL/TP는 구조적으로 항상 대시(—)**: `positions.py:91-92`가 `stop_loss=None, take_profit=None` 하드코딩. 그래서 우측 카드/대시보드 `PositionsPanel` 모두 KR 손절·익절을 절대 못 보여준다(뒤 A-4·C 참고).

### A-3. 좌/우 중복 여부 판정 (시장별로 다름)

| 섹션 | 좌 카드 | 우 카드 | 판정 |
|---|---|---|---|
| **KR** | `KiwoomAccountBalance` → `/kr_stocks/accounts`(kt00004) + 자체 "보유 종목" 미니리스트 | `KiwoomPositionPanel` → `/kr_stocks/positions`(kt00004) | **표현 중복** — 시장이 다른 게 아니라 **같은 kt00004 브로커 보유종목을 필드 수만 다르게 두 번**(좌=종목/수량/손익률, 우=+현재가/평가손익/SL·TP/청산버튼). |
| **Coin** | `CoinAccountBalance` → `/coin/accounts`(업비트 실계좌 원장 잔고) | `CoinPositionPanel` → `/coin/positions`(coin_positions SQLite, 앱 추적 진입가/SL/TP) | **중복 아님(정상 분리)** — 좌=원장 잔고, 우=앱 자체 추적 레코드로 의미가 다름. 단 라벨에 이 차이가 안 드러나 오해를 부름. |

즉 **KR만 진짜 중복**이고, Coin은 데이터가 다른데 라벨이 같아 오해를 준다.

### A-4. 메인 퍼널 PIPELINE '보유' 컬럼과의 중복 판정

같은 "KR 보유종목"을 그리는 곳이 앱에 **4곳**이고, 그중 **SL/TP를 제대로 보여주는 건 퍼널 1곳뿐**이다:

| # | 위치 | 소스 | SL/TP | 액션 |
|---|---|---|---|---|
| 1 | 대시보드 퍼널 PIPELINE `HoldingColumn` | `useOperations()` → `/operations`(공유폴링). trading.py:1344-1398이 `coordinator.state.positions`→(폴백)agent-chat PositionManager로 SL/TP **보강** | **표시됨** (`OperationsPanel.tsx:457`) | 읽기 요약, 클릭 시 navigate('/positions') |
| 2 | 대시보드 `PositionsPanel` 타일 | `getKRStockPositions()`(독립 10s) | KR은 항상 대시(소스가 None 하드코딩) | 인라인 STOP/TAKE 편집+청산 |
| 3 | **/positions 페이지** `KiwoomPositionPanel` | `getKRStockPositions()`(또 독립 10s) | 항상 대시 | 청산 |
| 4 | /agent-chat `PositionMonitor` | agent-chat PositionManager(별도 소스, 영문 라벨) | 별도 필드 | 없음 |

**판정: /positions의 우측 보유(#3)는 퍼널 PIPELINE 보유(#1)의 부분집합**이다(같은 브로커 데이터, SL/TP는 오히려 #1이 더 정확, 액션은 #1이 딥링크로 #3을 가리킴). 설계문서 §Phase2가 이미 `레거시 /positions KiwoomPositionPanel/CoinPositionPanel: 대시보드 PositionsPanel 부분집합 → 삭제 후보(KR은 P0-a 선행)`로 지목했고, 그 선행조건 P0-a(positions.py 소스 통일)는 **완료**됐는데 삭제만 미실행(Task 8 체크박스 미체크, 코드에 컴포넌트 잔존).

> **주의(실제 회귀)**: `PositionsPanel`(#2)의 인라인 STOP/TAKE 저장은 `PUT /trading/positions/{ticker}/stop-loss`→`risk_monitor`에 실제로 쓰이지만(`trading.py:402`, `source=risk_monitor`), 재조회 소스 `/kr_stocks/positions`는 risk_monitor를 안 읽고 None을 반환 → **저장 성공 후에도 칸이 다시 대시로 돌아가** "저장이 씹혔다"로 보인다. #2/#3의 KR SL/TP 편집은 구조적으로 무의미하다.

### A-5. 개선안 (대안 + 추천 + 삭제 후보)

**즉시 봉합(코드 아님, 운영):** `A-Unit 0` — 백엔드 재시작으로 구프로세스 제거 → `GET /kr_stocks/positions`가 실제 kt00004를 반환하는지 확인. 이걸 안 하면 아래 어떤 UI 개선도 "여전히 빈 우측"으로 오인된다. (재시작 시 R5-P1 영속으로 코디네이터 상태 복원됨.)

이후 3개 대안:

**대안 1 — 최소 봉합(페이지 유지, 중복만 제거)**
- `A-Unit 1a`: `KiwoomAccountBalance`의 "보유 종목" 미니리스트(216-236) 제거 → 좌측은 **현금·평가액 계좌 요약 전용**으로 순화. 헤더를 "계좌 요약"으로 명시.
- `A-Unit 1b`: 우측 `KiwoomPositionPanel`을 유일 보유종목 표면으로 남기고 헤더 "보유 종목" 유지.
- Coin도 좌="계좌 잔고(원장)" / 우="추적 포지션(SL/TP)" 라벨 위계만 부여.
- 트레이드오프: 빠르고 회귀 적음. 하지만 KR SL/TP는 여전히 대시(소스 미변경), 퍼널과의 4중 중복은 그대로.

**대안 2 — 단일 소스 통일(추천)**
- `A-Unit 2a`: 좌측 미니리스트 제거(1a와 동일).
- `A-Unit 2b`: 우측 보유종목 데이터 소스를 **퍼널과 동일한 `/operations` holding**으로 전환(또는 `KiwoomPositionPanel`을 `HoldingColumn` 재사용으로 대체) → SL/TP가 실제로 표시되고, 퍼널·페이지가 **단일 진실**이 되어 절대 안 갈린다. STOP/TAKE 편집도 `/operations` 경로(risk_monitor)와 재조회가 일치.
- `A-Unit 2c`: /positions는 **퍼널이 안 가진 것**(현금/계좌잔고 요약 + 미체결주문 상세)을 담당하는 "전체화면 상세 뷰"로 역할 재정의.
- 트레이드오프: 2b가 컴포넌트 소스 교체라 대안1보다 작업 큼. 그러나 SL/TP 회귀·4중 중복을 근본 해소하고 P2 Task 8 방향과 정합.

**대안 3 — 라우트 흡수(가장 공격적)**
- `/positions` 라우트를 nav에서 내리고 퍼널 PIPELINE으로 흡수. `KiwoomPositionPanel`/`CoinPositionPanel`/미니리스트 삭제.
- 트레이드오프: 최대 단순화지만 계좌 현금 요약·미체결 상세 전용면을 잃음(퍼널 `PendingBuyColumn`이 미체결을 일부 대체하나 현금/계좌평가 요약은 없음). 단독 운영자가 "내 계좌 잔고 한눈에"를 잃는 손실이 큼.

**▶ 추천: 대안 2.** 이유 — (1) 사용자 불만("두 개의 보유, 하나는 빔")을 좌측 미니리스트 제거로 직접 해소, (2) SL/TP 항상-대시라는 실제 회귀를 단일 소스로 봉합, (3) 퍼널이 못 가진 계좌요약/미체결을 페이지에 남겨 역할이 명확해짐, (4) 설계문서 Task 8이 이미 그린 방향.

**삭제 후보(대안 2 채택 시):**
- `KiwoomAccountBalance.tsx:216-236`의 "보유 종목" 서브리스트(계좌 요약만 남김).
- 우측 `KiwoomPositionPanel`의 `/kr_stocks/positions` 독립 폴링(→ `/operations` 소스로 대체).
- (선택) 대시보드 `PositionsPanel` 타일의 KR STOP/TAKE 편집 — 소스가 None인 한 무의미하므로 소스 통일 전까지 비활성 표기 권장.

---

## B. Agent Group Chat 페이지 진단 + 개선안

### B-1. 현재 구조

한 페이지가 **selectedSessionId 유무로 두 화면을 통째로 교체(full-swap)**한다.

- **상태 A (목록, `selectedSessionId===null`)**: 세로 스택 — ① 헤더 ② 에러배너 ③ Status Card(회색/녹색 점 + "Coordinator Running/Stopped" + Start/Stop + gear config + 3열 통계 Active/Total/Interval) ④ Active Discussions(0건이면 섹션 자체 사라짐, `AgentChatDashboard.tsx:269`) ⑤ 메인 그리드(좌 2/3 Recent Sessions · 우 1/3 PositionMonitor).
- **상태 B (뷰어, `selectedSessionId!==null`)**: `AgentChatDashboard.tsx:121-128`이 상태 A를 **통째로 걷어내고** `ChatSessionViewer`만 렌더 — ConsensusTicket(ACTION/신뢰도/ENTRY·STOP·TAKE) + VoteBlotter(투표표) + Discussion(말풍선). 상태 A↔B를 잇는 유일 단서는 좌상단 작은 "← Back".

### B-2. 난해함의 구조적 원인 (4가지가 겹침)

1. **세션 선택 = 전체 페이지 스왑**(`:121-128`). list-then-detail의 좌/우 분할이 아니라 완전 교체라, 앱의 다른 화면(퍼널 공유컬럼·/trading 관제)과 **네비게이션 문법이 이 페이지만 다르다**. "지금 어디 있고 어떻게 돌아가나"의 단서가 "← Back" 텍스트 하나.
2. **주 CTA 명명-동작 불일치**. Status Card "Start"(`:189`)·DebatePanel "토론 시작"(`:181`)은 **"이 종목을 지금 토론시켜라"가 아니라 "워치리스트 5분 주기 자동 모니터링 스케줄러를 켜라"**(coordinator.start). 누르면 즉시 토론이 뜰 거라 기대하지만, 기회 감지 조건 충족 종목이 없으면 몇 분이 지나도 화면 무변화.
3. **자동 트리거 로직이 불가시**. 5분 주기 + 종목별 재토론 쿨다운 + 기회 감지 휴리스틱 3겹 숨은 조건 중 아무것도 페이지에 노출 안 됨. 백엔드 `CoordinatorStatusResponse.last_check_at`(마지막 tick 시각, 루프 생존 판별 필드)가 있는데 **이 페이지는 렌더하지 않는다**(오직 전역 상태바 `LoopLivenessChip`만 소비). → "왜 지금 세션이 안 생기나"를 페이지 안에서 진단 불가.
4. **죽은 영역·부재 액션**:
   - Active Discussions가 0건이면 섹션째 사라져 "왜 없는지/다음 점검 언제"를 설명 안 함(`:269`).
   - `PositionMonitor`는 coordinator.start 전엔 `is_running:false, count:0` 고정 → "No positions / **Add positions** to start monitoring"만 뜨는데, **"Add positions" UI가 앱 전체에 없다**(`addAgentChatPosition` 등 호출부 0건). 안내 문구가 실동작(코디네이터 Start)과 다른 말을 하는 오도성 빈 상태.
   - EventItem "Discussion Required" 배지는 클릭 불가(onClick 없음) — 다음 행동이 UI에 없음.
   - **이 페이지에는 특정 종목을 골라 토론을 시작하는 입력창/버튼이 없다.** 수동 토론(`startAgentChatDiscussion`)은 오직 ⌘K CommandPalette(`:60`)에서만 호출 — /agent-chat과 무연결.

> 배선 자체는 견고함(더미 아님): Start/Stop·세션 리스트·`useAgentChatWebSocket`의 실시간 message/vote/decision push 모두 실백엔드 싱글턴에 연결됨. **문제는 배선이 아니라 정보 위계·명명·불가시 트리거.**

### B-3. 대시보드 DebatePanel과의 역할 분담 + 3중 컨트롤

- **의도된 계층(정상)**: DebatePanel(대시보드) = "최신 세션 1개의 4-애널리스트 투표+합의% 요약카드", /agent-chat = "전체 세션 목록 + 상세 뷰어". 이건 요약↔상세로 역할 분담이 맞다.
- **문제(감사 안 된 3중화)**: 코디네이터 **on/off를 켤 수 있는 UI가 3곳**에 흩어져 각각 다른 라벨·파라미터로 동일 `startAgentChat/stopAgentChat`를 호출:
  - `AgentChatDashboard.tsx:90/103` — Start(config 포함)/Stop
  - `DebatePanel.tsx:181` — "토론 시작"(Start만, config 없음)
  - `TradingDashboard.tsx:222/230` — "결정 계층" Start/Stop
  → 사용자가 "방금 어디서 켰는지", "다른 화면 버튼도 같은 스위치인지"를 알 수 없다.
- **딥링크 단절**: DebatePanel "세션 보기 →"는 `navigate('/agent-chat')`만 호출(세션 ID 미전달) → 방금 보던 활성 토론으로 안 가고 목록 첫 화면으로 떨어짐.

### B-4. 개선안 (대안 + 추천)

핵심 목표: 사용자가 **"토론이 지금 무슨 상태인지 / 뭘 클릭해야 하는지"**를 즉시 알게. 세션 리스트→토론 뷰→결정 흐름을 명확히.

**대안 1 — 제자리 재구조(단일 페이지 유지)**
- `B-Unit 1a`: full-swap을 **마스터-디테일**로 — 좌 세션 리스트 상시 유지 + 우 상세(선택 시). 또는 최소한 상태 B 상단에 세션 컨텍스트 브레드크럼(종목/상태/← 목록).
- `B-Unit 1b`: **명명 정정** — "Start" → "자동 모니터링 시작 (5분 주기)", 상태 A 상단에 "다음 점검까지 mm:ss" + `last_check_at` 렌더(루프 생존 가시화).
- `B-Unit 1c`: **페이지 내 수동 토론 입력** 추가 — 종목 입력 → `startAgentChatDiscussion` 배선(현재 ⌘K에만 있는 기능을 페이지로). "지금 이 종목 토론" 기대를 실제로 충족.
- `B-Unit 1d`: Active Discussions 0건 시 섹션 유지 + "다음 점검 mm:ss · 조건 충족 종목 없음" 설명. PositionMonitor 빈 상태 문구를 실동작("코디네이터 시작 시 계좌에서 자동 동기화")과 일치시키고 존재하지 않는 "Add positions" 문구 제거. EventItem "Discussion Required" 클릭 시 해당 세션 열기 배선.
- 트레이드오프: 페이지 구조 대수술 아님, 회귀 적음. 3중 컨트롤은 미해결.

**대안 2 — 2-모드 분리(관제 vs 기록)**
- 페이지를 명시적으로 두 구획: (a) **"자동 토론 관제"**(on/off·주기·last_check·active count) (b) **"토론 기록/뷰어"**(세션 리스트→상세). 라벨로 자동화 제어 vs 대화 열람을 분리.
- 트레이드오프: 개념 명확. 다만 여전히 세 화면 중 하나이고, on/off SSOT 문제는 별도.

**대안 3 — 단일 컨트롤 SSOT + 페이지 역할 고정(추천, 대안1을 포함)**
- **on/off를 한 곳으로**: `/agent-chat` Status Card를 코디네이터 제어의 **권위 소스(config 포함)**로 지정. `DebatePanel`·`TradingDashboard`의 brain 버튼은 **읽기전용 상태칩 + /agent-chat 딥링크**로 강등(동일 전역 스위치를 3곳에서 쓰는 혼란 제거). ※ /trading을 SSOT로 둘 수도 있으나, 사용자가 혼란을 느끼는 화면이 /agent-chat이고 라벨 의미가 일치하므로 여기를 홈으로 추천.
- 여기에 **대안 1의 1a~1d 전부 포함**(마스터-디테일 + 명명 정정 + last_check 가시화 + 페이지 내 수동 토론 + 빈 상태 정직화).
- `B-Unit 3e`: DebatePanel "세션 보기 →"에 **세션 ID 전달 딥링크**(`/agent-chat?session=…` 또는 상태 전달)로 보던 토론으로 직행.
- 트레이드오프: 대안 중 가장 손이 많이 가나(3중 컨트롤 강등 + 페이지 재구조), 4가지 구조적 원인을 모두 해소하고 IA 일관성(다른 화면과 같은 마스터-디테일 문법)까지 회복. DebatePanel/TradingDashboard 소폭 수정 필요(회귀는 status-only 강등이라 낮음).

**▶ 추천: 대안 3.** B-2의 4원인 + 3중 컨트롤 + 딥링크 단절을 한 번에 정리하되, 실제 코드 변경은 대부분 대안 1(제자리 재구조)이고 여기에 "다른 두 화면의 버튼을 상태칩으로 낮추는" 작은 작업이 얹히는 구조라 위험 대비 효과가 가장 크다.

---

## C. 우선순위·리스크

### C-1. 상대 우선순위 + 먼저 고쳐야 할 배선

1. **[최우선·즉시·비코드] `A-Unit 0` 백엔드 재시작.** Position 우측이 비는 **실제 원인은 구프로세스**다(코드는 이미 정상). 재시작 없이는 모든 UI 개선이 "여전히 빈 우측"으로 오인된다. → **빈 영역의 근본은 여기서 봉합.**
2. **[높음] Position 중복 제거(A 대안 2, 특히 A-Unit 1a/2a 좌측 미니리스트 제거).** 사용자가 명시적으로 불편을 겪는 중복이고 회귀 위험 낮음(표시 제거 위주).
3. **[높음] Agent Chat 명명·가시화·수동 토론(B-Unit 1b/1c/1d).** 사용자가 "구조를 이해 못 함"이라 답답함이 큰데, 이 세 개는 구조 대수술 없이 즉시 체감 개선.
4. **[중간] Agent Chat 마스터-디테일 + 3중 컨트롤 정리(B-Unit 1a/3e + 컨트롤 강등).** 구조 개선 본체, 다른 화면을 건드려 회귀면이 조금 넓음.
5. **[중간] Position SSOT 통일(A-Unit 2b, SL/TP 회귀 봉합).** 소스 교체라 검증 필요.

> **Position vs Agent Chat 상대 우선순위**: Position은 "재시작 1회 + 미니리스트 제거"로 **빠르게 큰 만족**(불만이 구체적·국소적). Agent Chat은 개선 효과는 크나 작업량·회귀면이 더 큼. → **Position 먼저(A-Unit 0→1a), Agent Chat은 저비용 항목(B-1b/1c/1d)부터 → 구조 재편(3)은 별도 승인 단위로.**

### C-2. 각 개선이 건드리는 핵심 파일 · 회귀 위험

| 단위 | 핵심 파일 | 회귀 위험 |
|---|---|---|
| A-Unit 0 (재시작) | — (운영) | 없음. 단 R5-P1 영속 복원 확인 필요(포지션/스탑) |
| A-Unit 1a/2a (미니리스트 제거) | `KiwoomAccountBalance.tsx:216-236` | 낮음(표시 제거). 계좌요약 카드 회귀만 확인 |
| A-Unit 2b (SSOT 통일) | `KiwoomPositionPanel.tsx`, `PositionsPage.tsx`, (소스)`/operations`·`trading.py:1344-1398` | 중간 — 폴링/필드 매핑 변경, 청산 버튼 경로 유지 확인 |
| B-Unit 1b/1d (명명·가시화) | `AgentChatDashboard.tsx:154-266,269`, `PositionMonitor.tsx` | 낮음(문구·필드 추가) |
| B-Unit 1c (수동 토론) | `AgentChatDashboard.tsx`, `client.ts`(`startAgentChatDiscussion` 재사용) | 낮음(기존 API 재사용) |
| B-Unit 1a/3e + 컨트롤 강등 | `AgentChatDashboard.tsx:121-128`, `DebatePanel.tsx:181,198`, `TradingDashboard.tsx:222-230` | 중간 — 3개 파일 교차, 테스트 있음(`DebatePanel.test.tsx:149`가 "토론 시작→startAgentChat" 계약을 검증 → 강등 시 테스트 수정 필요) |

**먼저 고쳐야 할 "배선"의 정답**: 코드 배선이 아니라 **런타임 프로세스**(A-Unit 0). 그다음이 표시 중복 제거. SL/TP 소스 통일(A-2b)과 3중 컨트롤 강등은 배선 변경이라 뒤에.

### C-3. 최근 P2 퍼널 통합과의 정합

- **Position은 "퍼널로 흡수 방향"이 P2 설계와 정합**하나, **완전 라우트 폐기는 비추천**. 설계문서 §Phase2 Task 8이 `레거시 /positions Kiwoom/CoinPositionPanel = 대시보드 부분집합 → 삭제 후보`로 이미 지목했고 선행 P0-a는 완료. 따라서 **레거시 보유 패널의 중복 표현은 제거/단일소스화(A 대안 2)하되, 퍼널이 안 가진 계좌현금 요약·미체결 상세는 /positions에 남긴다**(대안 3 라우트 폐기가 아닌 대안 2). → 4중 중복(#1~#4)을 퍼널 소스(#1) 단일로 수렴시키는 게 P2의 미완 마무리와 일치.
- **Agent Chat은 "페이지 유지"가 정합**. DebatePanel(요약)↔/agent-chat(상세)은 P2가 의도한 요약↔상세 계층이라 병합 대상 아님. 다만 **P2가 감사하지 않은 잔여물** 3가지 — (a) 3중 코디네이터 컨트롤, (b) no-op 'Watchlist' nav(→'/'로 가나 화면 무변화, `nav.ts:39` query param을 소비하는 곳이 nav 자기자신뿐), (c) 데스크톱 nav 9항목 vs 모바일 `Sidebar.tsx` 8항목(watchlist 부재) 불일치 — 는 이번 Agent Chat 재편(B 대안 3)과 함께 정리하면 IA 일관성이 붙는다. (b)(c)는 본 과제 범위 밖이나, 같은 "관제 표면 중복/라벨-목적지 불일치" 뿌리라 별도 단위로 기록해 둘 가치가 있음.

---

### 부록 — 핵심 근거 파일 (절대경로)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/pages/PositionsPage.tsx:57-82` (레이아웃)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/kiwoom/KiwoomAccountBalance.tsx:216-236` (좌측 중복 보유 미니리스트)
- `/Users/sunghoonk/Workspaces/JonberAITrading/backend/app/api/routes/kr_stocks/positions.py:37-52,91-92` (positions 소스 통일 완료 + SL/TP None 하드코딩)
- `/Users/sunghoonk/Workspaces/JonberAITrading/backend/app/api/routes/trading.py:384-441,1344-1398` (SL/TP 편집 경로 vs /operations holding 보강 — 소스 불일치 회귀)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/terminal/panels/OperationsPanel.tsx:431-457` (HoldingColumn = SL/TP 표시하는 유일 표면)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/terminal/panels/PositionsPanel.tsx:79-80,181,206` (KR SL/TP 대시 + 저장 후 되돌아감 회귀)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/agent-chat/AgentChatDashboard.tsx:121-128,189,269` (full-swap · "Start" 명명 · Active Discussions 조건부)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/terminal/panels/DebatePanel.tsx:181,198` / `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/trading/TradingDashboard.tsx:222,230` (3중 코디네이터 컨트롤)
- `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/terminal/CommandPalette.tsx:60` (수동 토론 유일 호출부)
- `/Users/sunghoonk/Workspaces/JonberAITrading/docs/superpowers/specs/2026-07-14-funnel-consolidation-design.md` §Phase2 / `plans/2026-07-14-p2-funnel-consolidation.md` Task 8 (레거시 /positions 삭제 후보, 미완)