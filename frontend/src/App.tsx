/**
 * Main Application Component
 *
 * Hybrid Layout: Dashboard + Chat Interface
 */

import { useEffect } from 'react';
import { useStore } from '@/store';
import { Header } from '@/components/layout/Header';
import { Sidebar } from '@/components/layout/Sidebar';
import { MainContent } from '@/components/layout/MainContent';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ApprovalDialog } from '@/components/approval/ApprovalDialog';
import { MobileNav } from '@/components/layout/MobileNav';

function App() {
  const showApprovalDialog = useStore((state) => state.showApprovalDialog);
  const error = useStore((state) => state.error);
  const setError = useStore((state) => state.setError);

  // Clear error after 5 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [error, setError]);

  return (
    <div className="h-screen bg-surface flex flex-col overflow-hidden">
      {/* Header - Fixed height */}
      <Header />

      {/* Error Toast */}
      {error && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-bear/90 text-white px-6 py-3 rounded-lg shadow-lg">
          {error}
        </div>
      )}

      {/* Main Layout - Takes remaining height */}
      <div className="flex-1 flex min-h-0">
        {/* Sidebar - Hidden on mobile, fixed width */}
        <aside className="hidden lg:flex lg:flex-col w-56 border-r border-border flex-shrink-0">
          <Sidebar />
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col lg:flex-row min-h-0 min-w-0">
          {/* Dashboard Panel - Scrollable */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <MainContent />
          </div>

          {/* Chat Panel - Fixed width, hidden on mobile */}
          <div className="hidden md:flex md:flex-col w-80 border-l border-border flex-shrink-0">
            <ChatPanel />
          </div>
        </main>
      </div>

      {/* Mobile Navigation */}
      <MobileNav />

      {/* Approval Dialog */}
      {showApprovalDialog && <ApprovalDialog />}
    </div>
  );
}

export default App;
