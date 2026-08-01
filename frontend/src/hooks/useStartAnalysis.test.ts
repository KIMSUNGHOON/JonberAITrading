/**
 * useStartAnalysis — P4 T3 dedup routing + held-position notice.
 *
 * Backend /analysis/start now additively returns `duplicate` (an active
 * session for the ticker already existed — the response IS that existing
 * session, no new graph run) and `position_exists` (the ticker is already
 * held — the run is position-aware ADD/REDUCE/HOLD, not a fresh BUY entry).
 * These tests pin:
 *  - duplicate:true focuses the existing session instead of adding a
 *    second store session (addKiwoomSession/wsManager.connect only fire
 *    when the session wasn't already cached locally).
 *  - position_exists:true surfaces the held-position toast via
 *    setInfoNotice.
 *  - the pre-P4 (both flags false/absent) path is unchanged.
 *
 * Follows kiwoomSessionHandlers.test.ts's convention: fully mock `@/store`
 * (a controlled `mockState` object serves both the `useStore(selector)` and
 * `useStore.getState()` call shapes) rather than exercising the real store,
 * since useStartAnalysis reads/dispatches through both.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const { mockWsManager } = vi.hoisted(() => ({
  mockWsManager: { has: vi.fn(), connect: vi.fn() },
}));
vi.mock('@/api/websocket', () => ({ wsManager: mockWsManager }));

const { startKRStockAnalysis } = vi.hoisted(() => ({
  startKRStockAnalysis: vi.fn(),
}));
vi.mock('@/api/client', () => ({
  startKRStockAnalysis: (...a: unknown[]) => startKRStockAnalysis(...a),
}));

const { createKiwoomWebSocketHandlers } = vi.hoisted(() => ({
  createKiwoomWebSocketHandlers: vi.fn((..._args: unknown[]) => ({ handlers: true })),
}));
vi.mock('@/api/kiwoomSessionHandlers', () => ({
  createKiwoomWebSocketHandlers: (...a: unknown[]) => createKiwoomWebSocketHandlers(...a),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockState: any;
vi.mock('@/store', () => ({
  useStore: Object.assign((sel: (s: any) => unknown) => sel(mockState), { // eslint-disable-line @typescript-eslint/no-explicit-any
    getState: () => mockState,
  }),
}));

import { useStartAnalysis } from './useStartAnalysis';

function baseState() {
  return {
    setActiveMarket: vi.fn(),
    addKiwoomSession: vi.fn(() => true),
    setActiveKiwoomSession: vi.fn(),
    setInfoNotice: vi.fn(),
    kiwoom: { sessions: [] as Array<{ sessionId: string }> },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState = baseState();
  mockWsManager.has.mockReturnValue(false);
});

describe('useStartAnalysis — kiwoom', () => {
  it('fresh start (duplicate/position_exists both false) adds a new session, connects WS, focuses it, and does not toast', async () => {
    startKRStockAnalysis.mockResolvedValue({
      session_id: 'S1', stk_cd: '005930', stk_nm: '삼성전자', status: 'started',
      message: 'ok', duplicate: false, position_exists: false,
    });
    const { result } = renderHook(() => useStartAnalysis());

    const out = await result.current('kiwoom', '005930', '삼성전자');

    expect(out).toEqual({ sessionId: 'S1', duplicate: false, positionExists: false });
    expect(mockState.addKiwoomSession).toHaveBeenCalledTimes(1);
    expect(mockState.addKiwoomSession).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: 'S1', ticker: '005930', status: 'running' })
    );
    expect(mockWsManager.connect).toHaveBeenCalledWith('S1', expect.anything());
    expect(mockState.setActiveKiwoomSession).toHaveBeenCalledWith('S1');
    expect(mockState.setInfoNotice).not.toHaveBeenCalled();
  });

  it('duplicate:true for a session ALREADY cached locally focuses it without adding a second store session', async () => {
    mockState.kiwoom.sessions = [{ sessionId: 'S1' }];
    startKRStockAnalysis.mockResolvedValue({
      session_id: 'S1', stk_cd: '005930', stk_nm: '삼성전자', status: 'running',
      message: '이미 진행중인 분석 세션이 있습니다', duplicate: true, position_exists: false,
    });
    const { result } = renderHook(() => useStartAnalysis());

    const out = await result.current('kiwoom', '005930', '삼성전자');

    expect(out).toEqual({ sessionId: 'S1', duplicate: true, positionExists: false });
    // The session count is unchanged: no second addKiwoomSession call, no new WS connect.
    expect(mockState.addKiwoomSession).not.toHaveBeenCalled();
    expect(mockWsManager.connect).not.toHaveBeenCalled();
    // But it IS focused, so the user lands on the existing run.
    expect(mockState.setActiveKiwoomSession).toHaveBeenCalledWith('S1');
  });

  it('duplicate:true for a session NOT yet cached locally (e.g. started in another tab) injects it once, then focuses it', async () => {
    mockState.kiwoom.sessions = [];
    startKRStockAnalysis.mockResolvedValue({
      session_id: 'S2', stk_cd: '000660', stk_nm: 'SK하이닉스', status: 'awaiting_approval',
      message: '이미 진행중인 분석 세션이 있습니다', duplicate: true, position_exists: false,
    });
    const { result } = renderHook(() => useStartAnalysis());

    await result.current('kiwoom', '000660', 'SK하이닉스');

    expect(mockState.addKiwoomSession).toHaveBeenCalledTimes(1);
    expect(mockState.addKiwoomSession).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: 'S2',
        status: 'awaiting_approval',
        awaitingApproval: true,
      })
    );
    expect(mockWsManager.connect).toHaveBeenCalledWith('S2', expect.anything());
    expect(mockState.setActiveKiwoomSession).toHaveBeenCalledWith('S2');
  });

  it('position_exists:true surfaces the held-position notice', async () => {
    startKRStockAnalysis.mockResolvedValue({
      session_id: 'S1', stk_cd: '005930', stk_nm: '삼성전자', status: 'started',
      message: 'ok', duplicate: false, position_exists: true,
    });
    const { result } = renderHook(() => useStartAnalysis());

    const out = await result.current('kiwoom', '005930', '삼성전자');

    expect(out.positionExists).toBe(true);
    expect(mockState.setInfoNotice).toHaveBeenCalledTimes(1);
    expect(mockState.setInfoNotice).toHaveBeenCalledWith(expect.stringContaining('이미 보유 중'));
  });

  it('duplicate:true does not open a second WS connection when one is already live', async () => {
    mockState.kiwoom.sessions = [];
    mockWsManager.has.mockReturnValue(true);
    startKRStockAnalysis.mockResolvedValue({
      session_id: 'S3', stk_cd: '005930', stk_nm: '삼성전자', status: 'running',
      message: 'dup', duplicate: true, position_exists: false,
    });
    const { result } = renderHook(() => useStartAnalysis());

    await result.current('kiwoom', '005930', '삼성전자');

    expect(mockWsManager.connect).not.toHaveBeenCalled();
  });
});
