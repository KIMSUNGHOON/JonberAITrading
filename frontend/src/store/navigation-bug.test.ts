/**
 * Unit Tests for Navigation Bug Investigation
 *
 * Bug: Analyzing stocks disappear from "분석 중인 종목" widget
 * when navigating from Analysis page back to Dashboard.
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

describe('Navigation Bug Investigation', () => {
  beforeEach(() => {
    // Reset store to initial state
    useStore.setState({
      currentView: 'dashboard',
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

      // Navigate to analysis view
      useStore.getState().setCurrentView('analysis');

      // Verify session still exists
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
      expect(useStore.getState().kiwoom.sessions[0].sessionId).toBe('test-session-1');
    });

    it('should preserve sessions when navigating from analysis back to dashboard', () => {
      // Add a running session
      const session = createMockSession({ sessionId: 'test-session-1' });
      useStore.getState().addKiwoomSession(session);

      // Start on dashboard
      useStore.getState().setCurrentView('dashboard');

      // Navigate to analysis
      useStore.getState().setCurrentView('analysis');

      // Navigate back to dashboard
      useStore.getState().setCurrentView('dashboard');

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

      // Navigate multiple times
      useStore.getState().setCurrentView('analysis');
      useStore.getState().setCurrentView('dashboard');
      useStore.getState().setCurrentView('basket');
      useStore.getState().setCurrentView('history');
      useStore.getState().setCurrentView('dashboard');

      // Verify both sessions still exist
      expect(useStore.getState().kiwoom.sessions).toHaveLength(2);
    });
  });

  describe('Session status should not change during navigation', () => {
    it('should keep session status as running during navigation', () => {
      const session = createMockSession({ sessionId: 'test-session', status: 'running' });
      useStore.getState().addKiwoomSession(session);

      // Navigate around
      useStore.getState().setCurrentView('analysis');
      useStore.getState().setCurrentView('dashboard');

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

      // Navigate
      useStore.getState().setCurrentView('analysis');
      useStore.getState().setCurrentView('dashboard');

      // Legacy fields should still be valid
      expect(useStore.getState().kiwoom.stk_cd).toBe('005930');
      expect(useStore.getState().kiwoom.status).toBe('running');
    });
  });

  describe('Market switching should not affect sessions', () => {
    it('should preserve sessions when switching markets', () => {
      const session = createMockSession({ sessionId: 'test-session' });
      useStore.getState().addKiwoomSession(session);

      // Switch markets
      useStore.getState().setActiveMarket('coin');
      useStore.getState().setActiveMarket('stock');
      useStore.getState().setActiveMarket('kiwoom');

      // Session should still exist
      expect(useStore.getState().kiwoom.sessions).toHaveLength(1);
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
