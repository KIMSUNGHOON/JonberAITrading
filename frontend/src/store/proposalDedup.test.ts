/**
 * setKiwoomSessionProposal idempotency (proposal dedup).
 *
 * Re-delivery of the SAME proposal (same id) must update the stored fields
 * silently — no new "Trade Proposal for …" chat message, no forced popup.
 * This happens on refresh rehydration (rehydrateKiwoomSessions sets the
 * proposal, then the fresh /ws/session snapshot re-emits the proposal frame)
 * and on /workflow route re-entry reconnecting the stream. A proposal with a
 * DIFFERENT id (or set over null) keeps the original announce behavior.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from './index';
import type { SessionData, KRStockTradeProposal } from '@/types';

function createMockSession(overrides: Partial<SessionData> = {}): SessionData {
  return {
    sessionId: 'session-1',
    ticker: '005930',
    displayName: '삼성전자',
    marketType: 'kiwoom',
    status: 'awaiting_approval',
    currentStage: null,
    reasoningLog: [],
    analyses: [],
    tradeProposal: null,
    awaitingApproval: true,
    autoApproveAt: null,
    activePosition: null,
    error: null,
    createdAt: new Date(),
    updatedAt: new Date(),
    ...overrides,
  };
}

function createProposal(overrides: Partial<KRStockTradeProposal> = {}): KRStockTradeProposal {
  return {
    id: 'p1',
    stk_cd: '005930',
    stk_nm: '삼성전자',
    action: 'BUY',
    quantity: 10,
    entry_price: 70000,
    stop_loss: 65000,
    take_profit: 80000,
    risk_score: 0.5,
    position_size_pct: 0,
    rationale: '테스트',
    bull_case: '',
    bear_case: '',
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

const proposalMessages = () =>
  useStore.getState().messages.filter((m) => m.role === 'proposal');

describe('setKiwoomSessionProposal dedup', () => {
  beforeEach(() => {
    useStore.setState({
      messages: [],
      chatPopupOpen: false,
      kiwoom: {
        ...useStore.getState().kiwoom,
        sessions: [],
        activeSessionId: null,
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
    useStore.getState().addKiwoomSession(createMockSession({ sessionId: 'session-1' }));
  });

  it('same-id proposal delivered twice appends exactly one chat message and forces the popup only on the first', () => {
    useStore.getState().setKiwoomSessionProposal('session-1', createProposal({ id: 'p1' }));

    expect(proposalMessages()).toHaveLength(1);
    expect(useStore.getState().chatPopupOpen).toBe(true);

    // User closes the popup, then the same proposal is re-delivered
    // (WS snapshot replay after refresh / route re-entry).
    useStore.getState().setChatPopupOpen(false);
    useStore
      .getState()
      .setKiwoomSessionProposal('session-1', createProposal({ id: 'p1', entry_price: 71000 }));

    // Silent update: no second message, popup stays closed…
    expect(proposalMessages()).toHaveLength(1);
    expect(useStore.getState().chatPopupOpen).toBe(false);
    // …but the proposal fields ARE updated (session + legacy mirror).
    const session = useStore.getState().kiwoom.sessions.find((s) => s.sessionId === 'session-1');
    expect(session?.tradeProposal?.entry_price).toBe(71000);
    expect(useStore.getState().kiwoom.tradeProposal?.entry_price).toBe(71000);
  });

  it('a different-id proposal appends a new message and reopens the popup', () => {
    useStore.getState().setKiwoomSessionProposal('session-1', createProposal({ id: 'p1' }));
    useStore.getState().setChatPopupOpen(false);

    useStore.getState().setKiwoomSessionProposal('session-1', createProposal({ id: 'p2' }));

    expect(proposalMessages()).toHaveLength(2);
    expect(useStore.getState().chatPopupOpen).toBe(true);
  });

  it('setting a proposal over null announces normally (baseline unchanged)', () => {
    // beforeEach session starts with tradeProposal null
    useStore.getState().setKiwoomSessionProposal('session-1', createProposal({ id: 'p1' }));

    expect(proposalMessages()).toHaveLength(1);
    expect(useStore.getState().chatPopupOpen).toBe(true);
  });
});
