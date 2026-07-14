import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { OrderTicketRail } from './OrderTicketRail';

// Controlled store: `useStore` runs the real selector against `mockState`, so
// `mockState` must carry the same shape `getMarketData` expects
// (`activeMarket` + the per-market slice), not the resolved selector outputs.
let mockState: Record<string, unknown>;
vi.mock('@/store', async () => {
  const actual = await vi.importActual<any>('@/store');
  return {
    ...actual,
    useStore: (selector: (s: any) => unknown) => selector(mockState),
  };
});
vi.mock('@/hooks/useMarketHours', () => ({
  useMarketHours: () => ({ status: null, countdownFormatted: '', nextEventFormatted: '' }),
}));

// `submitApproval` is reused as-is (Task 4 wires the decision handler to the
// EXISTING approval endpoint — no new/changed execution). The arrow-function
// indirection defers the read of `submitApproval` until call time, so it's
// safe regardless of vi.mock hoisting order.
const submitApproval = vi.fn().mockResolvedValue({});
vi.mock('@/api/client', () => ({ submitApproval: (...a: unknown[]) => submitApproval(...a) }));

beforeEach(() => {
  mockState = {
    activeMarket: 'kiwoom',
    kiwoom: {
      tradeProposal: null,
      activeSessionId: null,
      status: 'idle',
      currentStage: null,
      sessions: [],
    },
  };
});

describe('OrderTicketRail — idle', () => {
  it('shows NO PENDING ORDER when no active proposal', () => {
    render(<OrderTicketRail />);
    expect(screen.getByText('NO PENDING ORDER')).toBeInTheDocument();
  });
});

describe('OrderTicketRail — active', () => {
  it('renders the ticket: ACTION, symbol, SL/TP, risk, buttons', () => {
    mockState = {
      activeMarket: 'kiwoom',
      kiwoom: {
        tradeProposal: {
          id: 'p1',
          stk_cd: '005930',
          stk_nm: '삼성전자',
          action: 'BUY',
          quantity: 10,
          entry_price: 100,
          stop_loss: 90,
          take_profit: 120,
          risk_score: 5,
          position_size_pct: 10,
          rationale: 'Strong momentum with support at 95.',
          bull_case: 'Upside case',
          bear_case: 'Downside case',
          created_at: new Date().toISOString(),
        },
        activeSessionId: 'session-1',
        status: 'awaiting_approval',
        currentStage: null,
        awaitingApproval: true,
        sessions: [],
      },
    };
    render(<OrderTicketRail />);
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText('삼성전자')).toBeInTheDocument();
    expect(screen.getByText('Medium Risk')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reject|re-analyze/i })).toBeInTheDocument();
  });
});

describe('OrderTicketRail — decisions', () => {
  beforeEach(() => {
    submitApproval.mockClear();
    mockState = {
      activeMarket: 'kiwoom',
      kiwoom: {
        tradeProposal: {
          id: 'p1',
          stk_cd: '005930',
          stk_nm: '삼성전자',
          action: 'BUY',
          quantity: 10,
          entry_price: 100,
          stop_loss: 90,
          take_profit: 120,
          risk_score: 5,
          position_size_pct: 10,
          rationale: 'Strong momentum with support at 95.',
          bull_case: 'Upside case',
          bear_case: 'Downside case',
          created_at: new Date().toISOString(),
        },
        activeSessionId: 'sess-1',
        status: 'awaiting_approval',
        currentStage: null,
        awaitingApproval: true,
        sessions: [],
      },
      setAwaitingApproval: vi.fn(),
      setStatus: vi.fn(),
      setError: vi.fn(),
      addChatMessage: vi.fn(),
    };
  });

  it('Approve calls submitApproval with {session_id, approved, feedback}', async () => {
    render(<OrderTicketRail />);
    fireEvent.click(screen.getByRole('button', { name: /approve/i }));
    expect(submitApproval).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 'sess-1', decision: 'approved' }),
    );
  });

  it('the focus shortcut moves focus to Approve WITHOUT submitting', () => {
    render(<OrderTicketRail />);
    fireEvent.keyDown(window, { key: 'Enter', metaKey: true }); // ⌘⏎ focuses Approve
    expect(submitApproval).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /approve/i })).toHaveFocus();
  });

  // Task 7 (P2 funnel-consolidation): reject/cancel coverage that used to
  // live on OperationsPanel's now-defunct 승인대기 buttons (they called this
  // SAME submitApproval endpoint) — pinned here instead, since the rail is
  // now the ONE surface that submits an approval decision.
  it('Reject calls submitApproval with {session_id, rejected}', async () => {
    render(<OrderTicketRail />);
    fireEvent.click(screen.getByRole('button', { name: /reject|re-analyze/i }));
    expect(submitApproval).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 'sess-1', decision: 'rejected' }),
    );
  });

  it('Cancel Analysis calls submitApproval with {session_id, cancelled}', async () => {
    render(<OrderTicketRail />);
    fireEvent.click(screen.getByRole('button', { name: /cancel analysis/i }));
    expect(submitApproval).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 'sess-1', decision: 'cancelled' }),
    );
  });

  it('a rejected submitApproval surfaces the error via setError (no silent failure)', async () => {
    submitApproval.mockRejectedValueOnce(new Error('network down'));
    render(<OrderTicketRail />);
    fireEvent.click(screen.getByRole('button', { name: /approve/i }));
    await waitFor(() => expect(mockState.setError).toHaveBeenCalledWith('network down'));
  });
});

