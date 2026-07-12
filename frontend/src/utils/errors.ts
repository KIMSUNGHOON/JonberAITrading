/**
 * 브로커 API 오류의 사용자 친화 변환.
 *
 * 원문 오류는 호출부에서 title(툴팁)으로 보존하고, 화면 본문에는 조치 가능한
 * 안내를 보여준다. 알 수 없는 오류는 그대로 통과시킨다 (정직성 유지 — 오류를
 * 숨기지 않는다).
 */

export function friendlyCoinError(message: string): string {
  if (message.includes('no_authorization_ip')) {
    return (
      'Upbit API 키에 현재 IP가 등록되어 있지 않습니다. ' +
      'Upbit 마이페이지에서 IP를 등록하거나, 코인 기능을 사용하지 않으면 무시해도 됩니다.'
    );
  }
  if (message.includes('401') || message.includes('invalid_access_key')) {
    return 'Upbit API 키가 유효하지 않습니다. 설정 → Upbit API에서 키를 확인하세요.';
  }
  return message;
}
