# 프론트엔드 재설계: "Dense Terminal Shell, Editorial Agent Lane"

- **날짜**: 2026-07-05
- **상태**: 방향 확정 (UI/UX 리뷰 + 인터랙티브 목업 + 사용자 결정 완료)
- **근거**: 6-에이전트 UI/UX 리뷰 워크플로우(`frontend-uiux-review`) + 4방향 인터랙티브 비교 목업(아티팩트) + 사용자 결정
- **스택**: React 18 + Vite + Tailwind 3 + Zustand + lightweight-charts + react-markdown (변경 없음 — 재스킨 + 구조 리팩터)

---

## 1. 철학

현 프론트는 못생긴 게 아니라 **장르가 틀렸다**(mis-genred) — 실시간·돈 걸린·AI 트레이딩 터미널을 마케팅 대시보드 언어(반투명 `rounded-xl` 카드, 화면당 숫자 3~4개, 기어가는 마퀴)로 렌더. 목표는 **밀집 트레이딩 터미널** 미학인데, 앱의 존재 이유인 **대화형 에이전트 서사(멀티에이전트 토론·스트리밍 추론·한글 분석 리포트)** 를 순수 mono 터미널은 붕괴시킨다(한글은 Latin-mono 메트릭에 안 맞음).

**해법 = 하이브리드**: 데이터 절반은 터미널처럼(밀도+커맨드+상태줄+tick-flash), AI 절반은 읽기 좋은 토론으로(에디토리얼 본문 + 칸막이된 에이전트 색).

---

## 2. 확정 결정 (2026-07-05)

| 결정 | 값 |
|------|-----|
| **방향** | **Hybrid ★** — Binance 규율 베이스 + 터미널 커맨드/상태줄 + 에디토리얼 에이전트 레인 |
| **상승/하락 색** | **서구식 초록=상승 / 빨강=하락** 전역 통일 (차트·`bull/bear` 토큰과 일치) + **KR 빨강=상승 토글** 제공 + **상태줄에 현재 규약 표시** |
| **구조 부채** | **재설계와 함께** — 라우터+딥링크 도입, 2000줄 스토어 분할, WS 4개→단일 연결원천 |
| **데스크톱/모바일** | **데스크톱 우선** — 키보드/밀집 12px 행 풀레버리지, 모바일은 얇은 동반 |

### 이차 결정 (Phase 진행 중 확정)
- 숫자 폰트: JetBrains Mono(강한 터미널감) vs Inter+`tnum`(Binance 충실·한글 라벨 호환) — Phase 1에서 선택
- 에이전트별 색 의존도: 토론 스캔에 색을 쓰는지 → 쓰면 트랜스크립트 내 칸막이 팔레트 유지(기본 유지)
- HITL 라이트 테마 인버전("실거래" 신호): 선택
- US 데이터: 지금 실데이터 연결 vs `[SIMULATED]` 라벨 후 KR/coin 먼저

---

## 3. 미학과 무관하게 먼저 고칠 것

1. **⚠️ 색상 안전 버그** — `MarketSummaryWidget.tsx:266`(빨강=상승) vs `TradingDashboard.tsx:87`·agent-chat DecisionPanel(초록=상승). 같은 수익이 패널마다 반대색 → 오독 위험. §2 규약으로 전역 통일 후에만 스킨.
2. **tabular-nums 0회** — 모든 가격/%/수량이 비례폭 Inter라 자릿수 흔들림·우정렬 안 됨. `.num { font-variant-numeric: tabular-nums }` 유틸을 모든 숫자에.
3. **3개 dark 배경 + 2개 토큰 시스템** — ~50파일 `surface/border/bull/bear` 토큰 vs ~19파일 하드코딩 `bg-gray-900/800/700`+`green-400/red-400`, 차트 `#0f1419`. 단일 램프로 통일.
4. **"Live"는 연극** — 하드코딩 펄스 점이 5~30s REST 폴링을 실시간 위장. 차트 `setData` 1회 후 `series.update()` 없음. 연결 바인딩된 실제 live/stale로 교체.
5. **가짜 데이터** — `Math.random` US 캔들·null US 티커·0 US 계좌. 실데이터 연결 또는 `[SIMULATED]` 명시(밀집 프레임에선 거짓말이 더 도드라짐).
6. **모달 더미** — HITL 승인이 모달 더미 4번째. 도킹 오더티켓으로 승격.

---

## 4. Tailwind 토큰 세트 (Hybrid)

**단일 dark 램프** (3-gray triad 제거):
```
canvas   #0b0e11   card   #161a1f   elevated #1c222a   hairline #242c37
text     #e8ecf1   muted  #7b8794   dim      #4d5763
accent   #f0b90b (단일 브랜드 — 액션/포커스/브랜드마크에만; HOLD/warn/risk/Connecting의 옐로 남용 제거)
up (green) #0ecb81   down (red) #f6465d   warn #f0b90b   info #3b82f6
```
- **트레이딩 색은 text-only** (초록/빨강을 카드/버튼 배경으로 쓰지 않음 — 명시적 Buy/Sell 버튼 예외).
- **radius 축소**: `rounded-xl`→`rounded-md`(6px)/none. `.glass`·`.text-gradient` 삭제. `.signal-hold`를 `yellow-500`에서 분리.
- **폰트**: UI/프로즈 = 비례 산세리프(system-ui/Inter), 숫자·터미널 크롬 = mono(JetBrains Mono/`ui-monospace`) + `tabular-nums`. **에이전트 메시지 본문 = 비례(프로즈)** — 한글 거주지.
- **밀도**: 기본 행 높이 ~30px, 데이터 blotter 12.5px mono. 화면당 숫자 3~4개 → 풀 blotter.

