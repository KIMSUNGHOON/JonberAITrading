# 대시보드 위젯 정리 실사 (2026-07-14)

> 2-에이전트 READ-ONLY 실사 + 종합. HEAD 기준. 설계 제안(승인 전 구현 금지).

확인 완료. 두 실사자 결과가 실제 코드와 일치하며, 실행에 필요한 정밀 사항(레이아웃 트리, importer, 테스트 결합, 차트 입력 경로)까지 검증했다. 종합 설계안을 아래에 제출한다.

---

# 대시보드 위젯 정리 설계안 (READ-ONLY 실사 종합 · 승인 전 구현 금지)

## A. Scanner 직답

### (1) 대시보드 SCANNER 위젯(ScannerPanel) → **제거(REMOVE)**

**중복 정확히 무엇인가:** ScannerPanel이 표시하는 것 — 스캐너 상태 라벨 · 진행바 · 완료/총계 · B/S/W 카운트 — 은 `getScanProgress()` 하나에서 나온다. FunnelPanel의 DiscoverySection이 **동일한 `getScanProgress`를 동일한 라벨·진행바·카운트로 이미 그린다**(DiscoverySection.tsx:64-93). 그 위에 DiscoverySection만 추가로 갖는 것: 시작/일시중단/재개/정지 버튼 · auto-promote 토글 · 스캔결과 top10 · Scratchpad 승격/분석(:279-333).

**ScannerPanel의 고유 기능:** 0개. 완전한 부분집합이다.

**추가 근거 3가지:**
- **삼중 노출.** 이 정보는 이미 (a) 전역 상태바 `ScannerLivenessChip`(모든 라우트 공통 shell, TerminalShell.tsx:151-152)과 (b) DiscoverySection 두 곳에 있다. ScannerPanel은 세 번째 사본일 뿐.
- **이중 폴링 낭비.** DEFAULT_LAYOUT(v5)에서 `funnel`과 `scanner`가 **항상 동시에** 화면에 뜬다(TerminalDashboard.tsx:59). 같은 `getScanProgress`를 5초 간격으로 두 번 각각 친다.
- **도달성.** importer 검증: `ScannerPanel`은 TerminalDashboard가 유일하게 import(다른 참조 없음). 제거 시 파일까지 안전하게 삭제 가능(전용 테스트 파일 없음 — `ScannerLivenessChip.test.tsx`는 별개 컴포넌트).

> 결단: **REMOVE 확정.** 취향 여지 없음.

### (2) /scanner nav 탭(ScannerResultsPage) → **유지(KEEP)** (선택적 DEMOTE)

**퍼널이 커버 못 하는 고유가치:** 데이터소스가 **완전히 다른 엔드포인트**다. DiscoverySection = `getScanResults`(현재 진행 스캔의 메모리상 top-10, 신뢰도순, 필터/검색/페이지네이션 **없음**, DiscoverySection.tsx:38-39). /scanner = `getScanResultsFromDb + getScanSessions + getScanCounts`(**SQLite 전체 이력**, 세션 드롭다운 · 액션 필터 BUY/SELL/HOLD/WATCH/AVOID · 종목 검색 · 페이지네이션 · 상세분석 진입, ScannerResultsPage.tsx:148-179).

'현재 스캔 트리아지'(DISCOVERY) vs '과거 스캔 이력 감사'(/scanner)로 목적이 갈린다 — 중복 아님.

> 결단: **KEEP 확정.** 단 사용빈도가 낮으면 1급 nav 아이콘 대신 DiscoverySection 안 '전체 이력 보기 →' 딥링크로 **DEMOTE**하는 절충은 취향 판단(§C-4).

**핵심 대비:** 제거해야 할 건 대시보드 SCANNER **타일**이지 /scanner **탭**이 아니다. 두 개가 헷갈리기 쉬운데, 중복인 쪽은 타일이고 고유가치는 탭에 있다.

---

## B. 대시보드 위젯 정리안

