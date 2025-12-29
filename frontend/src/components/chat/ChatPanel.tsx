/**
 * Chat Panel Component
 *
 * Hybrid chat interface for user-agent communication.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User, Loader2 } from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import { useStore, selectChat } from '@/store';
import { format } from 'date-fns';
import { ProposalChatMessage } from './ProposalChatMessage';
import { sendChatMessage } from '@/api/client';
import type { ChatMessageRole } from '@/types';

export function ChatPanel() {
  const { messages, isTyping } = useStore(useShallow(selectChat));
  const addChatMessage = useStore((state) => state.addChatMessage);
  const setIsTyping = useStore((state) => state.setIsTyping);

  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Build structured trading context (Phase 13)
  const buildTradingContext = useCallback(() => {
    const state = useStore.getState();

    // Find active or most recent analysis
    let activeAnalysis: {
      ticker: string;
      displayName: string;
      marketType: string;
      status: string;
      recommendation?: string;
      confidence?: number;
      currentPrice?: number;
      entryPrice?: number;
      stopLoss?: number;
      takeProfit?: number;
      keySignals?: string[];
    } | undefined;

    // Check Kiwoom (Korean stock) session
    const kiwoomSession = state.kiwoom.sessions.find(
      s => s.sessionId === state.kiwoom.activeSessionId
    );
    if (kiwoomSession) {
      activeAnalysis = {
        ticker: kiwoomSession.ticker,
        displayName: kiwoomSession.displayName,
        marketType: 'kiwoom',
        status: kiwoomSession.status,
        recommendation: kiwoomSession.tradeProposal?.action,
        entryPrice: kiwoomSession.tradeProposal?.entry_price,
        stopLoss: kiwoomSession.tradeProposal?.stop_loss,
        takeProfit: kiwoomSession.tradeProposal?.take_profit,
        keySignals: kiwoomSession.reasoningLog?.slice(-3),
      };
    }

    // Check Coin session
    if (!activeAnalysis && state.coin.activeSessionId) {
      activeAnalysis = {
        ticker: state.coin.market,
        displayName: state.coin.market,
        marketType: 'coin',
        status: state.coin.status,
        recommendation: state.coin.tradeProposal?.action,
        entryPrice: state.coin.tradeProposal?.entry_price,
        stopLoss: state.coin.tradeProposal?.stop_loss,
        takeProfit: state.coin.tradeProposal?.take_profit,
      };
    }

    // Check Stock (US) session
    if (!activeAnalysis && state.stock.activeSessionId) {
      activeAnalysis = {
        ticker: state.stock.ticker,
        displayName: state.stock.ticker,
        marketType: 'stock',
        status: state.stock.status,
        recommendation: state.stock.tradeProposal?.action,
        entryPrice: state.stock.tradeProposal?.entry_price,
        stopLoss: state.stock.tradeProposal?.stop_loss,
        takeProfit: state.stock.tradeProposal?.take_profit,
      };
    }

    // Get recent trade decisions from history
    const recentDecisions: Array<{
      ticker: string;
      displayName: string;
      action: string;
      tradeAction: string;
      timestamp: string;
      quantity?: number;
      price?: number;
    }> = [];

    // Check Kiwoom history for approved/rejected decisions
    state.kiwoom.history.slice(-5).forEach(h => {
      if (h.status === 'completed' && h.tradeProposal) {
        recentDecisions.push({
          ticker: h.ticker,
          displayName: h.stk_nm || h.ticker,
          action: 'approved',  // If completed with proposal, it was approved
          tradeAction: h.tradeProposal.action || 'HOLD',
          timestamp: new Date(h.timestamp).toISOString(),
          quantity: h.tradeProposal.quantity,
          price: h.tradeProposal.entry_price,
        });
      }
    });

    return {
      activeAnalysis,
      recentDecisions,
    };
  }, []);

  // Build chat history for context
  const buildHistory = useCallback(() => {
    return messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({
        role: m.role,
        content: m.content,
      }));
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isSending) return;

    const userMessage = input.trim();
    setInput('');

    // Add user message
    addChatMessage({
      role: 'user',
      content: userMessage,
    });

    // Send to backend
    setIsSending(true);
    setIsTyping(true);

    try {
      const tradingContext = buildTradingContext();
      const history = buildHistory();

      // Phase 13: Send structured trading context
      const response = await sendChatMessage(userMessage, {
        tradingContext,
        history,
      });

      // Add assistant response
      addChatMessage({
        role: 'assistant',
        content: response.message,
      });
    } catch (error) {
      console.error('Chat failed:', error);
      addChatMessage({
        role: 'system',
        content: '응답 생성에 실패했습니다. 다시 시도해 주세요.',
      });
    } finally {
      setIsSending(false);
      setIsTyping(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface-light">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <h2 className="font-semibold flex items-center gap-2">
          <Bot className="w-5 h-5 text-blue-400" />
          Trading Assistant
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Ask questions or review analysis
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-hide">
        {messages.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>Start a conversation or begin analysis</p>
          </div>
        ) : (
          messages.map((message) => {
            // Render proposal messages differently
            if (message.role === 'proposal' && message.metadata?.proposal) {
              return (
                <ProposalChatMessage
                  key={message.id}
                  proposal={message.metadata.proposal}
                  timestamp={message.timestamp}
                />
              );
            }
            return <ChatMessage key={message.id} message={message} />;
          })
        )}

        {/* Typing Indicator */}
        {isTyping && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center">
              <Bot className="w-4 h-4 text-blue-400" />
            </div>
            <div className="bg-surface rounded-lg px-4 py-2">
              <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="p-4 border-t border-border"
      >
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              isSending
                ? 'Generating response...'
                : 'Ask about analysis or trading...'
            }
            disabled={isSending}
            className="input flex-1"
          />
          <button
            type="submit"
            disabled={!input.trim() || isSending}
            className="btn-primary p-3"
          >
            {isSending ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

interface ChatMessageProps {
  message: {
    id: string;
    role: ChatMessageRole;
    content: string;
    timestamp: Date;
  };
}

function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  if (isSystem) {
    return (
      <div className="text-center">
        <span className="text-xs text-gray-500 bg-surface px-3 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center ${
          isUser ? 'bg-blue-600' : 'bg-blue-600/20'
        }`}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-blue-400" />
        )}
      </div>

      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-surface text-gray-100'
        }`}
      >
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        <span
          className={`text-xs mt-1 block ${
            isUser ? 'text-blue-200' : 'text-gray-500'
          }`}
        >
          {format(message.timestamp, 'HH:mm')}
        </span>
      </div>
    </div>
  );
}
