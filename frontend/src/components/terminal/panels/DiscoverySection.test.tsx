/**
 * DISCOVERY section (P2 funnel Phase 1, P1-b) — pins the wiring of backend
 * controls that previously had zero UI callers:
 *  - Scanner ▶ start / ⏸ pause / ▶ resume / ⏹ stop, driven by the real
 *    getScanProgress poll (progress bar + status label).
 *  - The auto-promote toggle: when ON, startScan must receive
 *    auto_promote_enabled=true AND a warning about the autonomous pipeline
 *    must be visible.
 *  - Scan-result rows: [승격▲] → addToWatchList(ticker=...), [분석▶] →
 *    useStartAnalysis's start(...).
 *  - Scratchpad (client `basket` store slice): add/list + the same two
 *    actions per row.
 *  - Scratchpad price polling + row-click chart link (re-homed from the
 *    deleted standalone WatchlistPanel tile, dashboard-widget-cull
 *    2026-07-14 §C-1/§C-2): batched getKRStockTickers →
 *    updateBasketItemPrice, including the KR early-return-skip guard for a
 *    per-code null in the batch response.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const startScan = vi.fn();
const pauseScan = vi.fn();
const resumeScan = vi.fn();
const stopScan = vi.fn();
const getScanProgress = vi.fn();
const getScanResults = vi.fn();
const addToWatchList = vi.fn();
const searchKRStocks = vi.fn();
const getKRStockTickers = vi.fn();

vi.mock('@/api/client', () => ({
  startScan: (...a: unknown[]) => startScan(...a),
  pauseScan: (...a: unknown[]) => pauseScan(...a),
  resumeScan: (...a: unknown[]) => resumeScan(...a),
  stopScan: (...a: unknown[]) => stopScan(...a),
  getScanProgress: (...a: unknown[]) => getScanProgress(...a),
  getScanResults: (...a: unknown[]) => getScanResults(...a),
  addToWatchList: (...a: unknown[]) => addToWatchList(...a),
  searchKRStocks: (...a: unknown[]) => searchKRStocks(...a),
  getKRStockTickers: (...a: unknown[]) => getKRStockTickers(...a),
}));

const mockStart = vi.fn();
vi.mock('@/hooks/useStartAnalysis', () => ({
  useStartAnalysis: () => mockStart,
}));

import { useStore } from '@/store';
import { DiscoverySection } from './DiscoverySection';
import type { ScanProgressResponse, ScanResultItem } from '@/types';

function baseProgress(overrides: Partial<ScanProgressResponse> = {}): ScanProgressResponse {
  return {
    status: 'idle',
    total_stocks: 0,
    completed: 0,
    in_progress: 0,
    failed: 0,
    progress_pct: 0,
    current_stocks: [],
    buy_count: 0,
    sell_count: 0,
    hold_count: 0,
    watch_count: 0,
    avoid_count: 0,
    started_at: null,
    estimated_completion: null,
    completed_at: null,
    last_scan_date: null,
    last_error: null,
    ...overrides,
  };
}

function resultItem(overrides: Partial<ScanResultItem> = {}): ScanResultItem {
  return {
    stk_cd: '005930',
    stk_nm: '삼성전자',
    action: 'BUY',
    signal: 'buy',
    confidence: 0.82,
    summary: '기술적 지표 매수 신호',
    key_factors: ['골든크로스'],
    current_price: 71000,
    market_type: 'KOSPI',
    scanned_at: '2026-07-14T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  getScanProgress.mockResolvedValue(baseProgress());
  getScanResults.mockResolvedValue({ results: [], count: 0, total: 0, filter: null });
  searchKRStocks.mockResolvedValue({ stocks: [], total: 0 });
  useStore.setState({
    basket: { items: [], maxItems: 10, isUpdating: false },
    upbitApiConfigured: false,
    kiwoomApiConfigured: false,
    chartSymbol: null,
  });
});

describe('DiscoverySection — scanner controls', () => {
  it('▶ 스캔 시작이 startScan을 auto_promote=false 상태로 호출한다', async () => {
    render(<DiscoverySection />);
    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /스캔 시작/ }));
    await waitFor(() =>
      expect(startScan).toHaveBeenCalledWith(expect.objectContaining({ auto_promote_enabled: false }))
    );
  });

  it('auto_promote 토글 ON 시 startScan에 auto_promote_enabled=true 전달 + 경고 문구 노출', async () => {
    render(<DiscoverySection />);
    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());

    expect(screen.queryByText(/자율/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /자동 승격/ }));
    expect(screen.getByText(/자율/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /스캔 시작/ }));
    await waitFor(() =>
      expect(startScan).toHaveBeenCalledWith(expect.objectContaining({ auto_promote_enabled: true }))
    );
  });

  it('실행 중 상태에서 ⏸ 일시중단 버튼이 pauseScan을 호출한다', async () => {
    getScanProgress.mockResolvedValue(baseProgress({ status: 'running', progress_pct: 42, completed: 42, total_stocks: 100 }));
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByRole('button', { name: /일시중단/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /일시중단/ }));
    await waitFor(() => expect(pauseScan).toHaveBeenCalled());
  });

  it('일시정지 상태에서 ▶ 재개 버튼이 resumeScan을 호출한다', async () => {
    getScanProgress.mockResolvedValue(baseProgress({ status: 'paused', progress_pct: 42 }));
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByRole('button', { name: /재개/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /재개/ }));
    await waitFor(() => expect(resumeScan).toHaveBeenCalled());
  });

  it('⏹ 정지 버튼이 stopScan을 호출한다', async () => {
    getScanProgress.mockResolvedValue(baseProgress({ status: 'running' }));
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByRole('button', { name: /정지/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /정지/ }));
    await waitFor(() => expect(stopScan).toHaveBeenCalled());
  });

  it('진행바와 카운트가 진행률 폴 결과를 반영한다', async () => {
    getScanProgress.mockResolvedValue(baseProgress({ status: 'running', progress_pct: 37, completed: 370, total_stocks: 1000 }));
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '37'));
    expect(screen.getByText(/370/)).toBeInTheDocument();
  });
});

describe('DiscoverySection — scan results actions', () => {
  it('결과 행의 [승격▲]이 addToWatchList를 티커와 함께 호출한다', async () => {
    getScanResults.mockResolvedValue({ results: [resultItem()], count: 1, total: 1, filter: null });
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /승격.*005930/ }));
    await waitFor(() =>
      expect(addToWatchList).toHaveBeenCalledWith(expect.objectContaining({ ticker: '005930', current_price: 71000 }))
    );
  });

  it('결과 행의 [분석▶]이 useStartAnalysis의 start를 kiwoom/티커로 호출한다', async () => {
    getScanResults.mockResolvedValue({ results: [resultItem()], count: 1, total: 1, filter: null });
    mockStart.mockResolvedValue('session-1');
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /분석.*005930/ }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith('kiwoom', '005930', '삼성전자'));
  });

  it('결과 행에 액션뱃지와 신뢰도를 표시한다', async () => {
    getScanResults.mockResolvedValue({
      results: [resultItem({ action: 'BUY', confidence: 0.82 })],
      count: 1, total: 1, filter: null,
    });
    render(<DiscoverySection />);
    await waitFor(() => expect(screen.getByText('BUY')).toBeInTheDocument());
    expect(screen.getByText(/82/)).toBeInTheDocument();
  });
});

describe('DiscoverySection — Scratchpad', () => {
  function krItem(overrides: Record<string, unknown> = {}) {
    return {
      id: 'item-005930',
      marketType: 'kiwoom' as const,
      ticker: '005930',
      displayName: '삼성전자',
      price: 71000,
      prevPrice: 0,
      changeRate: 0,
      change: 'EVEN' as const,
      addedAt: new Date(),
      lastUpdated: null,
      isLoading: false,
      error: null,
      ...overrides,
    };
  }

  it('store의 스크래치패드 항목이 목록에 렌더된다', async () => {
    useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
    render(<DiscoverySection />);
    expect(screen.getByText('삼성전자')).toBeInTheDocument();
    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());
  });

  it('항목의 [분석▶]이 useStartAnalysis의 start를 호출한다', async () => {
    useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
    mockStart.mockResolvedValue('session-1');
    render(<DiscoverySection />);
    fireEvent.click(screen.getByRole('button', { name: /분석.*005930/ }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith('kiwoom', '005930', '삼성전자'));
  });

  it('KR 항목의 [승격▲]이 addToWatchList를 호출한다', async () => {
    useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
    render(<DiscoverySection />);
    fireEvent.click(screen.getByRole('button', { name: /승격.*005930/ }));
    await waitFor(() =>
      expect(addToWatchList).toHaveBeenCalledWith(expect.objectContaining({ ticker: '005930', current_price: 71000 }))
    );
  });

  it('6자리 종목코드 입력 후 추가 버튼이 스크래치패드에 항목을 추가한다', async () => {
    render(<DiscoverySection />);
    fireEvent.change(screen.getByPlaceholderText(/종목코드/), { target: { value: '000660' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    await waitFor(() => expect(useStore.getState().basket.items.some((i) => i.ticker === '000660')).toBe(true));
  });
});

// -------------------------------------------------------------------------
// Re-homed from the deleted standalone WatchlistPanel tile
// (dashboard-widget-cull, 2026-07-14 §C-1/§C-2): the row-click chart link and
// the 30s batch price polling — including the KR early-return-skip guard a
// per-code null in the batch response must not blank/crash the panel — were
// WatchlistPanel's only two features DiscoverySection's Scratchpad lacked.
// Both are now wired directly into DiscoverySection; these tests replace
// WatchlistPanel.test.tsx (deleted along with the panel it covered).
// -------------------------------------------------------------------------

describe('DiscoverySection — Scratchpad row click sets chart symbol (re-homed from WatchlistPanel)', () => {
  function krItem(overrides: Record<string, unknown> = {}) {
    return {
      id: 'item-005930',
      marketType: 'kiwoom' as const,
      ticker: '005930',
      displayName: '삼성전자',
      price: 71000,
      prevPrice: 0,
      changeRate: 0,
      change: 'EVEN' as const,
      addedAt: new Date(),
      lastUpdated: null,
      isLoading: false,
      error: null,
      ...overrides,
    };
  }

  it('행 클릭이 setChartSymbol(ticker)을 호출한다', async () => {
    useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
    render(<DiscoverySection />);
    fireEvent.click(screen.getByText('삼성전자'));
    await waitFor(() => expect(useStore.getState().chartSymbol).toBe('005930'));
  });

  it('chartSymbol과 일치하는 활성 행에 하이라이트 클래스가 적용된다', async () => {
    useStore.setState({
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
      chartSymbol: '005930',
    });
    render(<DiscoverySection />);
    const row = screen.getByText('삼성전자').closest('div[title="차트에 표시"]');
    expect(row).not.toBeNull();
    expect(row).toHaveClass('bg-elevated/60');
    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());
  });

  it('승격/분석 버튼 클릭은 행 클릭(차트 이동)으로 전파되지 않는다', async () => {
    useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
    mockStart.mockResolvedValue('session-1');
    render(<DiscoverySection />);
    fireEvent.click(screen.getByRole('button', { name: /분석.*005930/ }));
    await waitFor(() => expect(mockStart).toHaveBeenCalled());
    expect(useStore.getState().chartSymbol).toBeNull();
  });
});

describe('DiscoverySection — Scratchpad price polling (re-homed KR-price-fallback regression from WatchlistPanel.test.tsx)', () => {
  function krItem(overrides: Record<string, unknown> = {}) {
    return {
      id: `item-${overrides.ticker ?? '005930'}`,
      marketType: 'kiwoom' as const,
      ticker: '005930',
      displayName: '삼성전자',
      price: 0,
      prevPrice: 0,
      changeRate: 0,
      change: 'EVEN' as const,
      addedAt: new Date(),
      lastUpdated: null,
      isLoading: false,
      error: null,
      ...overrides,
    };
  }

  function krTicker(overrides: Record<string, unknown> = {}) {
    return {
      stk_cd: '005930',
      stk_nm: '삼성전자',
      cur_prc: 71000,
      prdy_vrss: 500,
      prdy_ctrt: 1.23,
      opng_prc: 70500,
      high_prc: 71200,
      low_prc: 70200,
      trde_qty: 1000,
      trde_prica: 71000000,
      per: null,
      pbr: null,
      eps: null,
      bps: null,
      timestamp: '2026-07-13T00:00:00Z',
      ...overrides,
    };
  }

  it('갱신 폴 이후 KR 종목의 가격/등락률이 getKRStockTickers 배치 호출로 갱신된다', async () => {
    useStore.setState({
      kiwoomApiConfigured: true,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });
    getKRStockTickers.mockResolvedValue({
      tickers: { '005930': krTicker() },
      total: 1,
    });

    render(<DiscoverySection />);

    await waitFor(() => expect(getKRStockTickers).toHaveBeenCalledWith(['005930']));
    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    expect(screen.getByText('+1.23%')).toBeInTheDocument();
  });

  it('여러 KR 종목이 있어도 배치 호출은 한 번만 발생한다 (N건이 아니라 1건)', async () => {
    useStore.setState({
      kiwoomApiConfigured: true,
      basket: {
        items: [
          krItem({ id: 'item-005930', ticker: '005930', displayName: '삼성전자' }),
          krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' }),
        ],
        maxItems: 10,
        isUpdating: false,
      },
    });
    getKRStockTickers.mockResolvedValue({
      tickers: {
        '005930': krTicker(),
        '000660': krTicker({ stk_cd: '000660', stk_nm: 'SK하이닉스', cur_prc: 150000, prdy_ctrt: -0.5 }),
      },
      total: 2,
    });

    render(<DiscoverySection />);

    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    expect(screen.getByText('₩150,000')).toBeInTheDocument();
    // Exactly ONE batch call for both symbols — not one call per symbol.
    expect(getKRStockTickers).toHaveBeenCalledTimes(1);
    expect(getKRStockTickers).toHaveBeenCalledWith(['005930', '000660']);
  });

  it('kiwoomApiConfigured가 false면 KR 폴을 시도하지 않는다', async () => {
    useStore.setState({
      kiwoomApiConfigured: false,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });

    render(<DiscoverySection />);

    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());
    expect(getKRStockTickers).not.toHaveBeenCalled();
  });

  it('일부 KR 종목이 배치 응답에서 null이어도 패널이 죽지 않고 나머지는 갱신된다', async () => {
    useStore.setState({
      kiwoomApiConfigured: true,
      basket: {
        items: [
          krItem({ id: 'item-005930', ticker: '005930', displayName: '삼성전자' }),
          krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' }),
        ],
        maxItems: 10,
        isUpdating: false,
      },
    });
    getKRStockTickers.mockResolvedValue({
      tickers: {
        '005930': krTicker(),
        '000660': null, // honest per-code degrade — never fabricated
      },
      total: 1,
    });

    render(<DiscoverySection />);

    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    // Null ticker keeps its last-known (missing) price — honest DASH, no crash.
    expect(screen.getByText('SK하이닉스')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('배치 호출 자체가 실패해도 패널이 죽지 않는다', async () => {
    useStore.setState({
      kiwoomApiConfigured: true,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });
    getKRStockTickers.mockRejectedValue(new Error('kiwoom rate limit'));

    render(<DiscoverySection />);

    await waitFor(() => expect(getKRStockTickers).toHaveBeenCalled());
    // Still renders the row with its last-known (initial) price, no crash.
    expect(screen.getByText('삼성전자')).toBeInTheDocument();
  });

});

// -------------------------------------------------------------------------
// Power-staging features folded in from the deleted standalone BasketWidget
// (nav-rationalize, 2026-07-14, user-approved "ABSORB"): comma-separated
// bulk-add, autocomplete ↑/↓/Esc keyboard nav, per-item remove + clear-all,
// bulk "analyze all" respecting the concurrent-slot limit, and the
// API-not-configured warning banner. BasketWidget.test.tsx (deleted along
// with the widget) covered these; these tests replace it.
// -------------------------------------------------------------------------

describe('DiscoverySection — Scratchpad power features folded in from BasketWidget', () => {
  function krItem(overrides: Record<string, unknown> = {}) {
    return {
      id: `item-${overrides.ticker ?? '005930'}`,
      marketType: 'kiwoom' as const,
      ticker: '005930',
      displayName: '삼성전자',
      price: 71000,
      prevPrice: 0,
      changeRate: 0,
      change: 'EVEN' as const,
      addedAt: new Date(),
      lastUpdated: null,
      isLoading: false,
      error: null,
      ...overrides,
    };
  }

  describe('comma-separated bulk-add', () => {
    it('콤마로 구분된 여러 종목코드를 한 번에 추가한다', async () => {
      render(<DiscoverySection />);
      fireEvent.change(screen.getByPlaceholderText(/종목코드/), { target: { value: '005930,000660' } });
      fireEvent.click(screen.getByRole('button', { name: '추가' }));
      await waitFor(() => {
        const tickers = useStore.getState().basket.items.map((i) => i.ticker);
        expect(tickers).toEqual(expect.arrayContaining(['005930', '000660']));
      });
    });

    it('유효하지 않은 코드가 섞여 있으면 유효한 것만 추가하고 나머지는 에러로 안내한다', async () => {
      render(<DiscoverySection />);
      fireEvent.change(screen.getByPlaceholderText(/종목코드/), { target: { value: '005930,BAD' } });
      fireEvent.click(screen.getByRole('button', { name: '추가' }));
      await waitFor(() => {
        expect(useStore.getState().basket.items.some((i) => i.ticker === '005930')).toBe(true);
      });
      expect(screen.getByText(/잘못된 종목코드.*BAD/)).toBeInTheDocument();
    });

    it('select에 COIN 옵션이 없다 — 코인 스택 제거 이후 사용자가 실제로 고를 수 있는 값은 KR뿐', () => {
      render(<DiscoverySection />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      const optionValues = Array.from(select.options).map((o) => o.value);
      expect(optionValues).toEqual(['kiwoom']);
    });
  });

  describe('autocomplete keyboard nav (↑/↓/Esc)', () => {
    it('↓ 키로 두 번째 자동완성 항목을 선택하고 Enter로 추가한다', async () => {
      searchKRStocks.mockResolvedValue({
        stocks: [
          { stk_cd: '005930', stk_nm: '삼성전자', cur_prc: 71000, prdy_ctrt: 1.2, prdy_vrss: 0, trde_qty: 0, trde_prica: 0 },
          { stk_cd: '000660', stk_nm: 'SK하이닉스', cur_prc: 150000, prdy_ctrt: -0.5, prdy_vrss: 0, trde_qty: 0, trde_prica: 0 },
        ],
        total: 2,
      });
      render(<DiscoverySection />);
      const input = screen.getByPlaceholderText(/종목코드/);
      fireEvent.change(input, { target: { value: '반도체' } });
      await waitFor(() => expect(searchKRStocks).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByText('SK하이닉스')).toBeInTheDocument());

      fireEvent.keyDown(input, { key: 'ArrowDown' }); // -> index 0 (삼성전자)
      fireEvent.keyDown(input, { key: 'ArrowDown' }); // -> index 1 (SK하이닉스)
      fireEvent.keyDown(input, { key: 'Enter' });

      await waitFor(() => {
        expect(useStore.getState().basket.items.some((i) => i.ticker === '000660')).toBe(true);
      });
      expect(useStore.getState().basket.items.some((i) => i.ticker === '005930')).toBe(false);
    });

    it('Esc가 자동완성 드롭다운을 닫는다', async () => {
      searchKRStocks.mockResolvedValue({
        stocks: [{ stk_cd: '005930', stk_nm: '삼성전자', cur_prc: 71000, prdy_ctrt: 1.2, prdy_vrss: 0, trde_qty: 0, trde_prica: 0 }],
        total: 1,
      });
      render(<DiscoverySection />);
      const input = screen.getByPlaceholderText(/종목코드/);
      fireEvent.change(input, { target: { value: '삼성' } });
      await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());

      fireEvent.keyDown(input, { key: 'Escape' });
      expect(screen.queryByText('삼성전자')).not.toBeInTheDocument();
    });
  });

  describe('per-item remove + clear-all', () => {
    it('개별 항목의 ✕ 버튼이 removeFromBasket을 호출한다', async () => {
      useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
      render(<DiscoverySection />);
      fireEvent.click(screen.getByRole('button', { name: /제거.*005930/ }));
      await waitFor(() => expect(useStore.getState().basket.items).toHaveLength(0));
    });

    it('제거 버튼 클릭은 행 클릭(차트 이동)으로 전파되지 않는다', async () => {
      useStore.setState({ basket: { items: [krItem()], maxItems: 10, isUpdating: false } });
      render(<DiscoverySection />);
      fireEvent.click(screen.getByRole('button', { name: /제거.*005930/ }));
      expect(useStore.getState().chartSymbol).toBeNull();
    });

    it('전체삭제 버튼이 스크래치패드를 비운다', async () => {
      useStore.setState({
        basket: {
          items: [krItem(), krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' })],
          maxItems: 10,
          isUpdating: false,
        },
      });
      render(<DiscoverySection />);
      fireEvent.click(screen.getByRole('button', { name: '전체 삭제' }));
      await waitFor(() => expect(useStore.getState().basket.items).toHaveLength(0));
    });

    it('스크래치패드가 비어있으면 전체분석/전체삭제 버튼을 보여주지 않는다', () => {
      render(<DiscoverySection />);
      expect(screen.queryByRole('button', { name: '전체 삭제' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '전체 분석' })).not.toBeInTheDocument();
    });
  });

  describe('bulk "analyze all" respects the concurrent-slot limit', () => {
    it('가용 슬롯만큼만 분석을 시작하고 시작된 항목만 스크래치패드에서 제거한다', async () => {
      useStore.setState({
        basket: {
          items: [
            krItem({ id: 'item-005930', ticker: '005930', displayName: '삼성전자' }),
            krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' }),
          ],
          maxItems: 10,
          isUpdating: false,
        },
        kiwoom: {
          sessions: [],
          activeSessionId: null,
          maxConcurrentSessions: 1,
          stk_cd: '',
          stk_nm: null,
          status: 'idle',
          currentStage: null,
          reasoningLog: [],
          analyses: [],
          tradeProposal: null,
          awaitingApproval: false,
          activePosition: null,
          error: null,
          history: [],
        },
      });
      mockStart.mockResolvedValue({ sessionId: 'session-limited', duplicate: false, positionExists: false });

      render(<DiscoverySection />);
      fireEvent.click(screen.getByRole('button', { name: '전체 분석' }));

      await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
      expect(mockStart).toHaveBeenCalledWith('kiwoom', '005930', '삼성전자');

      await waitFor(() => {
        const tickers = useStore.getState().basket.items.map((i) => i.ticker);
        expect(tickers).toEqual(['000660']);
      });
    });
  });

  describe('API-not-configured warning banner', () => {
    it('KR 항목이 있고 Kiwoom API 미등록이면 경고 배너를 보여주고, 클릭 시 설정 모달을 연다', () => {
      useStore.setState({
        upbitApiConfigured: true,
        kiwoomApiConfigured: false,
        basket: { items: [krItem()], maxItems: 10, isUpdating: false },
      });
      render(<DiscoverySection />);
      expect(screen.getByText(/Kiwoom API 미등록/)).toBeInTheDocument();

      fireEvent.click(screen.getByText('설정으로 이동'));
      expect(useStore.getState().showSettingsModal).toBe(true);
    });

    it('필요한 API가 모두 등록되어 있으면 경고 배너를 보여주지 않는다', () => {
      useStore.setState({
        upbitApiConfigured: true,
        kiwoomApiConfigured: true,
        basket: { items: [krItem()], maxItems: 10, isUpdating: false },
      });
      render(<DiscoverySection />);
      expect(screen.queryByText(/API 미등록/)).not.toBeInTheDocument();
    });
  });
});
