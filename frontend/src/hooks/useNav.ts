// frontend/src/hooks/useNav.ts
import { useNavigate, useLocation } from 'react-router-dom';
import { viewToPath, pathToView, type ViewKey } from '@/nav';

/** Drop-in replacement for the old setCurrentView(view). */
export function useGoTo() {
  const navigate = useNavigate();
  return (view: ViewKey, sessionId?: string) => navigate(viewToPath(view, sessionId));
}

/** The current top-level view, derived from the URL (nav active-state). */
export function useActiveView(): ViewKey {
  const { pathname } = useLocation();
  return pathToView(pathname);
}
