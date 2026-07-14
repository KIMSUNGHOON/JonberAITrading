/**
 * DebatePanel was a REST-poll-only decorative tile (no WS, no start action,
 * no deep link — always '—' when the coordinator was dormant, its default).
 * P2 T6 revived it: live votes/consensus via the already-built
 * useAgentChatWebSocket hook, a deep link into the /agent-chat session
 * viewer, and (at the time) a "토론 시작" action calling the coordinator
 * launch path directly.
 *
 * R5-P2-UX B1 demotes that start action: the SAME coordinator on/off was
 * also controllable from /agent-chat's Status Card and /trading's "결정
 * 계층" card — three switches, one coordinator, no way to tell they were the
 * same. /agent-chat is now the single authoritative control; this tile only
 * shows a read-only running/stopped chip (+ last-check freshness) and a
 * deep link to go control it there. It never calls `startAgentChat` itself.
 */
import { it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';

const POLL_MS = 5_000;

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
  // NOT imported by DebatePanel anymore — kept here only so a future
  // regression (re-adding a direct start call) has something to assert
  // against; the demotion tests below assert this mock is NEVER called.
  startAgentChat: (...a: unknown[]) => startAgentChat(...a),
}));

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

// Captures the options object passed by DebatePanel on its most recent
// render, so tests can invoke onVote/onStatusChange/onDecision directly to
// simulate a WS push (mirrors OrderTicketRail/NotificationBell's convention
// of driving mocked hooks by capturing their call args).
//
// Default behavior approximates the real hook: "connected" only when the
// panel actually asked to connect (a non-null sessionId — i.e. the panel
// decided the session is active). Individual tests override via
// `mockImplementation` when they need to force a specific isConnected value
// irrespective of sessionId (e.g. to exercise the REST-poll gating race).
type WsMockReturn = {
  isConnected: boolean;
  connectionState: 'disconnected' | 'connecting' | 'connected' | 'reconnecting';
  connect: () => void;
  disconnect: () => void;
  lastError: string | null;
};
function defaultWsMockImpl(opts?: unknown): WsMockReturn {
  const sessionId = (opts as { sessionId?: string | null } | undefined)?.sessionId ?? null;
  return {
    isConnected: Boolean(sessionId),
    connectionState: sessionId ? 'connected' : 'disconnected',
    connect: vi.fn(),
    disconnect: vi.fn(),
    lastError: null,
  };
}
const useAgentChatWebSocketMock = vi.fn(defaultWsMockImpl);
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
  useAgentChatWebSocketMock.mockImplementation(defaultWsMockImpl);
});

afterEach(() => {
  // Safety net: any test that opts into fake timers restores real ones
  // itself, but this guards against a leak into later tests if one throws.
  vi.useRealTimers();
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

it('활성/최근 세션이 없고 코디네이터가 미기동이면 정직한 빈 상태 + 상태칩·딥링크를 보여준다 (죽은 —타일 금지)', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 0,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText(/코디네이터 미기동/)).toBeInTheDocument());
  expect(screen.getByText('STOPPED')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '/agent-chat에서 제어 →' })).toBeInTheDocument();
  // No coordinator start control on this tile anymore (B1 demotion).
  expect(screen.queryByRole('button', { name: '토론 시작' })).not.toBeInTheDocument();
  expect(getAgentChatSessionDetail).not.toHaveBeenCalled();
});

it('"/agent-chat에서 제어" 클릭은 딥링크만 하고 startAgentChat을 호출하지 않는다 (SSOT=/agent-chat)', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 0,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  const controlLink = await screen.findByRole('button', { name: '/agent-chat에서 제어 →' });
  fireEvent.click(controlLink);
  expect(navigate).toHaveBeenCalledWith('/agent-chat');
  expect(startAgentChat).not.toHaveBeenCalled();
});