현재 DEFAULT_LAYOUT(v5)에 배치된 8개 리프 + 등록만 된 `operations` 1개:

| 패널 (PanelId) | 배선 | 중복 대상 | 권고 | 근거 |
|---|---|---|---|---|
| **Funnel** (`funnel`) | WORKS | — | **KEEP** | P2 통합 1차 패널. WATCHLIST/PIPELINE 컬럼은 OperationsPanel export 재사용(정직-강등 계약 승계). |
| **Chart** (`chart`) | WORKS | — | **KEEP** | 유일 시각화. 입력 경로 3개(⌘K `/chart`·Positions행·Scratchpad행)로 안전. |
| **Portfolio** (`portfolio`) | WORKS | — | **KEEP** | 총자산/가용현금 계좌집계는 타 패널에 없는 고유 데이터. |
| **Performance** (`performance`) | WORKS | — | **KEEP** | 유일한 실현손익 시계열/승률. paper-trading 수익 증빙. |
| **Debate** (`debate`) | WORKS | — | **KEEP** | 실WS 토론/합의 표시. 제어는 /agent-chat SSOT로 이미 뺀 잘 설계된 읽기전용. |
| **Positions** (`positions`) | PARTIAL | — | **KEEP** (+후속수정) | 대시보드에서 STOP/TAKE 저장+청산 가능한 유일 표면. ⚠️KR 자기-되돌림 버그(§C-5). |
| **Scanner** (`scanner`) | WORKS | DiscoverySection의 완전 부분집합 | **REMOVE** | 고유기능 0개 + 삼중노출 + 이중폴링. §A-(1). |
| **Watchlist** (`watchlist`, 라벨 'Scratchpad') | WORKS | store.basket 동시노출(DiscoverySection) | **MERGE** | 같은 basket을 3번째로 노출. 고유기능(30s 가격폴링+행클릭 차트연동)만 DiscoverySection Scratchpad로 이관 후 타일 제거. §C-1. |
| **Operations** (`operations`) | DEAD | funnel이 대체 | **REMOVE** (등록만) | DEFAULT_LAYOUT에 미배치 + 창컨트롤 억제(toolbarControls=`<span/>`)로 재추가 UI 경로 전무 → 도달불가 죽은 등록. **파일은 존치**(FunnelPanel이 컬럼 import). |

### 제거 후 남는 린(lean) 세트 — **6개 타일**
`funnel` · `chart` · `portfolio` · `performance` · `positions` · `debate`

### DEFAULT_LAYOUT 단순화 (8리프 → 6리프)

```
현재 v5:                              →   제안 v6:
row[38,62]                                row[38,62]
 ├ funnel                                  ├ funnel
 └ row[40,30,30]                           └ row[40,30,30]
     ├ col[64,36]{watchlist,chart}  ✂        ├ chart              ← col1 분할 제거, chart 단독
     ├ col[16,46,16,22]                       ├ col[22,50,28]      ← scanner 빠짐
     │   {portfolio,performance,               │   {portfolio,performance,positions}
     │    positions,scanner}         ✂        └ debate
     └ debate
```

`watchlist` 제거로 col1의 세로 분할이 사라져 **chart가 col1 전체를 차지**(차트 가독성↑), col2는 4셀→3셀로 얇아진다. (분할 퍼센트는 취향 조정값 — 위는 예시.)

---

## C. 실행 계획

### 1. MERGE 먼저 (WatchlistPanel → DiscoverySection Scratchpad) — **순서상 최우선**
타일을 지우기 전에 고유기능 2개를 DiscoverySection의 Scratchpad 구획(DiscoverySection.tsx:380-469)으로 이관:
- **행클릭 차트연동** `onClick={() => setChartSymbol(it.ticker)}` + 활성행 하이라이트(WatchlistPanel.tsx:122).
- **30s 배치 가격폴링** `getCoinTickers`/`getKRStockTickers` → `updateBasketItemPrice`(WatchlistPanel.tsx:33-100). 이걸 이관해야 Scratchpad 행의 LAST/CHG%가 살아있는 값이 됨.

