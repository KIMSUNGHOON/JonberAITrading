/**
 * Markdown Renderer Component
 *
 * Simple Markdown renderer for displaying formatted content.
 * Supports: headers, bold, italic, code blocks, lists, and trading-specific highlights.
 */

import { useMemo } from 'react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  compact?: boolean;
}

export function MarkdownRenderer({ content, className = '', compact = false }: MarkdownRendererProps) {
  const renderedHtml = useMemo(() => {
    let html = content;

    // Escape HTML first
    html = html
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, _lang, code) => {
      const padding = compact ? 'p-2' : 'p-3';
      return `<pre class="bg-surface rounded-lg ${padding} my-2 overflow-x-auto text-xs font-mono text-gray-300 border border-gray-700"><code>${code.trim()}</code></pre>`;
    });

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code class="bg-surface px-1.5 py-0.5 rounded text-xs font-mono text-blue-400">$1</code>');

    // Bold (**...**)
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-white">$1</strong>');

    // Italic (*...*)
    html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-300">$1</em>');

    // Headers (## ...)
    if (!compact) {
      html = html.replace(/^### (.+)$/gm, '<h4 class="font-semibold text-white mt-3 mb-1">$1</h4>');
      html = html.replace(/^## (.+)$/gm, '<h3 class="font-bold text-white mt-3 mb-1 text-lg">$1</h3>');
      html = html.replace(/^# (.+)$/gm, '<h2 class="font-bold text-white mt-3 mb-2 text-xl">$1</h2>');
    } else {
      html = html.replace(/^###? (.+)$/gm, '<p class="font-semibold text-white mt-2 mb-1">$1</p>');
      html = html.replace(/^# (.+)$/gm, '<p class="font-bold text-white mt-2 mb-1">$1</p>');
    }

    // Bullet lists (- ...)
    html = html.replace(/^[-•] (.+)$/gm, '<li class="ml-4 text-gray-300 flex items-start gap-2"><span class="text-gray-500">•</span><span>$1</span></li>');

    // Numbered lists (1. ...)
    html = html.replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 text-gray-300 flex items-start gap-2"><span class="text-gray-500 min-w-[1.5rem]">$1.</span><span>$2</span></li>');

    // Line breaks
    html = html.replace(/\n/g, '<br/>');

    // Trading-specific highlights
    const patterns = [
      { regex: /\b(STRONG_BUY|strong_buy)\b/gi, className: 'text-green-400 font-bold bg-green-500/20 px-1 rounded' },
      { regex: /\b(BUY)\b/g, className: 'text-green-400 font-semibold' },
      { regex: /\b(STRONG_SELL|strong_sell)\b/gi, className: 'text-red-400 font-bold bg-red-500/20 px-1 rounded' },
      { regex: /\b(SELL)\b/g, className: 'text-red-400 font-semibold' },
      { regex: /\b(HOLD)\b/g, className: 'text-yellow-400 font-semibold' },
      { regex: /(\d+\.?\d*%)/g, className: 'text-blue-400 font-medium' },
      { regex: /(\$[\d,]+\.?\d*)/g, className: 'text-green-400 font-medium' },
      { regex: /(Confidence:\s*[\d.]+%?)/gi, className: 'text-purple-400 font-medium' },
      { regex: /(Risk Score:?\s*[\d.]+%?)/gi, className: 'text-red-400 font-medium' },
      { regex: /(RSI:?\s*[\d.]+)/gi, className: 'text-blue-400' },
      { regex: /(P\/E:?\s*[\d.]+)/gi, className: 'text-purple-400' },
      { regex: /(Support:?\s*\$?[\d,.]+)/gi, className: 'text-green-400' },
      { regex: /(Resistance:?\s*\$?[\d,.]+)/gi, className: 'text-red-400' },
      { regex: /(bullish|uptrend|positive)/gi, className: 'text-green-400' },
      { regex: /(bearish|downtrend|negative)/gi, className: 'text-red-400' },
      { regex: /(neutral|sideways)/gi, className: 'text-yellow-400' },
    ];

    patterns.forEach(({ regex, className }) => {
      html = html.replace(regex, `<span class="${className}">$1</span>`);
    });

    return html;
  }, [content, compact]);

  return (
    <div
      className={`prose prose-sm prose-invert max-w-none leading-relaxed ${className}`}
      dangerouslySetInnerHTML={{ __html: renderedHtml }}
    />
  );
}

// Export for convenience
export default MarkdownRenderer;
