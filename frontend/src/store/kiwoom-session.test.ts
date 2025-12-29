/**
 * Unit Tests for Kiwoom Session Management
 *
 * Tests the removeKiwoomSession action and related state updates.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from './index';
import type { SessionData } from '@/types';

// Helper to create a mock session
function createMockSession(overrides: Partial<SessionData> = {}): SessionData {
  return {
    sessionId: `session-${Math.random().toString(36).slice(2)}`,
    ticker: '005930',
    displayName: '삼성전자',
    marketType: 'kiwoom',
    status: 'running',
    currentStage: 'technical',
    reasoningLog: ['분석 시작'],
    analyses: [],
    tradeProposal: null,
    awaitingApproval: false,
    activePosition: null,
    error: null,
    createdAt: new Date(),
    updatedAt: new Date(),
    ...overrides,
  };
}

describe('Kiwoom Session Management', () => {
  beforeEach(() => {
    // Reset store to initial state
    useStore.setState({
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

  describe('addKiwoomSession', () => {
    it('should add a new session successfully', () => {
      const session = createMockSession({ sessionId: 'test-session-1' });
      const result = useStore.getState().addKiwoomSession(session);

      expect(result).toBe(true);
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('test-session-1');
      expect(useStore.getState().kiwoom.activeSessionId).toBe('test-session-1');
    });

    it('should not add duplicate session', () => {
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      const result = useStore.getState().addKiwoomSession(session);
      expect(result).toBe(false);
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
    });

    it('should respect max concurrent sessions limit', () => {
      // Add 3 running sessions
      for (let i = 0; i < 3; i++) {
        const session = createMockSession({
          sessionId: `session-${i}`,
          status: 'running',
        });
        useStore.getState().addKiwoomSession(session);
      }

      // Try to add 4th session
      const session4 = createMockSession({
        sessionId: 'session-3',
        status: 'running',
      });
      const result = useStore.getState().addKiwoomSession(session4);

      expect(result).toBe(false);
      expect(useStore.getState().kiwoom.sessions).toHaveLength(3);
    });

    it('should allow adding session when previous ones are completed', () => {
      // Add 3 sessions, 2 completed
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: 'session-0', status: 'completed' })
      );
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: 'session-1', status: 'completed' })
      );
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: 'session-2', status: 'running' })
      );

      // Should allow adding more since only 1 is running
      const session = createMockSession({
        sessionId: 'session-3',
        status: 'running',
      });
      const result = useStore.getState().addKiwoomSession(session);

      expect(result).toBe(true);
      expect(useStore.getState().kiwoom.sessions).toHaveLength(4);
    });
  });

  describe('removeKiwoomSession', () => {
    it('should remove a session by ID', () => {
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().removeKiwoomSession('test-session-1');

      expect(useStore.getState().kiwoom.sessions).toHaveLength(0);
    });

    it('should update activeSessionId when removing active session', () => {
      const session1 = createMockSession({ sessionId: 'session-1', ticker: '005930' });
      const session2 = createMockSession({ sessionId: 'session-2', ticker: '000660' });

      useStore.getState().addKiwoomSession(session1);
      useStore.getState().addKiwoomSession(session2);

      // session-2 should be active (most recently added)
      expect(useStore.getState().kiwoom.activeSessionId).toBe('session-2');

      // Remove active session
      useStore.getState().removeKiwoomSession('session-2');

      // session-1 should now be active
      expect(useStore.getState().kiwoom.activeSessionId).toBe('session-1');
      expect(useStore.getState().kiwoom.stk_cd).toBe('005930');
    });

    it('should reset legacy fields when removing last session', () => {
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().removeKiwoomSession('test-session-1');

      expect(useStore.getState().kiwoom.activeSessionId).toBe(null);
      expect(useStore.getState().kiwoom.stk_cd).toBe('');
      expect(useStore.getState().kiwoom.status).toBe('idle');
      expect(useStore.getState().kiwoom.reasoningLog).toHaveLength(0);
    });

    it('should not affect other sessions when removing one', () => {
      const session1 = createMockSession({ sessionId: 'session-1' });
      const session2 = createMockSession({ sessionId: 'session-2' });
      const session3 = createMockSession({ sessionId: 'session-3' });

      useStore.getState().addKiwoomSession(session1);
      useStore.getState().addKiwoomSession(session2);
      useStore.getState().addKiwoomSession(session3);

      // Remove middle session
      useStore.getState().removeKiwoomSession('session-2');

      const remainingSessions = useStore.getState().kiwoom.sessions;
      expect(remainingSessions).toHaveLength(2);
      expect(remainingSessions.map((s) => s.sessionId)).toEqual(['session-1', 'session-3']);
    });

    it('should handle removing non-existent session gracefully', () => {
      const session = createMockSession({ sessionId: 'existing-session' });
      useStore.getState().addKiwoomSession(session);

      // Try to remove non-existent session
      useStore.getState().removeKiwoomSession('non-existent');

      // Original session should still be there
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
    });
  });

  describe('updateKiwoomSessionStatus', () => {
    it('should update session status correctly', () => {
      const session = createMockSession({ sessionId: 'test-session', status: 'running' });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().updateKiwoomSessionStatus('test-session', 'completed');

      const updatedSession = useStore.getState().kiwoom.sessions[0];
      expect(updatedSession.status).toBe('completed');
    });

    it('should update legacy status when active session is updated', () => {
      const session = createMockSession({ sessionId: 'test-session', status: 'running' });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().updateKiwoomSessionStatus('test-session', 'awaiting_approval');

      expect(useStore.getState().kiwoom.status).toBe('awaiting_approval');
    });
  });

  describe('setKiwoomSessionError', () => {
    it('should set error and update status to error', () => {
      const session = createMockSession({ sessionId: 'test-session', status: 'running' });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().setKiwoomSessionError('test-session', 'Analysis failed');

      const updatedSession = useStore.getState().kiwoom.sessions[0];
      expect(updatedSession.error).toBe('Analysis failed');
      expect(updatedSession.status).toBe('error');
    });

    it('should clear error when null is passed', () => {
      const session = createMockSession({
        sessionId: 'test-session',
        status: 'error',
        error: 'Previous error',
      });
      useStore.getState().addKiwoomSession(session);

      useStore.getState().setKiwoomSessionError('test-session', null);

      const updatedSession = useStore.getState().kiwoom.sessions[0];
      expect(updatedSession.error).toBe(null);
    });
  });
});

describe('Session Removal Flow (onRemove handler)', () => {
  beforeEach(() => {
    useStore.setState({
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

  it('should properly clean up session on removal', () => {
    // Setup: Add multiple sessions
    const sessions = [
      createMockSession({ sessionId: 'session-1', status: 'completed' }),
      createMockSession({ sessionId: 'session-2', status: 'running' }),
      createMockSession({ sessionId: 'session-3', status: 'error' }),
    ];

    sessions.forEach((s) => useStore.getState().addKiwoomSession(s));

    // Simulate onRemove: Remove completed session
    useStore.getState().removeKiwoomSession('session-1');

    // Verify removal
    const remainingSessions = useStore.getState().kiwoom.sessions;
    expect(remainingSessions).toHaveLength(2);
    expect(remainingSessions.find((s) => s.sessionId === 'session-1')).toBeUndefined();
  });

  it('should allow new session after removal frees up slot', () => {
    // Add max sessions
    for (let i = 0; i < 3; i++) {
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: `session-${i}`, status: 'running' })
      );
    }

    // Cannot add more
    expect(
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: 'session-new', status: 'running' })
      )
    ).toBe(false);

    // Remove one session
    useStore.getState().updateKiwoomSessionStatus('session-0', 'completed');
    useStore.getState().removeKiwoomSession('session-0');

    // Now can add new session
    expect(
      useStore.getState().addKiwoomSession(
        createMockSession({ sessionId: 'session-new', status: 'running' })
      )
    ).toBe(true);
  });
});