> 정정(정밀 검증): "차트 트리거를 먼저 이관 안 하면 ChartTile 입력이 끊긴다"는 과장. ChartTile은 ⌘K `/chart` 커맨드(commands.ts:92)와 PositionsPanel 행클릭(PositionsPanel.tsx:276)으로도 먹여지므로 **고아가 되지 않는다.** 이관 목적은 ChartTile 생존이 아니라 **스크래치패드발 차트선택 UX와 가격폴링을 잃지 않기 위함**이다. 위험도는 낮지만 순서는 여전히 MERGE→REMOVE가 맞다.

### 2. 제거·삭제 대상과 순서
1. **DiscoverySection에 §C-1 기능 이관** (MERGE).
2. **`scanner` 등록 제거**: PanelId union(:25)·TITLES(:34)·renderBody case(:75)·DEFAULT_LAYOUT(:59)에서 제거 + import(:18) 제거 → **`panels/ScannerPanel.tsx` 파일 삭제**(유일 importer가 대시보드).
3. **`watchlist` 등록 제거**: 동일 4곳(:24,30,56,71) + import(:14) 제거 → **`panels/WatchlistPanel.tsx` 삭제**. ⚠️`WatchlistPanel.test.tsx`(KR 가격폴백 회귀 5테스트)는 **삭제가 아니라 DiscoverySection 대상으로 재작성** — 그 회귀(KR early-return 스킵 버그)가 §C-1 이관 코드에 그대로 딸려오므로 가드를 옮겨야 한다.
4. **`operations` 등록 제거**: union(:24)·TITLES(:29)·renderBody case(:70) + import(:13) 제거. **`OperationsPanel.tsx` 파일은 존치**(FunnelPanel이 컬럼 6종 직접 import). `OperationsPanel.test.tsx`는 컬럼 계약을 가드하니 유지. (전(全)보드 `OperationsPanel` export는 이제 미사용 — 삭제 여부는 저(低)우선 취향.)
5. **DEFAULT_LAYOUT 재구성**(6리프, §B 트리) + **STORAGE_KEY v5→v6**.

### 3. STORAGE_KEY 재범프(v6) — **필요함**
react-mosaic가 트리를 localStorage에 저장한다. 기존 사용자의 v5 저장 트리에는 삭제된 `scanner`/`watchlist` 리프가 남아, renderBody가 그 case를 잃으면 해당 타일이 **빈 화면/undefined 렌더**로 깨진다. **v6로 범프**하면 낡은 트리를 폐기하고 깨끗한 DEFAULT_LAYOUT을 쓴다. 동반 수정: `TerminalDashboard.test.tsx:32`의 `toBe('...v5')` 단언 → v6, 그리고 leaf 목록 단언(:35-50)에서 scanner/watchlist 기대 제거.

### 4. 회귀 위험
- **딥링크/라우트: 없음.** 대시보드 타일 제거는 라우트를 안 건드림. /scanner·/positions·/watchlist 라우트 그대로 → 딥링크 무손상.
- **레이아웃 마이그레이션:** v6 범프로 사용자 커스텀 배치가 초기화됨. 단 창컨트롤이 억제돼(toolbarControls=`<span/>`) 애초에 사용자가 배치를 바꿀 표면이 거의 없어 실질 영향 낮음.
- **4-site 일관성 테스트:** TerminalDashboard.test.tsx가 "모든 DEFAULT_LAYOUT 리프는 TITLES+renderBody를 가진다"를 검증. union에서 PanelId를 빼면 TS `Record<PanelId,...>`가 TITLES·renderBody 동시 수정을 강제 → 세 곳을 함께 지우면 컴파일+테스트 통과.

