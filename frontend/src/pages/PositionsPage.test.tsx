/**
 * PositionsPage — 기간 손익 요약 스트립 배치.
 *
 * 스트립은 Korean Stock Positions 섹션 안, 계좌·보유 카드 **위**에 있어야 한다.
 * 처음 구현 때는 Dashboard 모자이크의 POSITIONS 타일(PositionsPanel)에 붙었는데,
 * 내비의 Positions가 여는 화면은 이 페이지(App.tsx의 `<Route path="positions">`)라
 * 정작 사용자가 보는 곳에는 없었다. 이 테스트가 그 회귀를 막는다.
 *
 * 키움 미설정 상태에서는 KR 섹션 자체가 렌더되지 않으므로 스트립도 없어야 한다 —
 * 이 엔드포인트는 키움 브로커 기반이다.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/components/terminal/panels/PnlSummaryStrip', () => ({
  PnlSummaryStrip: () => <div data-testid="pnl-strip" />,
}));
vi.mock('@/components/kiwoom', () => ({
  KiwoomPositionPanel: () => <div data-testid="kiwoom-holdings" />,
  KiwoomAccountBalance: () => <div data-testid="kiwoom-account" />,
  KiwoomOpenOrders: () => <div />,
}));
vi.mock('@/hooks/useNav', () => ({ useGoTo: () => vi.fn() }));

import { useStore } from '@/store';
import { PositionsPage } from './PositionsPage';

describe('PositionsPage — 손익 요약 스트립', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      upbitApiConfigured: false,
    } as never);
  });

  it('KR 섹션에 스트립을 계좌·보유 카드와 함께 렌더한다', async () => {
    render(<PositionsPage />);

    await waitFor(() => expect(screen.getByTestId('pnl-strip')).toBeInTheDocument());
    expect(screen.getByTestId('kiwoom-account')).toBeInTheDocument();
    expect(screen.getByTestId('kiwoom-holdings')).toBeInTheDocument();
  });

  it('스트립은 계좌·보유 카드보다 앞선다', async () => {
    const { container } = render(<PositionsPage />);

    await waitFor(() => expect(screen.getByTestId('pnl-strip')).toBeInTheDocument());
    const order = Array.from(
      container.querySelectorAll('[data-testid]'),
    ).map((el) => el.getAttribute('data-testid'));
    expect(order.indexOf('pnl-strip')).toBeLessThan(order.indexOf('kiwoom-account'));
  });

  it('키움 미설정이면 KR 섹션도 스트립도 없다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: false,
      upbitApiConfigured: false,
    } as never);
    render(<PositionsPage />);

    await waitFor(() => expect(screen.queryByTestId('kiwoom-account')).not.toBeInTheDocument());
    expect(screen.queryByTestId('pnl-strip')).not.toBeInTheDocument();
  });
});
