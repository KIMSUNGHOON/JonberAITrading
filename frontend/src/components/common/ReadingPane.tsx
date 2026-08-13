/**
 * ReadingPane — the editorial typography register for prose BODIES (agent
 * messages, analysis report text). This is the ONLY place font-sans appears:
 * dense-mono everywhere, proportional only inside a reading pane. Provides a
 * ~65ch measure + generous leading so Korean analysis prose reads well.
 */
import type { ReactNode } from 'react';

export function ReadingPane({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`font-sans text-sm text-ink leading-relaxed max-w-[65ch] ${className}`}>
      {children}
    </div>
  );
}
