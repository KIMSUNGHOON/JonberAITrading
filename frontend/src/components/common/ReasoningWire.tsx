/**
 * ReasoningWire — presentation-only dense "tail -f" of agent reasoning lines.
 *
 * Used by WorkflowPage (the dashboard's REASONING tile was removed as a perf
 * fix — this component's uncapped-log + per-delta scrollIntoView was one of
 * the two root causes of streaming-frequency re-renders). Renders raw
 * monospace lines with a numbered gutter, colorizes the [Agent] prefix, shows a
 * pulsing head for the current stage while running, and auto-scrolls to newest.
 * All data arrives via props — no store coupling.
 */
import { useEffect, useRef } from 'react';

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

interface ReasoningWireProps {
  entries: string[];
  running: boolean;
  currentStage?: string;
  className?: string;
}

export function ReasoningWire({ entries, running, currentStage, className }: ReasoningWireProps) {
  const endRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the newest line as the tail grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [entries.length, currentStage]);

  return (
    <div className={`overflow-auto px-2.5 py-1.5 text-[11px] leading-[1.5] font-mono ${className ?? ''}`}>
      {entries.map((line, i) => (
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
