/**
 * /trading's "결정 계층 · Agent Coordinator" card used to Start/Stop the
 * agent-chat coordinator directly — the SAME coordinator that /agent-chat's
 * Status Card and the dashboard's DebatePanel could also start/stop, each
 * with a different label (R5-P2-UX B1 audit finding). That let a user flip
 * the switch here without realizing two other screens control the exact
 * same thing.
 *
 * B1 demotes this card to read-only: a running/stopped status chip (+
 * last-check freshness) and a deep link to /agent-chat, which is now the
 * single authoritative control. This card must never call
 * `startAgentChat`/`stopAgentChat` itself. The "실행 계층 · Execution" card
 * is a separate switch (order-queue processing) and is unaffected — its
 * Start/Stop must keep working.
 */
import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

const getAgentChatStatus = vi.fn();
const getTradingStatus = vi.fn();
const startAgentChat = vi.fn();
const stopAgentChat = vi.fn();
const startTrading = vi.fn();
const stopTrading = vi.fn();
const pauseTrading = vi.fn();
const resumeTrading = vi.fn();
const getTradingRiskParams = vi.fn();
vi.mock('@/api/client', () => ({
  getAgentChatStatus: (...a: unknown[]) => getAgentChatStatus(...a),
  getTradingStatus: (...a: unknown[]) => getTradingStatus(...a),
  // NOT imported by TradingDashboard anymore — kept here only so a future
  // regression (re-adding a direct start/stop call) has something to
  // assert against; the demotion test below asserts these are NEVER called.
  startAgentChat: (...a: unknown[]) => startAgentChat(...a),
  stopAgentChat: (...a: unknown[]) => stopAgentChat(...a),
  startTrading: (...a: unknown[]) => startTrading(...a),
  stopTrading: (...a: unknown[]) => stopTrading(...a),
  pauseTrading: (...a: unknown[]) => pauseTrading(...a),
  resumeTrading: (...a: unknown[]) => resumeTrading(...a),
  apiClient: { getTradingRiskParams: (...a: unknown[]) => getTradingRiskParams(...a) },
}));

vi.mock('@/store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ autonomyMasterEnabled: false, tradingModes: { kiwoom: 'hitl', coin: 'hitl' } }),
}));

// Out of scope for this card's behavior — stub it out so this test file
// doesn't have to satisfy its own getTradingMode/setTradingMode deps.
vi.mock('@/components/settings/TradingModeSection', () => ({
  TradingModeSection: () => <div data-testid="trading-mode-section-stub" />,
}));

import TradingDashboard from './TradingDashboard';

beforeEach(() => {
  vi.clearAllMocks();
  getTradingStatus.mockResolvedValue({
    mode: 'paper', is_active: false, started_at: null, daily_trades: 0, max_daily_trades: 20,
  });
  getTradingRiskParams.mockResolvedValue({});
});

function brainCard(): HTMLElement {
  const heading = screen.getByText('결정 계층 · Agent Coordinator');
  const card = heading.closest('.bg-card');
  if (!card) throw new Error('brain card not found');
  return card as HTMLElement;
}

it('결정 계층 카드는 Start/Stop 없이 상태칩 + /agent-chat 딥링크만 보여준다', async () => {
  getAgentChatStatus.mockResolvedValue({
    is_running: true, active_discussions: 2, total_sessions: 5,
    check_interval_minutes: 5, max_concurrent_discussions: 3,
    last_check_at: '2026-07-14T00:00:00Z',
  });

  render(<TradingDashboard />);

  await waitFor(() => expect(getAgentChatStatus).toHaveBeenCalled());
  const card = await waitFor(() => brainCard());
  await waitFor(() => expect(within(card).getByText(/가동 중/)).toBeInTheDocument());

  // No Start/Stop control for the coordinator on this screen anymore.
  expect(within(card).queryByRole('button', { name: /^start$/i })).not.toBeInTheDocument();
  expect(within(card).queryByRole('button', { name: /^stop$/i })).not.toBeInTheDocument();

  // Read-only freshness + deep link instead.
  expect(within(card).getByText(/마지막 점검/)).toBeInTheDocument();
  const link = within(card).getByRole('button', { name: '/agent-chat에서 제어 →' });

  fireEvent.click(link);
  expect(navigate).toHaveBeenCalledWith('/agent-chat');
  expect(startAgentChat).not.toHaveBeenCalled();
  expect(stopAgentChat).not.toHaveBeenCalled();
});

it('코디네이터 정지 상태에서도 결정 계층 카드에 Start 버튼이 없다 (SSOT=/agent-chat)', async () => {
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 5,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<TradingDashboard />);

  await waitFor(() => expect(getAgentChatStatus).toHaveBeenCalled());
  const card = await waitFor(() => brainCard());
  await waitFor(() =>
    expect(within(card).getByText('정지 — 워치리스트 감시 없음')).toBeInTheDocument(),
  );
  expect(within(card).queryByRole('button', { name: /^start$/i })).not.toBeInTheDocument();
  expect(within(card).getByRole('button', { name: '/agent-chat에서 제어 →' })).toBeInTheDocument();
});

it('실행 계층(Execution) 카드의 Start/Stop은 이 변경과 무관하게 그대로 동작한다', async () => {
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 0,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });
  startTrading.mockResolvedValue({});

  render(<TradingDashboard />);

  await waitFor(() => expect(getTradingStatus).toHaveBeenCalled());
  const execHeading = screen.getByText('실행 계층 · Execution');
  const execCard = execHeading.closest('.bg-card') as HTMLElement;
  const startButton = within(execCard).getByRole('button', { name: /^start$/i });
  fireEvent.click(startButton);
  await waitFor(() => expect(startTrading).toHaveBeenCalled());
});
