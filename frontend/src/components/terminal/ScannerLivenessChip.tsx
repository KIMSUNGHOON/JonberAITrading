/**
 * ScannerLivenessChip — shell status-bar indicator for the background
 * KOSPI/KOSDAQ scanner loop. Unlike the agent-chat coordinator
 * (LoopLivenessChip), the scanner is an on-demand one-shot job: idle/paused/
 * completed/error are healthy resting states, not evidence of death. See
 * hooks/useScannerLiveness for the active/idle/stale/unknown classification.
 */
import { useScannerLiveness } from '@/hooks/useScannerLiveness';

const LEVEL_STYLES: Record<string, string> = {
  active: 'text-up',
  stale: 'text-warn',
  idle: 'text-dim',
  unknown: 'text-dim',
};

const LEVEL_LABELS: Record<string, string> = {
  active: 'SCAN ACTIVE',
  stale: 'SCAN STALE',
  idle: 'SCAN IDLE',
  unknown: 'SCAN —',
};

const LEVEL_TITLES: Record<string, string> = {
  active: '백그라운드 스캐너 실행 중',
  stale: '스캐너가 실행 중이라고 보고하지만 응답이 없음 — 멈췄을 수 있습니다',
  idle: '스캐너 대기 중 (미시작 · 완료 · 일시정지)',
  unknown: '스캐너 상태 확인 불가',
};

export function ScannerLivenessChip() {
  const { level } = useScannerLiveness();
  return (
    <span className={LEVEL_STYLES[level]} title={LEVEL_TITLES[level]}>
      {LEVEL_LABELS[level]}
    </span>
  );
}
