/**
 * Reasoning tile — a dense "tail -f" of the active market's agent reasoning.
 *
 * PASSIVE store subscriber: the analysis-launch flow owns the WebSocket and
 * appends into the store; this tile reads reasoningLog + currentStage + status
 * for the active market and renders them via the shared ReasoningWire. Empty
 * until a session streams.
 */
import { useStore, selectReasoningLog, selectStatus } from '@/store';
import { Awaiting } from './shared';
import { ReasoningWire } from '@/components/common/ReasoningWire';

export function ReasoningPanel() {
  const reasoningLog = useStore(selectReasoningLog);
  const status = useStore(selectStatus);
  const currentStage = useStore((s) =>
    s.activeMarket === 'stock'
      ? s.stock.currentStage
      : s.activeMarket === 'coin'
        ? s.coin.currentStage
        : s.kiwoom.currentStage,
  );
  const running = status === 'running';

  if (reasoningLog.length === 0 && !running) {
    return <Awaiting label="활성 세션 없음 · :analyze <종목> 실행 시 스트리밍" />;
  }

  return (
    <ReasoningWire
      entries={reasoningLog}
      running={running}
      currentStage={currentStage ?? undefined}
      className="h-full"
    />
  );
}
