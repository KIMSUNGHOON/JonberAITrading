// frontend/src/hooks/useCommandPalette.ts
// Open/close state for the ⌘K command palette + the global keyboard shortcut
// that toggles it. Kept separate from CommandPalette.tsx so the trigger
// (TerminalShell's command bar) and the modal itself can share the same
// open/setOpen state without prop-drilling a listener through both.
import { useEffect, useState } from 'react';

export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return { open, setOpen };
}
