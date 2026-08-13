/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── Dense Terminal Shell: single dark ramp ──
        canvas: '#0b0e11',   // app background
        card: '#161a1f',     // panels / blotters / tables
        elevated: '#1c222a', // modals, popovers, hover rows
        hairline: '#242c37', // 1px borders & dividers
        ink: '#e8ecf1',      // primary text
        muted: '#7b8794',    // secondary text / labels / axis
        dim: '#565e6b',      // tertiary / disabled / placeholder
        accent: '#f0b90b',   // the ONE accent — focus ring, active tab, primary CTA
        // Trading direction tokens — use for directional P&L TEXT (never a raw
        // green/red badge fill that could misread). Status/level tints
        // (bg-up/warn/down + /NN opacity) are OK.
        up: '#0ecb81',       // price up (Western green=up)
        down: '#f6465d',     // price down
        warn: '#f0a63a',     // genuine warnings only — NOT hold
        info: '#4b9fff',
        // Migration aliases — keep names alive so 353 raw green/red + 250 surface
        // sites don't break in one commit; per-file cleanup lands after.
        'bull': { DEFAULT: '#0ecb81', light: '#0ecb81', dark: '#0ecb81' },
        'bear': { DEFAULT: '#f6465d', light: '#f6465d', dark: '#f6465d' },
        'surface': { DEFAULT: '#161a1f', light: '#1c222a', dark: '#0b0e11' },
        'border': { DEFAULT: '#242c37', light: '#242c37' },
      },
      borderRadius: {
        // Collapse radius globally to a 6px cap (de-card): rounded-xl/2xl soften
        // with ZERO per-file edits.
        DEFAULT: '4px',
        sm: '3px',
        md: '4px',
        lg: '6px',
        xl: '6px',
        '2xl': '6px',
        '3xl': '6px',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-in': 'slideIn 0.4s ease-out forwards',
        'typing': 'typing 1.5s steps(30) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideIn: {
          '0%': { transform: 'translateX(-10px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        typing: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
      },
    },
    // Responsive breakpoints
    screens: {
      'xs': '475px',
      'sm': '640px',
      'md': '768px',
      'lg': '1024px',
      'xl': '1280px',
      '2xl': '1536px',
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
};
