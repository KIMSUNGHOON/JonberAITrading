/**
 * Reasoning tile — a dense "tail -f" of the active market's agent reasoning.
 *
 * PASSIVE store subscriber: the analysis-launch flow (BasketWidget / ticker
 * inputs) owns the WebSocket and appends into the store; this tile only reads
 * reasoningLog + currentStage + status for the active market and renders raw
 * monospace lines, colorizing the [Agent] prefix. When a session is running it
 * shows the current stage as a pulsing head. Empty until a session streams.
 */
import { useEffect, useRef } from 'react';
import { useStore, selectReasoningLog, selectStatus } from '@/store';
import { Awaiting } from './shared';

/** Map an [Agent] prefix to a terminal token color. */
function prefixColor(prefix: string): string {
  const p = prefix.toLowerCase();
  if (p.startsWith('technical')) return 'text-accent';
  if (p.startsWith('fundamental')) return 'text-accent';
  if (p.startsWith('sentiment')) return 'text-warn';
  if (p.startsWith('risk')) return 'text-down';
  if (p.startsWith('strategic')) return 'text-up';
  if (p.startsWith('execution')) return 'text-up';
  if (p.startsWith('hitl')) return 'text-warn';
  return 'text-muted';
}

function Line({ raw }: { raw: string }) {
  const m = raw.match(/^\[([^\]]+)\]\s*([\s\S]*)$/);
  if (!m) return <span className="text-muted">{raw}</span>;
  return (
    <>
      <span className={`${prefixColor(m[1])} font-semibold`}>[{m[1]}]</span>{' '}
      <span className="text-ink/90">{m[2]}</span>
    </>
  );
}

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
  const endRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the newest line as the tail grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [reasoningLog.length, currentStage]);

  if (reasoningLog.length === 0 && !running) {
    return <Awaiting label="활성 세션 없음 · :analyze <종목> 실행 시 스트리밍" />;
  }

  return (
    <div className="h-full overflow-auto px-2.5 py-1.5 text-[11px] leading-[1.5] font-mono">
      {reasoningLog.map((line, i) => (
        <div key={i} className="whitespace-pre-wrap break-words py-0.5 border-b border-hairline/30">
          <span className="text-dim mr-1.5 select-none tabular-nums">{String(i + 1).padStart(2, '0')}</span>
          <Line raw={line} />
        </div>
      ))}
      {running && (
        <div className="flex items-center gap-2 py-1 text-accent">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span>{currentStage || 'Thinking'}…</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