### 5. KEEP하되 후속수정 필요 — PositionsPanel KR 버그 (범위 밖, 명시만)
대시보드 PositionsPanel은 KR에서 `getKRStockPositions()`를 쓰는데 이 엔드포인트는 `stop_loss/take_profit`을 **구조적으로 항상 None 하드코딩**(kr_stocks/positions.py:79-89, 코드 주석이 자백). STOP/TAKE 저장 성공 직후 refetch가 이 None을 다시 읽어 **즉시 공란으로 자기-되돌림**. /positions 페이지의 `KiwoomPositionPanel`은 같은 이유로 이미 `/operations` 소스로 전환(주석 :7-18)했으나 대시보드 타일은 구 엔드포인트에 잔류. **패널은 KEEP, 데이터소스를 `/operations` 기반으로 이관하는 별도 수정** 권고(코인은 storage 기반이라 무관). 이건 위젯-과다와 무관한 별건 버그.

### 6. 인접 정리 (nav/모바일 — Q3 "위젯 과다"의 확장, 선택)
| 대상 | 배선 | 권고 | 성격 |
|---|---|---|---|
| MobileNav 하단바 Analysis/Charts/Position 3버튼 | DEAD (`onClick=()=>setActiveView('none')`, 라우팅 없음, 'Charts'는 유령 라벨) | **REMOVE** | **명백** |
| Sidebar(모바일) 하드코딩 8항목 | PARTIAL (nav.ts 미참조, `watchlist` 결측, 구식 'Charts' 주석) | **MERGE**(NAV_ITEMS 단일소스 map) | 명백-소 |
| `watchlist` nav 탭(`/?tab=watchlist`) | PARTIAL (아무도 `tab` 미소비 → dashboard와 렌더 100% 동일한 장식탭) | **MERGE/수정**(WATCHLIST 섹션 anchor-scroll 배선하거나 탭 제거) | 취향 |

### 7. 명백히 제거 가능 vs 사용자 확인 필요

**명백(취향 무관, 바로 진행 가능):**
- 대시보드 `scanner` 타일 제거 + ScannerPanel.tsx 삭제 (완전 부분집합).
- `operations` PanelId 등록 제거 (도달불가 죽은 등록).
- MobileNav 죽은 3버튼 제거.
- STORAGE_KEY v6 범프 (제거의 필수 동반).

**사용자 확인 필요(취향):**
- `watchlist` 타일 **MERGE 여부** — 살아서 동시에 보이는 working 타일이다. "압축 차트연동 워치리스트를 별도 타일로 보고 싶다"면 KEEP도 방어 가능. 실사 권고는 MERGE지만 최종은 취향.
- /scanner **DEMOTE 여부** (1급 nav 유지 vs DiscoverySection 딥링크로 강등).
- Scratchpad nav(`basket`) **DEMOTE 여부** (store.basket 표면이 이미 3곳).
- PositionsPanel **KR 소스 이관**(§C-5) 착수 시점 — 별건 버그라 이번 정리와 분리 가능.

---

**요약:** Q1 = 대시보드 Scanner 타일 **제거**(퍼널 DISCOVERY의 완전 부분집합). Q2 = /scanner 탭 **유지**(DB 전체이력·필터는 대시보드에 없는 고유가치). Q3 = 8리프→**6리프**(scanner 제거·watchlist는 DiscoverySection으로 병합·operations 죽은 등록 정리), STORAGE_KEY **v6 범프** 필수, ScannerPanel.tsx/WatchlistPanel.tsx 삭제 및 관련 테스트 재배치. `funnel·chart·portfolio·performance·positions·debate`가 최종 린 세트.

관련 파일(절대경로): `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/components/terminal/TerminalDashboard.tsx`, `.../panels/ScannerPanel.tsx`, `.../panels/WatchlistPanel.tsx`, `.../panels/WatchlistPanel.test.tsx`, `.../panels/DiscoverySection.tsx`, `.../panels/OperationsPanel.tsx`, `.../TerminalDashboard.test.tsx`, `.../panels/PositionsPanel.tsx`, `/Users/sunghoonk/Workspaces/JonberAITrading/frontend/src/pages/ScannerResultsPage.tsx`, `.../components/layout/MobileNav.tsx`, `.../components/layout/Sidebar.tsx`, `.../nav.ts`.