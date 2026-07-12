/**
 * 브로커 API 오류의 사용자 친화 변환 (R5-P2 t1).
 *
 * 감사 발견: Positions 페이지가 Upbit 401 원문("[401] no_authorization_ip:
 * This is not a verified IP.")을 빨간 배너로 그대로 노출 — 사용자는 무엇을
 * 해야 하는지 알 수 없다. 원문은 title(툴팁)로 보존하되 본문은 조치 가능한
 * 안내로 바꾼다.
 */
import { describe, expect, it } from 'vitest';

import { friendlyCoinError } from './errors';

describe('friendlyCoinError', () => {
  it('maps Upbit unverified-IP 401 to an actionable Korean message', () => {
    const msg = friendlyCoinError(
      'Failed to fetch accounts: [401] no_authorization_ip: This is not a verified IP.',
    );
    expect(msg).toContain('Upbit');
    expect(msg).toContain('IP');
    expect(msg).not.toContain('no_authorization_ip');
  });

  it('maps generic 401/invalid key to a key-setup hint', () => {
    const msg = friendlyCoinError('[401] invalid_access_key');
    expect(msg).toContain('설정');
  });

  it('passes through unknown errors unchanged', () => {
    expect(friendlyCoinError('ECONNREFUSED')).toBe('ECONNREFUSED');
  });
});
