/**
 * dev 프록시 백엔드 자동 탐지 (포트 점유 대응).
 *
 * :8000을 타 프로젝트(예: AgentHub)가 점유하면 우리 백엔드는 런처가 다음 빈
 * 포트로 비켜 뜬다 — vite가 포트를 스캔해 "우리 앱"을 식별 응답
 * (/api/settings/trading-mode 의 kiwoom + master_enabled 필드)으로 찾아낸다.
 * 아무 200 응답이나 믿으면 타 FastAPI 앱에 오연결되므로 필드 검증이 핵심.
 */
import { describe, expect, it, vi } from 'vitest';

import { detectBackendOrigin } from './detectBackendOrigin';

function fetchStub(byPort: Record<number, unknown | Error>) {
  return vi.fn(async (input: URL | RequestInfo) => {
    const port = Number(new URL(String(input)).port);
    const entry = byPort[port];
    if (entry === undefined) throw new Error('ECONNREFUSED');
    if (entry instanceof Error) throw entry;
    return {
      ok: true,
      json: async () => entry,
    } as Response;
  }) as unknown as typeof fetch;
}

describe('detectBackendOrigin', () => {
  it('skips a foreign app on :8000 and picks our backend on :8001', async () => {
    const fetchFn = fetchStub({
      8000: { name: 'AgentHub', status: 'ok' }, // 타 앱 — 식별 필드 없음
      8001: { kiwoom: 'hitl', master_enabled: false },
    });
    const origin = await detectBackendOrigin({ ports: [8000, 8001], fetchFn });
    expect(origin).toBe('http://127.0.0.1:8001');
  });

  it('returns the first matching port when ours is on :8000', async () => {
    const fetchFn = fetchStub({
      8000: { kiwoom: 'autonomous', master_enabled: true },
    });
    const origin = await detectBackendOrigin({ ports: [8000, 8001], fetchFn });
    expect(origin).toBe('http://127.0.0.1:8000');
  });

  it('returns null when nothing identifies as our backend', async () => {
    const fetchFn = fetchStub({
      8000: { name: 'AgentHub' },
      8001: new Error('ECONNREFUSED'),
    });
    const origin = await detectBackendOrigin({ ports: [8000, 8001], fetchFn });
    expect(origin).toBeNull();
  });

  it('probes the identification endpoint, not just any 200', async () => {
    const fetchFn = fetchStub({
      8001: { kiwoom: 'hitl', master_enabled: false },
    });
    await detectBackendOrigin({ ports: [8001], fetchFn });
    expect(fetchFn).toHaveBeenCalledWith(
      'http://127.0.0.1:8001/api/settings/trading-mode',
      expect.anything(),
    );
  });
});
