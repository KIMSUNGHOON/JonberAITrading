/**
 * WatchlistPanel had a KR (kiwoom) early-return that skipped price refresh
 * entirely — the poll effect only ever handled `activeMarket === 'coin'`, so
 * KR basket rows froze at whatever price they were added at. That was fixed
 * with a per-symbol getKRStockTicker loop (P0-T4 stopgap). These tests now
 * pin the P1-7 follow-up: KR items refresh via ONE getKRStockTickers batch
 * call per poll (not N per-symbol calls), the coin path is untouched, and a
 * per-code null in the batch response doesn't blank/crash the panel.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getCoinTickers = vi.fn();
const getKRStockTickers = vi.fn();
vi.mock('@/api/client', () => ({
  getCoinTickers: (...a: unknown[]) => getCoinTickers(...a),
  getKRStockTickers: (...a: unknown[]) => getKRStockTickers(...a),
}));

import { useStore } from '@/store';
import { WatchlistPanel } from './WatchlistPanel';

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

function coinItem(overrides: Record<string, unknown> = {}) {
  return {
    id: `item-${overrides.ticker ?? 'KRW-BTC'}`,
    marketType: 'coin' as const,
    ticker: 'KRW-BTC',
    displayName: '비트코인',
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

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    activeMarket: 'kiwoom',
    upbitApiConfigured: false,
    kiwoomApiConfigured: false,
    basket: { items: [], maxItems: 10, isUpdating: false },
  });
});

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

describe('WatchlistPanel — KR price refresh', () => {
  it('갱신 폴 이후 KR 종목의 가격/등락률이 getKRStockTickers 배치 호출로 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });
    getKRStockTickers.mockResolvedValue({
      tickers: { '005930': krTicker() },
      total: 1,
    });

    render(<WatchlistPanel />);

    await waitFor(() => expect(getKRStockTickers).toHaveBeenCalledWith(['005930']));
    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    expect(screen.getByText('+1.23%')).toBeInTheDocument();
  });

  it('여러 KR 종목이 있어도 배치 호출은 한 번만 발생한다 (N건이 아니라 1건)', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
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

    render(<WatchlistPanel />);

    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    expect(screen.getByText('₩150,000')).toBeInTheDocument();
    // Exactly ONE batch call for both symbols — not one call per symbol.
    expect(getKRStockTickers).toHaveBeenCalledTimes(1);
    expect(getKRStockTickers).toHaveBeenCalledWith(['005930', '000660']);
  });

  it('kiwoomApiConfigured가 false면 KR 폴을 시도하지 않는다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: false,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });

    render(<WatchlistPanel />);

    await new Promise((r) => setTimeout(r, 0));
    expect(getKRStockTickers).not.toHaveBeenCalled();
  });

  it('일부 KR 종목이 배치 응답에서 null이어도 패널이 죽지 않고 나머지는 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      basket: {
        items: [krItem({ id: 'item-005930', ticker: '005930', displayName: '삼성전자' }),
                krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' })],
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

    render(<WatchlistPanel />);

    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    // Null ticker keeps its last-known (missing) price — honest DASH, no crash.
    expect(screen.getByText('SK하이닉스')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('배치 호출 자체가 실패해도 패널이 죽지 않는다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });
    getKRStockTickers.mockRejectedValue(new Error('kiwoom rate limit'));

    render(<WatchlistPanel />);

    await waitFor(() => expect(getKRStockTickers).toHaveBeenCalled());
    // Still renders the row with its last-known (initial) price, no crash.
    expect(screen.getByText('삼성전자')).toBeInTheDocument();
  });
});

describe('WatchlistPanel — coin path unchanged', () => {
  it('coin 종목은 기존처럼 getCoinTickers로 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'coin',
      upbitApiConfigured: true,
      basket: { items: [coinItem()], maxItems: 10, isUpdating: false },
    });
    getCoinTickers.mockResolvedValue({
      tickers: [
        {
          market: 'KRW-BTC',
          trade_price: 50_000_000,
          change: 'RISE',
          change_rate: 0.012,
          change_price: 600_000,
          high_price: 50_500_000,
          low_price: 49_000_000,
          trade_volume: 10,
          acc_trade_price_24h: 1_000_000_000,
          timestamp: '2026-07-13T00:00:00Z',
        },
      ],
      total: 1,
    });

    render(<WatchlistPanel />);

    await waitFor(() => expect(getCoinTickers).toHaveBeenCalledWith(['KRW-BTC']));
    await waitFor(() => expect(screen.getByText('₩50,000,000')).toBeInTheDocument());
    expect(screen.getByText('+1.20%')).toBeInTheDocument();
    expect(getKRStockTickers).not.toHaveBeenCalled();
  });
});
