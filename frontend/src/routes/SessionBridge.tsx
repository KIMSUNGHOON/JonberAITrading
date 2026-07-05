// frontend/src/routes/SessionBridge.tsx
// Bridges the URL :sessionId into store.selectedSessionId so the detail pages
// (which read selectedSessionId) work unchanged.
import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useStore } from '@/store';

export function SessionBridge({ children }: { children: React.ReactNode }) {
  const { sessionId } = useParams();
  const setSelectedSessionId = useStore((s) => s.setSelectedSessionId);
  useEffect(() => {
    if (sessionId) setSelectedSessionId(sessionId);
  }, [sessionId, setSelectedSessionId]);
  return <>{children}</>;
}
