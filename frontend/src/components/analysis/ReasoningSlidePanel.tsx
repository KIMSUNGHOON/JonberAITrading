/**
 * ReasoningSlidePanel Component
 *
 * Slide-out panel for detailed reasoning log view.
 * Shows full agent reasoning with timestamps and stages.
 */

import { useEffect, useRef } from 'react';
import { X, Brain, ChevronRight } from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import { useStore } from '@/store';

interface ReasoningSlidePanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ReasoningSlidePanel({ isOpen, onClose }: ReasoningSlidePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Get reasoning log based on current market - use useShallow to prevent infinite re-renders
  const { ticker, displayName, reasoningLog, currentStage, status } = useStore(
    useShallow((state) => {
      switch (state.activeMarket) {
        case 'stock':
          return {
            ticker: state.stock.ticker,
            displayName: state.stock.ticker,
            reasoningLog: state.stock.reasoningLog,
            currentStage: state.stock.currentStage,
            status: state.stock.status,
          };
        case 'coin':
          return {
            ticker: state.coin.market,
            displayName: state.coin.koreanName || state.coin.market.replace('KRW-', ''),
            reasoningLog: state.coin.reasoningLog,
            currentStage: state.coin.currentStage,
            status: state.coin.status,
          };
        case 'kiwoom':
          return {
            ticker: state.kiwoom.stk_cd,
            displayName: state.kiwoom.stk_nm || state.kiwoom.stk_cd,
            reasoningLog: state.kiwoom.reasoningLog,
            currentStage: state.kiwoom.currentStage,
            status: state.kiwoom.status,
          };
      }
    })
  );

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Auto-scroll to bottom when new entries come in
  useEffect(() => {
    if (isOpen && panelRef.current) {
      panelRef.current.scrollTop = panelRef.current.scrollHeight;
    }
  }, [isOpen, reasoningLog.length]);

  if (!isOpen) return null;

  // Parse reasoning entries to extract stage info
  const parseEntry = (entry: string) => {
    // Try to extract stage from entry (format: "[Stage] content")
    const stageMatch = entry.match(/^\[([^\]]+)\]/);
    if (stageMatch) {
      return {
        stage: stageMatch[1],
        content: entry.slice(stageMatch[0].length).trim(),
      };
    }
    return { stage: null, content: entry };
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 h-full w-full max-w-md bg-surface-dark border-l border-border z-50 flex flex-col shadow-2xl transform transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-blue-400" />
            <div>
              <h3 className="font-semibold text-sm">Agent Reasoning</h3>
              <p className="text-xs text-gray-400">
                {displayName}
                {displayName !== ticker && ` (${ticker})`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-200 hover:bg-surface rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Current Stage */}
        {status === 'running' && currentStage && (
          <div className="px-4 py-2 bg-blue-500/10 border-b border-border flex items-center gap-2">
            <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
            <span className="text-sm text-blue-400">{currentStage}</span>
          </div>
        )}

        {/* Reasoning Log */}
        <div
          ref={panelRef}
          className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin scrollbar-thumb-gray-700"
        >
          {reasoningLog.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <Brain className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">No reasoning entries yet</p>
            </div>
          ) : (
            reasoningLog.map((entry, idx) => {
              const { stage, content } = parseEntry(entry);
              return (
                <div
                  key={idx}
                  className="group relative pl-4 border-l-2 border-gray-700 hover:border-blue-500 transition-colors"
                >
                  {/* Entry number */}
                  <div className="absolute -left-3 top-0 w-5 h-5 bg-surface-dark border border-gray-700 group-hover:border-blue-500 rounded-full flex items-center justify-center text-[10px] text-gray-500 group-hover:text-blue-400 transition-colors">
                    {idx + 1}
                  </div>

                  {/* Stage badge */}
                  {stage && (
                    <div className="flex items-center gap-1 mb-1">
                      <ChevronRight className="w-3 h-3 text-gray-500" />
                      <span className="text-xs text-blue-400 font-medium">{stage}</span>
                    </div>
                  )}

                  {/* Content */}
                  <p className="text-sm text-gray-300 leading-relaxed">
                    {content}
                  </p>
                </div>
              );
            })
          )}

          {/* Loading indicator for running sessions */}
          {status === 'running' && (
            <div className="flex items-center gap-2 text-gray-500 text-sm">
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
              <span>Thinking...</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border bg-surface flex items-center justify-between">
          <div className="text-xs text-gray-500">
            {reasoningLog.length} entries
          </div>
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200 hover:bg-surface-light rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </>
  );
}
