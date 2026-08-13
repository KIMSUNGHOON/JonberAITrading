/**
 * LoopLivenessChip — shell status-bar indicator for the agent-chat
 * coordinator loop (watch-list monitoring + discussion scheduling). See
 * hooks/useLoopLiveness for the active/stale/off/unknown classification.
 */
import { useLoopLiveness } from '@/hooks/useLoopLiveness';

const LEVEL_STYLES: Record<string, string> = {
  active: 'text-up',
  stale: 'text-warn',
  off: 'text-dim',
  unknown: 'text-dim',
};

const LEVEL_LABELS: Record<string, string> = {
  active: 'LOOP ACTIVE',
  stale: 'LOOP STALE',
  off: 'LOOP OFF',
  unknown: 'LOOP —',
};

const LEVEL_TITLES: Record<string, string> = {
  active: '에이전트 챗 루프 정상 동작 중',
  stale: '루프가 응답 없음 — 워치리스트 모니터링이 멈췄을 수 있습니다',
  off: '에이전트 챗 코디네이터가 꺼져 있습니다',
  unknown: '루프 상태 확인 불가',
};

export function LoopLivenessChip() {
  const { level } = useLoopLiveness();
  return (
    <span className={LEVEL_STYLES[level]} title={LEVEL_TITLES[level]}>
      {LEVEL_LABELS[level]}
    </span>
  );
}
