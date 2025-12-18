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
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Header */}
      <Header />

      {/* Error Toast */}
      {error && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-bear/90 text-white px-6 py-3 rounded-lg shadow-lg">
          {error}
        </div>
      )}

      {/* Main Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar - Hidden on mobile */}
        <aside className="hidden lg:block w-64 border-r border-border">
          <Sidebar />
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col lg:flex-row overflow-hidden">
          {/* Dashboard Panel */}
          <div className="flex-1 overflow-auto">
            <MainContent />
          </div>

          {/* Chat Panel - Collapsible on desktop, bottom sheet on mobile */}
          <div className="hidden md:block w-96 border-l border-border">
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
