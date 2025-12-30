# UI/UX 개선 및 Basket 기능 제안서

## 현재 상태 분석

### 문제점
1. **단일 종목 분석**: 현재 한 번에 하나의 종목만 분석 가능
2. **마켓 간 분리**: Stock/Coin/Kiwoom 마켓이 완전히 분리되어 동시 관리 불가
3. **상태 동기화**: 분석 페이지와 메인 대시보드 간 상태 동기화 부족
4. **실시간 시세**: Kiwoom 마켓의 실시간 시세 미구현
5. **통화 표시**: 마켓별 통화(USD/KRW) 일관성 부족

---

## 제안: Basket (Watchlist) 기능

### 개념
- 여러 종목을 "장바구니"에 담아 동시에 관리/분석
- 최대 10개 종목 추가 가능
- 마켓 간 혼합 가능 (예: 삼성전자 + BTC + AAPL)

### UI/UX 레이아웃 제안

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [🔥 인기종목 티커 바] 삼성전자 ₩58,000 ▲1.2% │ BTC ₩145,000,000 ▼0.5% │ ...  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────┐  ┌─────────────────────────────┐ │
│  │                                      │  │  📋 My Basket (3/10)    [+] │ │
│  │         Main Content Area            │  ├─────────────────────────────┤ │
│  │                                      │  │ 🏢 삼성전자 (005930)        │ │
│  │   - Welcome Panel (idle)             │  │    ₩58,000 ▲1.2%   [분석]  │ │
│  │   - OR Analysis View (running)       │  ├─────────────────────────────┤ │
│  │                                      │  │ ₿ 비트코인 (KRW-BTC)        │ │
│  │   [Workflow Progress]                │  │    ₩145.5M ▼0.5%   [분석]  │ │
│  │   [Chart Panel]                      │  ├─────────────────────────────┤ │
│  │   [보유종목 | 미체결주문]            │  │ 📈 AAPL                      │ │
│  │                                      │  │    $189.50 ▲0.8%   [분석]  │ │
│  │                                      │  └─────────────────────────────┘ │
│  │                                      │                                   │
│  │                                      │  ┌─────────────────────────────┐ │
│  │                                      │  │  🔄 분석 중 (2/3)           │ │
│  │                                      │  ├─────────────────────────────┤ │
│  │                                      │  │ 🏢 삼성전자 ████████░░ 80%  │ │
│  │                                      │  │    Risk Assessment          │ │
│  │                                      │  ├─────────────────────────────┤ │
│  │                                      │  │ ₿ 비트코인 ████░░░░░░ 40%   │ │
│  │                                      │  │    Technical Analysis       │ │
│  └──────────────────────────────────────┘  └─────────────────────────────┘ │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  💬 Trading Assistant (Chat Popup)                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 구현 계획

### Phase 1: Basket (Watchlist) 기본 기능

#### 1.1 Store 확장
```typescript
// store/index.ts
interface BasketItem {
  id: string;
  marketType: 'stock' | 'coin' | 'kiwoom';
  ticker: string;
  displayName: string;
  price: number;
  changeRate: number;
  change: 'RISE' | 'FALL' | 'EVEN';
  addedAt: Date;
}

interface BasketState {
  items: BasketItem[];
  maxItems: 10;
}

// Actions
addToBasket: (item: BasketItem) => void;
removeFromBasket: (id: string) => void;
clearBasket: () => void;
```

#### 1.2 새 컴포넌트
| 컴포넌트 | 설명 |
|----------|------|
| `BasketWidget.tsx` | 우측 사이드바 바스켓 위젯 |
| `BasketItem.tsx` | 개별 종목 아이템 (실시간 시세) |
| `AddToBasketButton.tsx` | 종목 추가 버튼 |
| `BasketAnalysisButton.tsx` | 선택 종목 일괄 분석 버튼 |

#### 1.3 기능
- [ ] 종목 검색 후 바스켓에 추가
- [ ] 실시간 시세 업데이트 (WebSocket)
- [ ] 바스켓에서 개별 분석 시작
- [ ] 선택 종목 일괄 분석 (최대 3개 동시)
- [ ] LocalStorage 저장 (페이지 새로고침 유지)

---

### Phase 2: 실시간 시세 통합

#### 2.1 Backend API 추가
```
GET /api/v1/kr-stocks/prices?codes=005930,000660,035420
GET /api/v1/coins/prices?markets=KRW-BTC,KRW-ETH
```

#### 2.2 WebSocket 실시간 업데이트
```typescript
// WebSocket 메시지 타입
{
  type: 'PRICE_UPDATE',
  payload: {
    marketType: 'kiwoom',
    ticker: '005930',
    price: 58000,
    changeRate: 1.2,
    change: 'RISE'
  }
}
```

#### 2.3 PopularTickerBar 개선
- [ ] Kiwoom API 연동하여 실시간 시세 표시
- [ ] 클릭 시 바스켓에 추가
- [ ] 통화 단위 자동 표시 (KRW/USD)

---

### Phase 3: 분석 큐 고도화

#### 3.1 멀티 세션 관리
- [ ] 최대 3개 동시 분석
- [ ] 분석 우선순위 큐
- [ ] 분석 일시정지/재개

#### 3.2 상태 동기화
- [ ] 메인 대시보드 ↔ 분석 페이지 실시간 동기화
- [ ] History에서 진행 중인 분석 클릭 시 해당 세션으로 이동
- [ ] 분석 완료 시 알림 (Toast/Sound)

---

### Phase 4: UI/UX 통합 개선

#### 4.1 레이아웃 재구성
```
현재:
  - 좌측 사이드바: Navigation
  - 중앙: Main Content
  - 우측: 없음

개선:
  - 좌측 사이드바: Navigation (축소 가능)
  - 중앙: Main Content (확장)
  - 우측: Basket + 분석 큐 (토글 가능)
```

#### 4.2 반응형 개선
- [ ] 모바일: 바스켓을 하단 시트로 변경
- [ ] 태블릿: 2컬럼 레이아웃
- [ ] 데스크톱: 3컬럼 레이아웃

#### 4.3 다크/라이트 모드
- [ ] 테마 전환 기능 추가
- [ ] 시스템 설정 자동 감지

---

## 우선순위 및 일정

| 단계 | 기능 | 우선순위 | 복잡도 |
|------|------|----------|--------|
| 1.1 | Basket Store 확장 | 🔴 높음 | 중 |
| 1.2 | BasketWidget UI | 🔴 높음 | 중 |
| 2.1 | 실시간 시세 API | 🟡 중간 | 높음 |
| 2.2 | WebSocket 통합 | 🟡 중간 | 높음 |
| 3.1 | 멀티 세션 관리 | 🟡 중간 | 높음 |
| 4.1 | 레이아웃 재구성 | 🟢 낮음 | 중 |

---

## 기술 고려사항

### 1. 상태 관리
- Zustand persist middleware로 Basket 상태 영구 저장
- 마켓별 상태 분리 유지하면서 cross-market 조회 가능

### 2. 실시간 업데이트
- Kiwoom: REST API polling (5초) 또는 WebSocket
- Upbit: 기존 WebSocket 활용
- US Stock: 무료 API 제한으로 polling 권장

### 3. 성능 최적화
- React.memo로 불필요한 리렌더링 방지
- useMemo/useCallback 적극 활용
- Virtual scrolling for large basket

---

## 다음 단계

1. 이 제안서 검토 및 피드백
2. Phase 1 상세 설계 (컴포넌트 구조, API 스펙)
3. 개발 착수

**질문 또는 수정 사항이 있으시면 말씀해 주세요.**
