/**
 * TradesPage — 코인 동결(freeze) fix round 1.
 *
 * PositionsPage와 동일한 결함이 있었다: Crypto Trades 섹션이
 * `activeMarket === 'coin' || upbitApiConfigured`로 감싸여 있어, activeMarket이
 * 'coin'이 될 필요조차 없이 `upbitApiConfigured`만 true면(예: 과거에 Upbit 키를
 * 설정해 둔 계정) 렌더됐다 — CoinTradeHistory가 이 커밋으로 언마운트된 `/coin/trades`
 * 를 호출하는 라이브 브레이크(리뷰 발견, 원래 브리프는 이 페이지를 다루지 않았다).
 * KR 섹션 게이트도 PositionsPage와 같은 이유로 `kiwoomApiConfigured` 단독으로
 * 단순화했다 — activeMarket은 동결 이후 사실상 항상 'kiwoom'이라 원래 OR 조건이
 * 상시 참이 되어 미설정 상태에서도 계좌 패널이 뜨는 모순이 있었다.
 *
 * Task 6 fix round 1 (코디네이터 리뷰): `upbitApiConfigured` 자체가 스토어에서
 * 제거됐다(코인 스택 제거 이후 프로덕션 리더 0 — 실제 Upbit UI는 SettingsModal이
 * getUpbitApiStatus()를 로컬 상태로 직접 소비했다). "Upbit이 설정되어
 * 있어도(레거시 상태)" 테스트는 이제 존재하지 않는 필드를 흉내 내는 것이므로
 * 제거한다 — Crypto Trades 미노출은 activeMarket/kiwoomApiConfigured 두
 * 테스트만으로 이미 고정돼 있다.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/components/kiwoom', () => ({
  KRStockTradeHistory: () => <div data-testid="kiwoom-trades" />,
}));
vi.mock('@/hooks/useNav', () => ({ useGoTo: () => vi.fn() }));

import { useStore } from '@/store';
import { TradesPage } from './TradesPage';

describe('TradesPage — 코인 동결', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
    } as never);
  });

  it('KR 섹션에 거래내역을 렌더한다', async () => {
    render(<TradesPage />);
    await waitFor(() => expect(screen.getByTestId('kiwoom-trades')).toBeInTheDocument());
  });

  it('Crypto Trades 섹션은 렌더되지 않는다', async () => {
    render(<TradesPage />);
    await waitFor(() => expect(screen.getByTestId('kiwoom-trades')).toBeInTheDocument());
    expect(screen.queryByText('Crypto Trades')).not.toBeInTheDocument();
  });

  it('키움 미설정이면 KR 섹션도 없고 빈 상태 안내만 보인다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: false,
    } as never);
    render(<TradesPage />);
    await waitFor(() => expect(screen.queryByTestId('kiwoom-trades')).not.toBeInTheDocument());
    expect(screen.getByText(/Configure your API keys/)).toBeInTheDocument();
  });
});
