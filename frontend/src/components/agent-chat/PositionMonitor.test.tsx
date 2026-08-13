/**
 * B3 (page-ux audit §B-2(4)) — PositionMonitor's empty state used to say
 * "Add positions to start monitoring" even though there is no "Add
 * positions" UI anywhere in the app (`addAgentChatPosition` etc. have zero
 * callers); positions are actually populated by coordinator.start() ->
 * sync_from_account(). This pins the honest replacement text.
 *
 * It also pins the "Discussion Required" event badge becoming a real
 * click-to-act affordance instead of static text with no onClick: clicking
 * it opens the matching active/recent session for that ticker, or — if none
 * exists — starts a new debate for it, so it's never a dead end.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const getAgentChatPositionSummary = vi.fn();
const getAgentChatPositionEvents = vi.fn();
vi.mock('@/api/client', () => ({
  getAgentChatPositionSummary: (...a: unknown[]) => getAgentChatPositionSummary(...a),
  getAgentChatPositionEvents: (...a: unknown[]) => getAgentChatPositionEvents(...a),
}));

import { PositionMonitor } from './PositionMonitor';
import type {
  AgentChatPositionEvent,
  AgentChatPositionSummary,
  AgentChatActiveDiscussion,
  AgentChatSessionSummary,
} from '@/types';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('빈 상태 정직화 (B3)', () => {
  it('포지션이 없으면 실동작(코디네이터 자동 동기화)과 일치하는 문구를 보여준다', async () => {
    getAgentChatPositionSummary.mockResolvedValue({
      is_running: false,
      position_count: 0,
      total_value: 0,
      total_unrealized_pnl: 0,
      total_unrealized_pnl_pct: 0,
      event_count: 0,
      positions: [],
    } satisfies AgentChatPositionSummary);
    getAgentChatPositionEvents.mockResolvedValue({ events: [], count: 0 });

    render(<PositionMonitor />);

    await screen.findByText('모니터링 중인 포지션이 없습니다');
    expect(screen.getByText('코디네이터 시작 시 계좌에서 자동 동기화됩니다')).toBeInTheDocument();
    // The old text described a UI action that doesn't exist anywhere.
    expect(screen.queryByText(/Add positions/i)).not.toBeInTheDocument();
  });
});

describe('EventItem "Discussion Required" 액션 (B3)', () => {
  const baseEvent: AgentChatPositionEvent = {
    id: 'e1',
    ticker: '005930',
    event_type: 'stop_loss_near',
    timestamp: new Date().toISOString(),
    current_price: 70000,
    trigger_value: 69000,
    message: '손절가 근접',
    requires_discussion: true,
    auto_execute: false,
    data: { stock_name: '삼성전자' },
  };

  function summaryWithOnePosition(): AgentChatPositionSummary {
    return {
      is_running: true,
      position_count: 1,
      total_value: 710000,
      total_unrealized_pnl: 10000,
      total_unrealized_pnl_pct: 0.01,
      event_count: 1,
      positions: [
        {
          ticker: '005930',
          stock_name: '삼성전자',
          quantity: 10,
          avg_price: 70000,
          current_price: 71000,
          unrealized_pnl: 10000,
          unrealized_pnl_pct: 0.01,
          position_value: 710000,
          stop_loss: null,
          take_profit: null,
          trailing_stop_pct: null,
          trailing_stop_price: null,
          highest_price: null,
          holding_days: 1,
          discussion_count: 0,
          last_discussion: null,
        },
      ],
    };
  }

  it('일치하는 활성 토론이 있으면 클릭 시 그 세션을 연다', async () => {
    getAgentChatPositionSummary.mockResolvedValue(summaryWithOnePosition());
    getAgentChatPositionEvents.mockResolvedValue({ events: [baseEvent], count: 1 });

    const onOpenSession = vi.fn();
    const onStartDebate = vi.fn();
    const activeDiscussions: AgentChatActiveDiscussion[] = [
      { ticker: '005930', stock_name: '삼성전자', session_id: 'sess-live', status: 'discussing', started_at: null },
    ];

    render(
      <PositionMonitor
        activeDiscussions={activeDiscussions}
        sessions={[]}
        onOpenSession={onOpenSession}
        onStartDebate={onStartDebate}
      />,
    );

    const badge = await screen.findByRole('button', { name: /Discussion Required/i });
    fireEvent.click(badge);

    expect(onOpenSession).toHaveBeenCalledWith('sess-live');
    expect(onStartDebate).not.toHaveBeenCalled();
  });

  it('활성 토론은 없지만 최근 세션 기록에 일치하는 티커가 있으면 그 세션을 연다', async () => {
    getAgentChatPositionSummary.mockResolvedValue(summaryWithOnePosition());
    getAgentChatPositionEvents.mockResolvedValue({ events: [baseEvent], count: 1 });

    const onOpenSession = vi.fn();
    const onStartDebate = vi.fn();
    const sessions: AgentChatSessionSummary[] = [
      {
        id: 'sess-recent',
        ticker: '005930',
        stock_name: '삼성전자',
        status: 'decided',
        started_at: null,
        ended_at: null,
        total_messages: 3,
        total_rounds: 1,
        consensus_level: 0.8,
        decision_action: 'HOLD',
        decision_confidence: 0.6,
      },
    ];

    render(
      <PositionMonitor
        activeDiscussions={[]}
        sessions={sessions}
        onOpenSession={onOpenSession}
        onStartDebate={onStartDebate}
      />,
    );

    const badge = await screen.findByRole('button', { name: /Discussion Required/i });
    fireEvent.click(badge);

    expect(onOpenSession).toHaveBeenCalledWith('sess-recent');
    expect(onStartDebate).not.toHaveBeenCalled();
  });

  it('일치하는 세션이 전혀 없으면 죽은 텍스트가 아니라 새 토론 시작으로 이어진다', async () => {
    getAgentChatPositionSummary.mockResolvedValue(summaryWithOnePosition());
    getAgentChatPositionEvents.mockResolvedValue({ events: [baseEvent], count: 1 });

    const onOpenSession = vi.fn();
    const onStartDebate = vi.fn();

    render(
      <PositionMonitor
        activeDiscussions={[]}
        sessions={[]}
        onOpenSession={onOpenSession}
        onStartDebate={onStartDebate}
      />,
    );

    const badge = await screen.findByRole('button', { name: /Discussion Required/i });
    fireEvent.click(badge);

    expect(onOpenSession).not.toHaveBeenCalled();
    expect(onStartDebate).toHaveBeenCalledWith('005930', '삼성전자');
  });
});
