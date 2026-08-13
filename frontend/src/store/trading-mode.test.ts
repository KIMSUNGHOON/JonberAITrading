/**
 * Unit Tests for R3 Trading Mode (Autonomous | HITL) store slice
 *
 * Covers:
 * - setTradingModes (sync setter fed by API callers)
 * - setKiwoomSessionAutoApproveAt set/clear semantics, including the
 *   auto-clear whenever a session's status moves away from awaiting_approval.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from './index';
import type { SessionData } from '@/types';

// Helper to create a mock session (same shape as kiwoom-session.test.ts)
function createMockSession(overrides: Partial<SessionData> = {}): SessionData {
  return {
    sessionId: `session-${Math.random().toString(36).slice(2)}`,
    ticker: '005930',
    displayName: '삼성전자',
    marketType: 'kiwoom',
    status: 'running',
    currentStage: 'technical',
    reasoningLog: [],
    analyses: [],
    tradeProposal: null,
    awaitingApproval: false,
    autoApproveAt: null,
    activePosition: null,
    error: null,
    createdAt: new Date(),
    updatedAt: new Date(),
    ...overrides,
  };
}

beforeEach(() => {
  useStore.setState({
    tradingModes: null,
    autonomyMasterEnabled: false,
    kiwoom: {
      sessions: [],
      activeSessionId: null,
      maxConcurrentSessions: 3,
      stk_cd: '',
      stk_nm: null,
      status: 'idle',
      currentStage: null,
      reasoningLog: [],
      analyses: [],
      tradeProposal: null,
      awaitingApproval: false,
      activePosition: null,
      error: null,
      history: [],
    },
  });
});

describe('setTradingModes', () => {
  it('defaults to null modes and master gate off', () => {
    expect(useStore.getState().tradingModes).toBeNull();
    expect(useStore.getState().autonomyMasterEnabled).toBe(false);
  });

  it('stores per-market modes and the master gate from the API response', () => {
    useStore.getState().setTradingModes({
      kiwoom: 'autonomous',
      master_enabled: true,
    });

    expect(useStore.getState().tradingModes).toEqual({
      kiwoom: 'autonomous',
    });
    expect(useStore.getState().autonomyMasterEnabled).toBe(true);
  });

  it('overwrites a previous response wholesale', () => {
    useStore.getState().setTradingModes({
      kiwoom: 'autonomous',
      master_enabled: true,
    });
    useStore.getState().setTradingModes({
      kiwoom: 'hitl',
      master_enabled: false,
    });

    expect(useStore.getState().tradingModes).toEqual({ kiwoom: 'hitl' });
    expect(useStore.getState().autonomyMasterEnabled).toBe(false);
  });
});

describe('setKiwoomSessionAutoApproveAt', () => {
  it('sets the deadline on the target session only', () => {
    useStore.getState().addKiwoomSession(createMockSession({ sessionId: 's-1' }));
    useStore.getState().addKiwoomSession(createMockSession({ sessionId: 's-2' }));

    useStore.getState().setKiwoomSessionAutoApproveAt('s-1', '2026-07-12T00:01:00Z');

    const sessions = useStore.getState().kiwoom.sessions;
    expect(sessions.find((s) => s.sessionId === 's-1')?.autoApproveAt).toBe(
      '2026-07-12T00:01:00Z'
    );
    expect(sessions.find((s) => s.sessionId === 's-2')?.autoApproveAt).toBeNull();
  });

  it('clears the deadline when null is passed', () => {
    useStore.getState().addKiwoomSession(
      createMockSession({ sessionId: 's-1', autoApproveAt: '2026-07-12T00:01:00Z' })
    );

    useStore.getState().setKiwoomSessionAutoApproveAt('s-1', null);

    expect(useStore.getState().kiwoom.sessions[0].autoApproveAt).toBeNull();
  });

  it('is a no-op for unknown session ids', () => {
    useStore.getState().addKiwoomSession(createMockSession({ sessionId: 's-1' }));

    useStore.getState().setKiwoomSessionAutoApproveAt('nope', '2026-07-12T00:01:00Z');

    expect(useStore.getState().kiwoom.sessions[0].autoApproveAt).toBeNull();
  });

  it('is cleared when the session status changes away from awaiting_approval', () => {
    useStore.getState().addKiwoomSession(
      createMockSession({ sessionId: 's-1', status: 'awaiting_approval' })
    );
    useStore.getState().setKiwoomSessionAutoApproveAt('s-1', '2026-07-12T00:01:00Z');

    useStore.getState().updateKiwoomSessionStatus('s-1', 'running');

    expect(useStore.getState().kiwoom.sessions[0].autoApproveAt).toBeNull();
  });

  it('is preserved while the session stays awaiting_approval', () => {
    useStore.getState().addKiwoomSession(
      createMockSession({ sessionId: 's-1', status: 'running' })
    );
    useStore.getState().setKiwoomSessionAutoApproveAt('s-1', '2026-07-12T00:01:00Z');

    useStore.getState().updateKiwoomSessionStatus('s-1', 'awaiting_approval');

    expect(useStore.getState().kiwoom.sessions[0].autoApproveAt).toBe(
      '2026-07-12T00:01:00Z'
    );
  });

  it('is cleared when the session completes or errors', () => {
    useStore.getState().addKiwoomSession(
      createMockSession({ sessionId: 's-1', status: 'awaiting_approval' })
    );
    useStore.getState().setKiwoomSessionAutoApproveAt('s-1', '2026-07-12T00:01:00Z');
    useStore.getState().completeKiwoomSession('s-1', {});
    expect(useStore.getState().kiwoom.sessions[0].autoApproveAt).toBeNull();

    useStore.getState().addKiwoomSession(
      createMockSession({ sessionId: 's-2', status: 'awaiting_approval' })
    );
    useStore.getState().setKiwoomSessionAutoApproveAt('s-2', '2026-07-12T00:01:00Z');
    useStore.getState().setKiwoomSessionError('s-2', 'boom');
    expect(
      useStore.getState().kiwoom.sessions.find((s) => s.sessionId === 's-2')?.autoApproveAt
    ).toBeNull();
  });
});
