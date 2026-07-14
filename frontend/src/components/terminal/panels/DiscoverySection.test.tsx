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

vi.mock('@/api/client', () => ({
  startScan: (...a: unknown[]) => startScan(...a),
  pauseScan: (...a: unknown[]) => pauseScan(...a),
  resumeScan: (...a: unknown[]) => resumeScan(...a),
  stopScan: (...a: unknown[]) => stopScan(...a),
  getScanProgress: (...a: unknown[]) => getScanProgress(...a),
  getScanResults: (...a: unknown[]) => getScanResults(...a),
  addToWatchList: (...a: unknown[]) => addToWatchList(...a),
  searchKRStocks: (...a: unknown[]) => searchKRStocks(...a),
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
  useStore.setState({ basket: { items: [], maxItems: 10, isUpdating: false } });
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

  it('coin 항목의 [승격▲]은 비활성화된다 (서버 워치리스트는 KR 전용)', async () => {
    useStore.setState({
      basket: {
        items: [krItem({ id: 'item-coin', marketType: 'coin', ticker: 'KRW-BTC', displayName: '비트코인' })],
        maxItems: 10,
        isUpdating: false,
      },
    });
    render(<DiscoverySection />);
    fireEvent.click(screen.getByRole('button', { name: /승격.*KRW-BTC/ }));
    expect(addToWatchList).not.toHaveBeenCalled();
    await waitFor(() => expect(getScanProgress).toHaveBeenCalled());
  });

  it('6자리 종목코드 입력 후 추가 버튼이 스크래치패드에 항목을 추가한다', async () => {
    render(<DiscoverySection />);
    fireEvent.change(screen.getByPlaceholderText(/종목코드/), { target: { value: '000660' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    await waitFor(() => expect(useStore.getState().basket.items.some((i) => i.ticker === '000660')).toBe(true));
  });
});
