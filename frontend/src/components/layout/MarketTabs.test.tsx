/**
 * MarketTabs — 코인 동결(freeze) fix round 1.
 *
 * 사이드바 → MobileNav(App.tsx에서 무조건 렌더)를 통해 `setActiveMarket('coin')`을
 * 호출할 수 있는 Crypto 탭이 살아 있었다(리뷰 발견, 원래 브리프 Step 5는 데스크톱
 * TerminalShell의 MARKETS 배열만 다뤘다). 이 테스트는 Crypto 탭이 다시 나타나지
 * 않도록 고정한다.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

import { useStore } from '@/store';
import { MarketTabs } from './MarketTabs';

describe('MarketTabs — 코인 동결', () => {
  beforeEach(() => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
    } as never);
  });

  it('Crypto/COIN 탭이 렌더되지 않는다', () => {
    render(<MarketTabs />);
    expect(screen.queryByText('Crypto')).not.toBeInTheDocument();
    expect(screen.queryByText('COIN')).not.toBeInTheDocument();
  });

  it('Stock 탭 하나만 렌더된다', () => {
    render(<MarketTabs />);
    expect(screen.getByText('Stock')).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });
});
