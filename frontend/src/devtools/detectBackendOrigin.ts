/**
 * dev 프록시용 백엔드 자동 탐지.
 *
 * :8000이 다른 프로젝트에 점유되면 백엔드 런처(backend/run_dev.py)가 다음 빈
 * 포트로 비켜 뜬다. vite.config가 이 함수를 시작 시 1회 호출해 포트를 스캔하고,
 * "우리 앱"임을 /api/settings/trading-mode 응답의 kiwoom + master_enabled
 * 필드로 식별한다 — 아무 200이나 믿으면 같은 머신의 타 FastAPI 앱(예:
 * AgentHub)에 조용히 오연결되기 때문에 필드 검증이 필수다.
 */

export const DEFAULT_SCAN_PORTS = [8000, 8001, 8002, 8003, 8004, 8005];

const IDENTIFY_PATH = '/api/settings/trading-mode';

interface DetectOptions {
  ports?: number[];
  fetchFn?: typeof fetch;
  timeoutMs?: number;
}

export async function detectBackendOrigin({
  ports = DEFAULT_SCAN_PORTS,
  fetchFn = fetch,
  timeoutMs = 500,
}: DetectOptions = {}): Promise<string | null> {
  for (const port of ports) {
    const origin = `http://127.0.0.1:${port}`;
    try {
      const res = await fetchFn(`${origin}${IDENTIFY_PATH}`, {
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) continue;
      const body: unknown = await res.json();
      if (
        body !== null &&
        typeof body === 'object' &&
        'kiwoom' in body &&
        'master_enabled' in body
      ) {
        return origin;
      }
    } catch {
      // not listening / not ours — keep scanning
    }
  }
  return null;
}
