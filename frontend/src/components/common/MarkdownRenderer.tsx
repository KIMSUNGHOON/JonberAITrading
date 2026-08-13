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
      return `<pre class="bg-elevated rounded ${padding} my-2 overflow-x-auto text-xs font-mono text-ink border border-hairline"><code>${code.trim()}</code></pre>`;
    });

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, '<code class="bg-elevated px-1.5 py-0.5 rounded text-xs font-mono text-accent">$1</code>');

    // Bold (**...**)
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-ink">$1</strong>');

    // Italic (*...*)
    html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-muted">$1</em>');

    // Headers (## ...)
    if (!compact) {
      html = html.replace(/^### (.+)$/gm, '<h4 class="font-semibold text-ink mt-3 mb-1">$1</h4>');
      html = html.replace(/^## (.+)$/gm, '<h3 class="font-bold text-ink mt-3 mb-1 text-lg">$1</h3>');
      html = html.replace(/^# (.+)$/gm, '<h2 class="font-bold text-ink mt-3 mb-2 text-xl">$1</h2>');
    } else {
      html = html.replace(/^###? (.+)$/gm, '<p class="font-semibold text-ink mt-2 mb-1">$1</p>');
      html = html.replace(/^# (.+)$/gm, '<p class="font-bold text-ink mt-2 mb-1">$1</p>');
    }

    // Bullet lists (- ...)
    html = html.replace(/^[-•] (.+)$/gm, '<li class="ml-4 text-muted flex items-start gap-2"><span class="text-dim">•</span><span>$1</span></li>');

    // Numbered lists (1. ...)
    html = html.replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 text-muted flex items-start gap-2"><span class="text-dim min-w-[1.5rem]">$1.</span><span>$2</span></li>');

    // Horizontal rules (--- or ***)
    html = html.replace(/^[-*]{3,}$/gm, '<hr class="border-hairline my-2" />');

    // Clean up line breaks - multiple newlines become a single paragraph break
    // First, collapse multiple newlines into double newlines (paragraph marker)
    html = html.replace(/\n{3,}/g, '\n\n');

    // Single newlines after block elements (headers, lists, hr) should be removed
    html = html.replace(/<\/(h[1-4]|p|li|pre|hr)>\n/g, '</$1>');

    // Double newlines become paragraph breaks (single <br/>)
    html = html.replace(/\n\n/g, '<br/>');

    // Single newlines within text become spaces (for proper line wrapping)
    html = html.replace(/\n/g, ' ');

    // Trading-specific highlights
    const patterns = [
      { regex: /\b(STRONG_BUY|strong_buy)\b/gi, className: 'text-up font-bold bg-up/20 px-1 rounded' },
      { regex: /\b(BUY)\b/g, className: 'text-up font-semibold' },
      { regex: /\b(STRONG_SELL|strong_sell)\b/gi, className: 'text-down font-bold bg-down/20 px-1 rounded' },
      { regex: /\b(SELL)\b/g, className: 'text-down font-semibold' },
      { regex: /\b(HOLD)\b/g, className: 'text-warn font-semibold' },
      { regex: /(\d+\.?\d*%)/g, className: 'text-accent font-medium' },
      { regex: /(\$[\d,]+\.?\d*)/g, className: 'text-accent font-medium' },
      { regex: /(Confidence:\s*[\d.]+%?)/gi, className: 'text-accent font-medium' },
      { regex: /(Risk Score:?\s*[\d.]+%?)/gi, className: 'text-down font-medium' },
      { regex: /(RSI:?\s*[\d.]+)/gi, className: 'text-accent' },
      { regex: /(P\/E:?\s*[\d.]+)/gi, className: 'text-accent' },
      { regex: /(Support:?\s*\$?[\d,.]+)/gi, className: 'text-up' },
      { regex: /(Resistance:?\s*\$?[\d,.]+)/gi, className: 'text-down' },
      { regex: /(bullish|uptrend|positive)/gi, className: 'text-up' },
      { regex: /(bearish|downtrend|negative)/gi, className: 'text-down' },
      { regex: /(neutral|sideways)/gi, className: 'text-warn' },
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
