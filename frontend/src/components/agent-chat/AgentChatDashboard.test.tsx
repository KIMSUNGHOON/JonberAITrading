/**
 * R5-P2-UX B2 — /agent-chat used to full-page-swap to `ChatSessionViewer`
 * the moment a session was selected (the app's only screen that navigates
 * that way, per the page-ux audit §B): the session list, status card, and
 * everything else vanished, leaving a tiny "← Back" as the only orientation
 * cue. This pins the fix:
 *
 * 1. Master-detail — selecting a session narrows the list, it never
 *    disappears (no more total page wipe).
 * 2. "Start" actually starts the 5-minute watch-list scheduler, not an
 *    immediate debate — the button must say so.
 * 3. `last_check_at` (loop-liveness heartbeat) is rendered on the page, and
 *    a stale/absent heartbeat must read as honestly stale/absent, never as
 *    a fabricated "just checked".
 * 4. `?session=<id>` in the URL (B1's DebatePanel deep link) selects that
 *    session on load.
 *
 * Child components are stubbed (same convention as TradingDashboard.test.tsx
 * stubbing TradingModeSection) so this file stays scoped to
 * AgentChatDashboard's own status/selection/naming logic instead of also
 * having to satisfy ChatSessionViewer's/PositionMonitor's own network calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type {
  AgentChatCoordinatorStatus,
  AgentChatSessionSummary,
} from '@/types';

const getAgentChatStatus = vi.fn();
const startAgentChat = vi.fn();
const stopAgentChat = vi.fn();
const getAgentChatActiveDiscussions = vi.fn();
const getAgentChatSessions = vi.fn();
vi.mock('@/api/client', () => ({
  getAgentChatStatus: (...a: unknown[]) => getAgentChatStatus(...a),
  startAgentChat: (...a: unknown[]) => startAgentChat(...a),
  stopAgentChat: (...a: unknown[]) => stopAgentChat(...a),
  getAgentChatActiveDiscussions: (...a: unknown[]) => getAgentChatActiveDiscussions(...a),
  getAgentChatSessions: (...a: unknown[]) => getAgentChatSessions(...a),
}));

// Stubs — the point of this suite is AgentChatDashboard's own layout/status
// logic, not these components' internals (each has its own test coverage).
vi.mock('./ChatSessionList', () => ({
  ChatSessionList: ({
    sessions,
    onSelectSession,
  }: {
    sessions: AgentChatSessionSummary[];
    onSelectSession: (id: string) => void;
  }) => (
    <div data-testid="chat-session-list">
      {sessions.map((s) => (
        <button key={s.id} onClick={() => onSelectSession(s.id)}>
          select-{s.id}
        </button>
      ))}
    </div>
  ),
}));

vi.mock('./ChatSessionViewer', () => ({
  ChatSessionViewer: ({
    sessionId,
    onClose,
  }: {
    sessionId: string;
    onClose: () => void;
  }) => (
    <div data-testid="chat-session-viewer">
      viewing:{sessionId}
      <button onClick={onClose}>close-viewer</button>
    </div>
  ),
}));

vi.mock('./PositionMonitor', () => ({
  PositionMonitor: () => <div data-testid="position-monitor" />,
}));

import { AgentChatDashboard } from './AgentChatDashboard';

const SESSIONS: AgentChatSessionSummary[] = [
  {
    id: 's1',
    ticker: '005930',
    stock_name: '삼성전자',
    status: 'decided',
    started_at: null,
    ended_at: null,
    total_messages: 3,
    total_rounds: 1,
    consensus_level: 0.8,
    decision_action: 'BUY',
    decision_confidence: 0.7,
  },
  {
    id: 's2',
    ticker: '000660',
    stock_name: 'SK하이닉스',
    status: 'voting',
    started_at: null,
    ended_at: null,
    total_messages: 1,
    total_rounds: 1,
    consensus_level: 0.5,
    decision_action: null,
    decision_confidence: null,
  },
];

function baseStatus(over: Partial<AgentChatCoordinatorStatus>): AgentChatCoordinatorStatus {
  return {
    is_running: false,
    active_discussions: 0,
    total_sessions: 2,
    check_interval_minutes: 5,
    max_concurrent_discussions: 3,
    last_check_at: null,
    ...over,
  };
}

function renderDashboard(initialPath = '/agent-chat') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AgentChatDashboard />
    </MemoryRouter>,
  );
}

// Fake-timer-safe flush (mirrors DebatePanel.test.tsx's `flushMicrotasks`):
// RTL's own `waitFor`/`findBy*` poll via a (faked) setInterval, so they hang
// under fake timers instead of settling. `advanceTimersByTimeAsync(0)` drains
// the already-resolved mock-promise chain (fetchData's Promise.all) without
// needing to fire any real timer.
async function flushMicrotasks() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  getAgentChatActiveDiscussions.mockResolvedValue({ discussions: [], count: 0 });
  getAgentChatSessions.mockResolvedValue({ sessions: SESSIONS, count: SESSIONS.length });
  getAgentChatStatus.mockResolvedValue(baseStatus({}));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('마스터-디테일 (풀스왑 금지)', () => {
  it('세션 선택 후에도 세션 목록이 유지된다 — 전체 페이지 교체가 아니다', async () => {
    renderDashboard();

    await screen.findByTestId('chat-session-list');
    // Header still present — this is not a full-page swap.
    expect(screen.getByText('Agent Group Chat')).toBeInTheDocument();

    fireEvent.click(screen.getByText('select-s1'));

    // The detail pane now shows the viewer for s1...
    await waitFor(() => expect(screen.getByTestId('chat-session-viewer')).toBeInTheDocument());
    expect(screen.getByText('viewing:s1')).toBeInTheDocument();
    // ...but the list ("master") is still on screen, and the header too.
    expect(screen.getByTestId('chat-session-list')).toBeInTheDocument();
    expect(screen.getByText('Agent Group Chat')).toBeInTheDocument();
  });

  it('닫기(onClose) 시 상세만 사라지고 목록 화면으로 돌아간다', async () => {
    renderDashboard('/agent-chat?session=s1');

    await screen.findByTestId('chat-session-viewer');
    fireEvent.click(screen.getByText('close-viewer'));

    await waitFor(() => expect(screen.queryByTestId('chat-session-viewer')).not.toBeInTheDocument());
    expect(screen.getByTestId('chat-session-list')).toBeInTheDocument();
    expect(screen.getByTestId('position-monitor')).toBeInTheDocument();
  });
});

describe('딥링크 소비 (?session=<id>)', () => {
  it('URL의 ?session=<id>가 마운트 시 해당 세션을 선택한다 (B1 DebatePanel 딥링크 착지)', async () => {
    renderDashboard('/agent-chat?session=s2');

    await waitFor(() => expect(screen.getByTestId('chat-session-viewer')).toBeInTheDocument());
    expect(screen.getByText('viewing:s2')).toBeInTheDocument();
    // Master-detail: the list is present alongside the deep-linked viewer.
    expect(screen.getByTestId('chat-session-list')).toBeInTheDocument();
  });
});

describe('명명 정정 — Start/Stop', () => {
  it('코디네이터 미기동이면 "자동 모니터링 시작 (N분 주기)" 라벨을 보여준다 (즉시 토론 오해 금지)', async () => {
    getAgentChatStatus.mockResolvedValue(baseStatus({ is_running: false }));
    renderDashboard();

    await screen.findByText(/자동 모니터링 시작 \(5분 주기\)/);
    expect(screen.queryByText(/^Start$/)).not.toBeInTheDocument();
  });

  it('코디네이터 실행 중이면 "자동 모니터링 중지" 라벨을 보여준다', async () => {
    getAgentChatStatus.mockResolvedValue(baseStatus({ is_running: true, last_check_at: null }));
    renderDashboard();

    await screen.findByText('자동 모니터링 중지');
    expect(screen.queryByText(/^Stop$/)).not.toBeInTheDocument();
  });
});

describe('루프 생존 가시화 (last_check_at)', () => {
  it('last_check_at이 있으면 마지막 점검 시각과 다음 점검까지 카운트다운을 보여준다', async () => {
    vi.useFakeTimers();
    try {
      const fixedNow = new Date('2026-07-14T09:05:00+09:00');
      vi.setSystemTime(fixedNow);

      const lastCheck = new Date(fixedNow.getTime() - 30_000).toISOString(); // 30s ago
      getAgentChatStatus.mockResolvedValue(
        baseStatus({ is_running: true, last_check_at: lastCheck, check_interval_minutes: 5 }),
      );

      renderDashboard();
      await flushMicrotasks();

      expect(screen.getByText(/다음 점검까지/)).toBeInTheDocument();
      expect(screen.getByText(/마지막 점검/)).toBeInTheDocument();
      // 5min interval - 30s elapsed = 270s = 04:30 remaining.
      expect(screen.getByText('04:30')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('last_check_at이 없으면(첫 틱 대기) 거짓 카운트다운 없이 정직하게 보여준다', async () => {
    getAgentChatStatus.mockResolvedValue(
      baseStatus({ is_running: true, last_check_at: null }),
    );

    renderDashboard();

    await screen.findByText('첫 점검 대기 중');
    // Absent heartbeat renders the honest dash, not a fabricated timestamp.
    expect(screen.getByText('마지막 점검')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('마지막 점검이 점검주기의 2배 이상 지나면 살아있는 척하지 않고 지연 경고를 보여준다', async () => {
    vi.useFakeTimers();
    try {
      const fixedNow = new Date('2026-07-14T09:30:00+09:00');
      vi.setSystemTime(fixedNow);

      // 5min interval; last check 30 minutes ago — well past the stale
      // threshold (staleAfterMs = max(2min, interval*2) = 10min here).
      const staleLastCheck = new Date(fixedNow.getTime() - 30 * 60_000).toISOString();
      getAgentChatStatus.mockResolvedValue(
        baseStatus({ is_running: true, last_check_at: staleLastCheck, check_interval_minutes: 5 }),
      );

      renderDashboard();
      await flushMicrotasks();

      expect(screen.getByText(/루프 응답 지연/)).toBeInTheDocument();
      // No confident countdown while the loop reads as dead.
      expect(screen.queryByText(/다음 점검까지/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('코디네이터 미기동이면 다음 점검 카운트다운을 보여주지 않는다', async () => {
    getAgentChatStatus.mockResolvedValue(baseStatus({ is_running: false, last_check_at: null }));

    renderDashboard();

    await screen.findByText('마지막 점검');
    expect(screen.queryByText(/다음 점검까지/)).not.toBeInTheDocument();
    expect(screen.queryByText(/루프 응답 지연/)).not.toBeInTheDocument();
  });
});
