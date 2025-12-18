/**
 * Chat Panel Component
 *
 * Hybrid chat interface for user-agent communication.
 */

import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2 } from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import { useStore } from '@/store';
import { format } from 'date-fns';

export function ChatPanel() {
  const { messages, isTyping } = useStore(
    useShallow((state) => ({
      messages: state.messages,
      isTyping: state.isTyping,
    }))
  );
  const addChatMessage = useStore((state) => state.addChatMessage);
  const status = useStore((state) => state.status);

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    addChatMessage({
      role: 'user',
      content: input.trim(),
    });

    setInput('');

    // TODO: Send to backend for processing
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
          messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))
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
              status === 'running'
                ? 'Analysis in progress...'
                : 'Ask about analysis or enter a ticker...'
            }
            disabled={status === 'running'}
            className="input flex-1"
          />
          <button
            type="submit"
            disabled={!input.trim() || status === 'running'}
            className="btn-primary p-3"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </form>
    </div>
  );
}

interface ChatMessageProps {
  message: {
    id: string;
    role: 'user' | 'assistant' | 'system';
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