**칸막이 에이전트 팔레트** (트랜스크립트 내부에서만, 단일-액센트 규율의 의도적 예외):
```
technical #38bdf8  fundamental #34d399  sentiment #f472b6  risk #fb923c  moderator #f0b90b
```
그 외 모든 곳은 초록/빨강만(밀집 데이터 화면의 색 scarcity 유지).

---

## 5. 컴포넌트 규칙

**전역 셸 (신규, 모든 뷰 감쌈)**
- **상단 커맨드라인** (`:analyze 005930`, `:go positions`, `/filter`, `⌘K`) — 이모지-플래그 `MarketTabs`를 커맨드 토큰(`005930 KS`, `KRW-BTC`)으로 대체. **라우터/딥링크 진입점**.
- **하단 상태줄** — `KRX │ WS ●live 42ms │ 09:31 │ P&L: GRN-UP │ CONSENSUS 72%`. 앱에 없는 **전역 live/stale/지연 + P&L 규약 + 컨센서스** 단일 지표. 통합 WS 스토어가 공급.

**데이터 화면 (Binance-flat 밀도)**
- Dashboard: 카드 제거→작은 ALL-CAPS 제목의 flat 패널; 밀도 3~4→풀 blotter.
- Markets/`PopularTickerBar`: 기어가는 마퀴 중단→정적 밀집 정렬 테이블(SYM·LAST·±CHG·%·VOL), tabular 숫자, per-cell tick-flash. US는 채우거나 `[SIMULATED]`.
- Chart/`TradingChart`: 캔버스 bg→단일 토큰, 캔들→정확한 up/down, hairline 그리드, mono 축. **실버그 수정**(`series.update()` + 실제 refetch), 가짜 1s-spin Refresh 제거.
- Positions/`PositionCard`→`PositionMonitor`: **최대 밀도 이득** — 1카드/포지션→`top`식 다행 blotter(entry/cur/qty/P&L/stop/take/held), 우정렬 tabular, unrealized-P&L tick-flash, 연결 바인딩 "live".

**AI 화면 (듀얼모드 — 필수)**
- 구조는 dense mono: 타임스탬프·에이전트 핸들·`VoteCard`→투표 blotter(AGENT·VOTE·CONF·WGT·SCORE)·`DecisionPanel`→컨센서스 티켓·연결 상태.
- 스트리밍 `ReasoningLog`: 닫힌 `ReasoningSlidePanel`서 꺼내 **상시 `tail -f` 와이어**로 승격(이미 `entries: string[]` 소비). collapse-to-latest 기본 OFF.
- **메시지/리포트 본문 = 에디토리얼 비례 폰트 + 실제 마크다운**, ~64–68ch 측정, 넉넉한 leading. `AnalysisDetailPage`도 이 reading-pane. 한글 프로즈 거주지.
- **에이전트별 색은 이 패널 안에서만** 생존(§4 칸막이 팔레트).

**HITL (`ApprovalDialog`) = 오더티켓**
- 도킹, 키보드 확정, dense key-value 티켓, 리스크 게이지(초록→amber→빨강, 브랜드 액센트 아님), KR 장마감 경고 유지. **크고 라벨된 Approve/Reject 유지**(`[y/N]` 함정 금지). 선택: 라이트 테마 인버전("실거래" 신호).

---

## 6. 구조 리팩터 (재설계와 동시)

- **라우터 + 딥링크**: 11-branch `currentView` 스위치(`MainContent.tsx`, `store/index.ts:179`) 은퇴 → 실제 라우트. 커맨드 팔레트가 URL 타깃을 필요로 하니 동시 구축.
- **스토어 분할**: 2000줄 Zustand 메가스토어를 새 뷰 경계로 분해.
- **WS 통합**: 4개 불일치 WebSocket 추상 → 단일 연결-상태 원천(상태줄이 소비).

---

## 7. 페이징

- **Phase 1 (기계적·고가치·빠르게 다른 앱)**: Tailwind 토큰 램프 통일 + `.num` tabular 전면 + 카드→테이블 de-card + 차트 리테마 + §2 색 규약 전역 통일 + 가짜데이터 라벨/수정 + 가짜 live/Refresh 제거.
- **Phase 2 (구조 + "빠름")**: ⌘K 커맨드 팔레트(실 라우트 위 = 라우터/딥링크 해결) + 하단 상태줄(단일 연결 스토어 = WS 4개 통합) + 라우터 도입.
- **Phase 3 (AI 레인)**: 에이전트 패널 듀얼모드 + 스트리밍 와이어 승격 + HITL 오더티켓 + (선택) HITL 라이트모드.

각 Phase는 독립적으로 "눈에 띄게 다른 앱"을 배포. Phase 1이 가장 빠른 시각적 임팩트.

---

## 8. 접근성/한글

12px 행·tick-flash 색이 WCAG 대비 통과, 모바일 바텀시트 탭타깃 ≥44px, 혼합 한글/Latin 컬럼이 선택 숫자 폰트에서 정렬 확인.

---

## 참고 아티팩트

4방향 인터랙티브 비교 목업(같은 3화면을 Binance/TUI/Bloomberg/Hybrid로 실시간 전환): 세션 아티팩트 `Frontend Direction Comparator`.