describe('OrderTicketRail — R3 autonomous mode', () => {
  // Active-proposal state with a kiwoom multi-session entry carrying the
  // auto-approve deadline (the countdown reads sessions[], not legacy fields).
  function activeAutonomousState(autoApproveAt: string | null) {
    return {
      activeMarket: 'kiwoom',
      tradingModes: { kiwoom: 'autonomous', coin: 'hitl' },
      kiwoom: {
        tradeProposal: {
          id: 'p1',
          stk_cd: '005930',
          stk_nm: '삼성전자',
          action: 'BUY',
          quantity: 10,
          entry_price: 100,
          stop_loss: 90,
          take_profit: 120,
          risk_score: 5,
          position_size_pct: 10,
          rationale: 'Strong momentum with support at 95.',
          bull_case: 'Upside case',
          bear_case: 'Downside case',
          created_at: new Date().toISOString(),
        },
        activeSessionId: 'sess-1',
        status: 'awaiting_approval',
        currentStage: null,
        awaitingApproval: true,
        sessions: [{ sessionId: 'sess-1', autoApproveAt }],
      },
    };
  }

  it('renders the AUTONOMOUS chip in idle state when the active market mode is autonomous', () => {
    mockState.tradingModes = { kiwoom: 'autonomous', coin: 'hitl' };
    render(<OrderTicketRail />);
    expect(screen.getByText('AUTONOMOUS')).toBeInTheDocument();
    expect(screen.getByText('NO PENDING ORDER')).toBeInTheDocument();
  });

  it('renders no chip when trading modes are not loaded (null)', () => {
    mockState.tradingModes = null;
    render(<OrderTicketRail />);
    expect(screen.queryByText('AUTONOMOUS')).not.toBeInTheDocument();
  });

  it('renders no chip when the active market mode is hitl', () => {
    mockState.tradingModes = { kiwoom: 'hitl', coin: 'autonomous' };
    render(<OrderTicketRail />);
    expect(screen.queryByText('AUTONOMOUS')).not.toBeInTheDocument();
  });

  it('keeps the chip and shows a countdown on an active proposal with a future autoApproveAt', () => {
    mockState = activeAutonomousState(new Date(Date.now() + 30_000).toISOString());
    render(<OrderTicketRail />);
    expect(screen.getByText('AUTONOMOUS')).toBeInTheDocument();
    expect(screen.getByText(/자율 승인까지 \d+초/)).toBeInTheDocument();
    // The veto stays the EXISTING buttons — no new controls.
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
  });

  it('shows the processing message once the deadline has passed', () => {
    mockState = activeAutonomousState(new Date(Date.now() - 1_000).toISOString());
    render(<OrderTicketRail />);
    expect(screen.getByText('자율 승인 처리 중…')).toBeInTheDocument();
  });

  it('shows no countdown when the active session has no autoApproveAt', () => {
    mockState = activeAutonomousState(null);
    render(<OrderTicketRail />);
    expect(screen.queryByText(/자율 승인/)).not.toBeInTheDocument();
  });
});
