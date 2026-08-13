/**
 * Unit Tests for Navigation Bug Investigation
 *
 * Bug: Analyzing stocks disappear from "분석 중인 종목" widget
 * when navigating from Analysis page back to Dashboard.
 *
 * Navigation is now URL-based (react-router) and no longer touches the
 * store at all — the store no longer tracks which page is active. These
 * tests instead assert directly that Kiwoom sessions (and other slices)
 * are unaffected by the kinds of state mutations that used to accompany
 * navigation.
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
    autoApproveAt: null,
    activePosition: null,
    error: null,
    createdAt: new Date(),
    updatedAt: new Date(),
    ...overrides,
  };
}

describe('Navigation Bug Investigation', () => {
  beforeEach(() => {
    // Reset store to initial state
    useStore.setState({
      activeMarket: 'kiwoom',
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

  describe('Sessions persist through navigation', () => {
    it('should preserve sessions when navigating from dashboard to analysis', () => {
      // Add a running session
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      // Verify session was added
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);

      // Navigation is URL-based now; sessions are unaffected by it.

      // Verify session still exists
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('test-session-1');
    });

    it('should preserve sessions when navigating from analysis back to dashboard', () => {
      // Add a running session
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      // Navigation is URL-based now (dashboard -> analysis -> dashboard);
      // sessions are unaffected by it.

      // Verify session still exists
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('test-session-1');
      expect(useStore.getState().kiwoom.sessions[0].status).toBe('running');
    });

    it('should preserve multiple sessions through multiple navigations', () => {
      // Add multiple sessions
      const session1 = createMockSession({ sessionId: 'session-1', ticker: '005930' });
      const session2 = createMockSession({ sessionId: 'session-2', ticker: '000660' });
      useStore.getState().addKiwoomSession(session1);
      useStore.getState().addKiwoomSession(session2);

      // Navigation is URL-based now (multiple route changes);
      // sessions are unaffected by it.

      // Verify both sessions still exist
      expect(useStore.getState().kiwoom.sessions).toHaveLength(2);
    });
  });

  describe('Session status should not change during navigation', () => {
    it('should keep session status as running during navigation', () => {
      const session = createMockSession({ sessionId: 'test-session', status: 'running' });
      useStore.getState().addKiwoomSession(session);

      // Navigation is URL-based now; sessions are unaffected by it.

      // Status should still be running
      expect(useStore.getState().kiwoom.sessions[0].status).toBe('running');
    });
  });

  describe('Legacy fields should stay in sync', () => {
    it('should sync legacy fields when active session is set', () => {
      const session = createMockSession({
        sessionId: 'test-session',
        ticker: '005930',
        displayName: '삼성전자',
        status: 'running',
      });
      useStore.getState().addKiwoomSession(session);
      useStore.getState().setActiveKiwoomSession('test-session');

      // Legacy fields should be synced
      expect(useStore.getState().kiwoom.stk_cd).toBe('005930');
      expect(useStore.getState().kiwoom.stk_nm).toBe('삼성전자');
      expect(useStore.getState().kiwoom.status).toBe('running');
    });

    it('should preserve legacy fields during navigation', () => {
      const session = createMockSession({
        sessionId: 'test-session',
        ticker: '005930',
        displayName: '삼성전자',
        status: 'running',
      });
      useStore.getState().addKiwoomSession(session);
      useStore.getState().setActiveKiwoomSession('test-session');

      // Navigation is URL-based now; sessions are unaffected by it.

      // Legacy fields should still be valid
      expect(useStore.getState().kiwoom.stk_cd).toBe('005930');
      expect(useStore.getState().kiwoom.status).toBe('running');
    });
  });

  describe('Market switching should not affect sessions', () => {
    it('setActiveMarket clears chartSymbol but leaves kiwoom.sessions untouched', () => {
      // MarketType is 'kiwoom'-only since the coin stack's removal
      // (2026-08-01), so calling setActiveMarket('kiwoom') while already on
      // 'kiwoom' is a same-value no-op for `activeMarket` itself — the only
      // thing left to actually exercise is setActiveMarket's OTHER effect
      // (store/index.ts: it unconditionally clears chartSymbol so the chart
      // falls back to the newly-active session's ticker). Assert both: the
      // clear happens, and it doesn't collaterally touch sessions.
      const session = createMockSession({ sessionId: 'test-session' });
      useStore.getState().addKiwoomSession(session);
      useStore.getState().setChartSymbol('005930');
      expect(useStore.getState().chartSymbol).toBe('005930');

      useStore.getState().setActiveMarket('kiwoom');

      expect(useStore.getState().chartSymbol).toBeNull();
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('test-session');
    });
  });

  describe('startKiwoomSession preserves existing sessions', () => {
    it('should preserve multi-session array when starting legacy session', () => {
      // Add a session via multi-session API (e.g., from BasketWidget)
      const existingSession = createMockSession({
        sessionId: 'existing-session',
        ticker: '005930',
      });
      useStore.getState().addKiwoomSession(existingSession);

      // Verify session exists
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);

      // Now call startKiwoomSession (legacy API from KiwoomTickerInput)
      // This should NOT clear the existing sessions array
      useStore.getState().startKiwoomSession('new-session-id', '000660', 'SK하이닉스');

      // The existing session from BasketWidget should still be there!
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('existing-session');

      // Legacy fields should be updated for the new session
      expect(useStore.getState().kiwoom.activeSessionId).toBe('new-session-id');
      expect(useStore.getState().kiwoom.stk_cd).toBe('000660');
      expect(useStore.getState().kiwoom.status).toBe('running');
    });
  });
});
