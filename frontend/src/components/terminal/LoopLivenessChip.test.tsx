import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LoopLivenessChip } from './LoopLivenessChip';

const getAgentChatStatus = vi.fn();
vi.mock('@/api/client', () => ({
  getAgentChatStatus: (...a: unknown[]) => getAgentChatStatus(...a),
}));

beforeEach(() => {
  getAgentChatStatus.mockReset();
});

describe('LoopLivenessChip', () => {
  it('shows LOOP ACTIVE when the coordinator is running with a fresh tick', async () => {
    getAgentChatStatus.mockResolvedValue({
      is_running: true,
      active_discussions: 0,
      total_sessions: 0,
      check_interval_minutes: 5,
      max_concurrent_discussions: 3,
      last_check_at: new Date().toISOString(),
    });
    render(<LoopLivenessChip />);
    await waitFor(() => expect(screen.getByText('LOOP ACTIVE')).toBeInTheDocument());
  });

  it('shows LOOP OFF when the coordinator is not running', async () => {
    getAgentChatStatus.mockResolvedValue({
      is_running: false,
      active_discussions: 0,
      total_sessions: 0,
      check_interval_minutes: 5,
      max_concurrent_discussions: 3,
      last_check_at: null,
    });
    render(<LoopLivenessChip />);
    await waitFor(() => expect(screen.getByText('LOOP OFF')).toBeInTheDocument());
  });

  it('shows LOOP STALE when is_running=true but the last tick is far in the past (dead scheduler)', async () => {
    getAgentChatStatus.mockResolvedValue({
      is_running: true,
      active_discussions: 0,
      total_sessions: 0,
      check_interval_minutes: 5,
      max_concurrent_discussions: 3,
      last_check_at: new Date(Date.now() - 60 * 60_000).toISOString(),
    });
    render(<LoopLivenessChip />);
    await waitFor(() => expect(screen.getByText('LOOP STALE')).toBeInTheDocument());
    // The dead scheduler must NOT render as active.
    expect(screen.queryByText('LOOP ACTIVE')).not.toBeInTheDocument();
  });

  it('shows an unknown state when the status fetch fails', async () => {
    getAgentChatStatus.mockRejectedValue(new Error('network down'));
    render(<LoopLivenessChip />);
    await waitFor(() => expect(screen.getByText('LOOP —')).toBeInTheDocument());
  });
});
