import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TradingModeSection } from './TradingModeSection';

// Controlled store: `useStore` runs the real selector against `mockState`,
// mirroring the pattern used by OrderTicketRail.test.tsx. The component's
// `setStoreTradingModes` mock mutates `mockState` directly (no real zustand
// subscription), and a subsequent local-state update in the component
// (`setLoadFailed`) triggers a re-render that picks up the mutation.
let mockState: Record<string, unknown>;
vi.mock('@/store', async () => {
  const actual = await vi.importActual<any>('@/store');
  return {
    ...actual,
    useStore: (selector: (s: any) => unknown) => selector(mockState),
  };
});

const getTradingMode = vi.fn();
const setTradingMode = vi.fn();
vi.mock('@/api/client', () => ({
  getTradingMode: (...a: unknown[]) => getTradingMode(...a),
  setTradingMode: (...a: unknown[]) => setTradingMode(...a),
}));

beforeEach(() => {
  getTradingMode.mockReset();
  setTradingMode.mockReset();
  getTradingMode.mockResolvedValue({ kiwoom: 'hitl', master_enabled: false });
  mockState = {
    tradingModes: { kiwoom: 'hitl' },
    autonomyMasterEnabled: false,
    setTradingModes: vi.fn((resp) => {
      mockState.tradingModes = { kiwoom: resp.kiwoom };
      mockState.autonomyMasterEnabled = resp.master_enabled;
    }),
  };
});

describe('TradingModeSection — master gate OFF does not disable intent-setting', () => {
  it('HITL and AUTONOMOUS buttons are enabled (clickable) when masterEnabled is false', async () => {
    render(<TradingModeSection onError={vi.fn()} />);
    await waitFor(() => expect(getTradingMode).toHaveBeenCalled());
    const buttons = screen.getAllByRole('button', { name: /^(hitl|autonomous)$/i });
    // 코인 스택 제거(2026-08-01) 이후 마켓은 kiwoom 하나뿐 — 1 market x 2 modes.
    expect(buttons.length).toBe(2);
    buttons.forEach((btn) => expect(btn).not.toBeDisabled());
  });

  it('selecting a mode calls setTradingMode', async () => {
    setTradingMode.mockResolvedValue({ kiwoom: 'autonomous', master_enabled: false });
    render(<TradingModeSection onError={vi.fn()} />);
    await waitFor(() => expect(getTradingMode).toHaveBeenCalled());
    const autonomousButtons = screen.getAllByRole('button', { name: /^autonomous$/i });
    fireEvent.click(autonomousButtons[0]); // kiwoom row is the only row
    await waitFor(() => expect(setTradingMode).toHaveBeenCalledWith('kiwoom', 'autonomous'));
  });

  it('shows the env-requirement note when masterEnabled is false and a market is set to autonomous', async () => {
    // Pre-render store state IS the final state here — the mount effect's
    // fetch resolves to the same values, so this doesn't depend on a
    // same-value React state update (setLoadFailed(false)) actually forcing
    // a re-render (React bails out via Object.is when it wouldn't).
    mockState.tradingModes = { kiwoom: 'autonomous' };
    mockState.autonomyMasterEnabled = false;
    getTradingMode.mockResolvedValue({ kiwoom: 'autonomous', master_enabled: false });
    render(<TradingModeSection onError={vi.fn()} />);
    await waitFor(() => expect(getTradingMode).toHaveBeenCalled());
    expect(
      screen.getByText(/자율 모드 설정됨.*AUTONOMY_ENABLED=true.*재시작/)
    ).toBeInTheDocument();
  });

  it('does not show the env-requirement note when no market is set to autonomous', async () => {
    mockState.tradingModes = { kiwoom: 'hitl' };
    mockState.autonomyMasterEnabled = false;
    getTradingMode.mockResolvedValue({ kiwoom: 'hitl', master_enabled: false });
    render(<TradingModeSection onError={vi.fn()} />);
    await waitFor(() => expect(getTradingMode).toHaveBeenCalled());
    expect(screen.queryByText(/자율 모드 설정됨/)).not.toBeInTheDocument();
  });
});
