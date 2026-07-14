/**
 * DebatePanel was a REST-poll-only decorative tile (no WS, no start action,
 * no deep link — always '—' when the coordinator was dormant, its default).
 * P2 T6 revives it: live votes/consensus via the already-built
 * useAgentChatWebSocket hook, a "토론 시작" action that calls the coordinator
 * launch path, and a deep link into the /agent-chat session viewer.
 */
import { it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';

const getAgentChatActiveDiscussions = vi.fn();
const getAgentChatSessions = vi.fn();
const getAgentChatSessionDetail = vi.fn();
const getAgentChatStatus = vi.fn();
const startAgentChat = vi.fn().mockResolvedValue({ status: 'started', message: 'ok', check_interval: 300 });
vi.mock('@/api/client', () => ({
  getAgentChatActiveDiscussions: (...a: unknown[]) => getAgentChatActiveDiscussions(...a),
  getAgentChatSessions: (...a: unknown[]) => getAgentChatSessions(...a),
  getAgentChatSessionDetail: (...a: unknown[]) => getAgentChatSessionDetail(...a),
  getAgentChatStatus: (...a: unknown[]) => getAgentChatStatus(...a),
  startAgentChat: (...a: unknown[]) => startAgentChat(...a),
}));

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

// Captures the options object passed by DebatePanel on its most recent
// render, so tests can invoke onVote/onStatusChange/onDecision directly to
// simulate a WS push (mirrors OrderTicketRail/NotificationBell's convention
// of driving mocked hooks by capturing their call args).
const useAgentChatWebSocketMock = vi.fn((_opts?: unknown) => ({
  isConnected: true,
  connectionState: 'connected' as const,
  connect: vi.fn(),
  disconnect: vi.fn(),
  lastError: null,
}));
vi.mock('@/hooks/useAgentChatWebSocket', () => ({
  useAgentChatWebSocket: (opts?: unknown) => useAgentChatWebSocketMock(opts),
}));

import { DebatePanel } from './DebatePanel';

function lastWsOpts(): any {
  const calls = useAgentChatWebSocketMock.mock.calls;
  return calls[calls.length - 1]?.[0];
}

const BASE_DETAIL = {
  id: 's1',
  ticker: '005930',
  stock_name: '삼성전자',
  status: 'voting' as const,
  started_at: null,
  ended_at: null,
  rounds: [],
  messages: [],
  votes: [
    { agent_type: 'technical' as const, vote: 'BUY' as const, confidence: 0.7, weight: 0.3, weighted_score: 0.5, reasoning: 'r' },
  ],
  consensus_level: 0.4,
  decision: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  startAgentChat.mockResolvedValue({ status: 'started', message: 'ok', check_interval: 300 });
  useAgentChatWebSocketMock.mockReturnValue({
    isConnected: true,
    connectionState: 'connected' as const,
    connect: vi.fn(),
    disconnect: vi.fn(),
    lastError: null,
  });
});

it('활성 세션의 실시간 votes/consensus를 렌더하고, WS vote/decision 프레임 수신 시 갱신한다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({
    discussions: [{ ticker: '005930', stock_name: '삼성전자', session_id: 's1', status: 'voting', started_at: null }],
    count: 1,
  });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatSessionDetail.mockResolvedValue(BASE_DETAIL);
  getAgentChatStatus.mockResolvedValue({
    is_running: true, active_discussions: 1, total_sessions: 3,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText('BUY')).toBeInTheDocument());
  expect(screen.getByText('40%')).toBeInTheDocument();
  expect(screen.getByText('삼성전자')).toBeInTheDocument();
  expect(screen.getByText('LIVE')).toBeInTheDocument(); // isConnected: true from the mocked hook

  // Simulate a live WS vote frame for a second analyst.
  const opts = lastWsOpts();
  act(() => opts.onVote({
    agent_type: 'risk', vote: 'SELL', confidence: 0.6, weight: 0.2, weighted_score: -0.3, reasoning: 'r2',
  }));
  await waitFor(() => expect(screen.getByText('SELL')).toBeInTheDocument());
  // Original technical vote is untouched (upsert-by-agent, not replace-all).
  expect(screen.getByText('BUY')).toBeInTheDocument();

  // Simulate a live WS decision frame — decision + consensus both update.
  act(() => opts.onDecision({
    action: 'BUY', confidence: 0.85, consensus_level: 0.82, entry_price: null,
    stop_loss: null, take_profit: null, quantity: null, key_factors: [],
    dissenting_opinions: [], rationale: 'r',
  }));
  await waitFor(() => expect(screen.getByText('82%')).toBeInTheDocument());
  expect(screen.getByText('BUY', { selector: 'span.text-ink' })).toBeInTheDocument();
});

it('활성/최근 세션이 없고 코디네이터가 미기동이면 정직한 빈 상태 + 토론 시작 유도를 보여준다 (죽은 —타일 금지)', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 0,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText(/코디네이터 미기동/)).toBeInTheDocument());
  expect(screen.getByRole('button', { name: '토론 시작' })).toBeInTheDocument();
  expect(getAgentChatSessionDetail).not.toHaveBeenCalled();
});

it('"토론 시작" 클릭 시 코디네이터 기동 경로(startAgentChat)를 호출한다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 0,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  const startButton = await screen.findByRole('button', { name: '토론 시작' });
  fireEvent.click(startButton);
  await waitFor(() => expect(startAgentChat).toHaveBeenCalled());
});

it('코디네이터가 실행 중이고 활성 토론이 없으면 시작 버튼 없이 대기 상태만 보여준다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: true, active_discussions: 0, total_sessions: 2,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: '2026-07-14T00:00:00Z',
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText(/코디네이터 실행 중/)).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: '토론 시작' })).not.toBeInTheDocument();
});

it('"세션 보기" 클릭 시 /agent-chat 세션 뷰어로 딥링크한다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({
    discussions: [{ ticker: '005930', stock_name: '삼성전자', session_id: 's1', status: 'voting', started_at: null }],
    count: 1,
  });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatSessionDetail.mockResolvedValue(BASE_DETAIL);
  getAgentChatStatus.mockResolvedValue({
    is_running: true, active_discussions: 1, total_sessions: 3,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  const viewButton = await screen.findByRole('button', { name: '세션 보기 →' });
  fireEvent.click(viewButton);
  expect(navigate).toHaveBeenCalledWith('/agent-chat');
});
