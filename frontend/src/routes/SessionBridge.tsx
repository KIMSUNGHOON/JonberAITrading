// frontend/src/routes/SessionBridge.tsx
// Bridges the URL :sessionId into store.selectedSessionId so the detail pages
// (which read selectedSessionId) work unchanged, AND ensures the per-session
// live stream is connected. Start paths that don't go through useStartAnalysis
// (watchlist reanalyze, scanner "analyze", re-viewing a running session) add a
// session and navigate here without opening /ws/session — so the page stayed
// blank while the analysis ran server-side (only Telegram fired). Connecting the
// stream here fixes every such route in one place.
import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useStore } from '@/store';
import { ensureKiwoomSessionStreaming } from '@/api/kiwoomSessionHandlers';

export function SessionBridge({ children }: { children: React.ReactNode }) {
  const { sessionId } = useParams();
  const setSelectedSessionId = useStore((s) => s.setSelectedSessionId);
  useEffect(() => {
    if (sessionId) {
      setSelectedSessionId(sessionId);
      ensureKiwoomSessionStreaming(sessionId);
    }
  }, [sessionId, setSelectedSessionId]);
  return <>{children}</>;
}