it('코디네이터가 실행 중이면 RUNNING 상태칩 + 마지막 점검 시각을 보여주고 활성 토론이 없으면 대기 상태만 보여준다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: [], count: 0 });
  getAgentChatStatus.mockResolvedValue({
    is_running: true, active_discussions: 0, total_sessions: 2,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: '2026-07-14T00:00:00Z',
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText(/코디네이터 실행 중/)).toBeInTheDocument());
  expect(screen.getByText('RUNNING')).toBeInTheDocument();
  expect(screen.getByText(/마지막 점검/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '토론 시작' })).not.toBeInTheDocument();
});

it('"세션 보기" 클릭 시 현재 세션 ID를 실어 /agent-chat 세션 뷰어로 딥링크한다', async () => {
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
  // BASE_DETAIL.id === 's1' — the deep link must carry the session actually
  // being viewed, not drop the user on the bare /agent-chat list.
  expect(navigate).toHaveBeenCalledWith('/agent-chat?session=s1');
});

// --- T6 review fixes: REST/WS never run concurrently, and a decided session
// never claims LIVE (mirrors ChatSessionViewer's isActiveSession gating). ---
//
// NOTE: `waitFor`'s own internal retry loop is itself a (faked) setInterval,
// so it must not be used to await state settling while fake timers are
// active — it would just hang until the real testTimeout kills the test.
// `flushMicrotasks` instead drains the pending promise chain directly via
// `advanceTimersByTimeAsync(0)` (which — per vitest/sinon — still lets
// already-resolved promises drain even with nothing scheduled to tick).
async function flushMicrotasks() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

it('WS가 연결된 활성 세션에서는 5s+ 경과해도 REST 폴이 재실행되지 않는다 (플리커 봉합)', async () => {
  vi.useFakeTimers();
  try {
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
    await flushMicrotasks();

    // Initial REST fetch resolves and the (active) session's WS connects
    // (default mock: isConnected === Boolean(sessionId)).
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(getAgentChatSessionDetail).toHaveBeenCalledTimes(1);

    // Advance well past several poll intervals — REST must NOT refire while
    // the WS reports connected, so a stale snapshot can never race a fresher
    // WS-pushed vote/decision via the panel's replace-all setDetail.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });
    expect(getAgentChatSessionDetail).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it('WS가 연결되지 않은 활성 세션에서는 REST 폴백 폴링이 계속된다', async () => {
  vi.useFakeTimers();
  try {
    // Force isConnected: false regardless of sessionId — simulates an
    // active session whose socket is still connecting/never connects.
    useAgentChatWebSocketMock.mockImplementation(() => ({
      isConnected: false,
      connectionState: 'connecting' as const,
      connect: vi.fn(),
      disconnect: vi.fn(),
      lastError: null,
    }));

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
    await flushMicrotasks();

    expect(getAgentChatSessionDetail).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('LIVE')).not.toBeInTheDocument();

    // One poll interval elapses while still disconnected — REST fallback
    // must fire again (never becomes a dead tile if the socket never opens).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    expect(getAgentChatSessionDetail).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});

it('decided(비활성) 세션에서는 WS를 열지 않고(sessionId=null) LIVE 배지를 보여주지 않는다', async () => {
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({
    sessions: [
      {
        id: 's-old', ticker: '005930', stock_name: '삼성전자', status: 'decided' as const,
        started_at: null, ended_at: '2026-07-14T00:00:00Z', total_messages: 12, total_rounds: 3,
        consensus_level: 0.9, decision_action: 'BUY' as const, decision_confidence: 0.88,
      },
    ],
    count: 1,
  });
  getAgentChatSessionDetail.mockResolvedValue({ ...BASE_DETAIL, id: 's-old', status: 'decided' as const });
  getAgentChatStatus.mockResolvedValue({
    is_running: false, active_discussions: 0, total_sessions: 5,
    check_interval_minutes: 5, max_concurrent_discussions: 3, last_check_at: null,
  });

  render(<DebatePanel />);

  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  // The panel resolved a session id (the most-recent, no-status-check
  // fallback) but must not treat it as live: no WS connection request...
  expect(lastWsOpts().sessionId).toBeNull();
  // ...and no misleading "LIVE" badge for a historical/decided session.
  expect(screen.queryByText('LIVE')).not.toBeInTheDocument();
});
