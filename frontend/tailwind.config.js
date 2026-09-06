/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // All colors use CSS vars with space-separated RGB so opacity modifiers work (bg-x/20 etc.)
        bg: {
          primary:   'rgb(var(--bg-primary)   / <alpha-value>)',
          secondary: 'rgb(var(--bg-secondary) / <alpha-value>)',
          surface:   'rgb(var(--bg-surface)   / <alpha-value>)',
          tertiary:  'rgb(var(--bg-surface)   / <alpha-value>)',
          card:      'rgb(var(--bg-card)      / <alpha-value>)',
          elevated:  'rgb(var(--bg-elevated)  / <alpha-value>)',
          border:    'rgb(var(--bg-border)    / <alpha-value>)',
        },
        neon: {
          cyan:   'rgb(var(--accent-blue)    / <alpha-value>)',
          green:  'rgb(var(--accent-green)   / <alpha-value>)',
          red:    'rgb(var(--accent-red)     / <alpha-value>)',
          purple: 'rgb(var(--accent-purple)  / <alpha-value>)',
          amber:  'rgb(var(--accent-amber)   / <alpha-value>)',
          blue:   'rgb(var(--accent-blue)    / <alpha-value>)',
        },
        primary: 'rgb(var(--accent-blue)   / <alpha-value>)',
        success: 'rgb(var(--accent-green)  / <alpha-value>)',
        warning: 'rgb(var(--accent-amber)  / <alpha-value>)',
        danger:  'rgb(var(--accent-red)    / <alpha-value>)',
        text: {
          primary:   'rgb(var(--text-primary)   / <alpha-value>)',
          secondary: 'rgb(var(--text-secondary) / <alpha-value>)',
          muted:     'rgb(var(--text-muted)     / <alpha-value>)',
          bright:    'rgb(var(--text-bright)    / <alpha-value>)',
          dim:       'rgb(var(--text-dim)       / <alpha-value>)',
        },
        risk: {
          clean:      'rgb(var(--accent-green)  / <alpha-value>)',
          entity:     'rgb(var(--accent-blue)   / <alpha-value>)',
          bridge:     'rgb(var(--accent-amber)  / <alpha-value>)',
          medium:     'rgb(var(--accent-amber)  / <alpha-value>)',
          scam:       'rgb(var(--accent-orange) / <alpha-value>)',
          mixer:      'rgb(var(--accent-red)    / <alpha-value>)',
          sanctioned: 'rgb(var(--accent-purple) / <alpha-value>)',
          error:      'rgb(var(--text-muted)    / <alpha-value>)',
        },
        accent: {
          cyan:   'rgb(var(--accent-blue)   / <alpha-value>)',
          blue:   'rgb(var(--accent-blue)   / <alpha-value>)',
          indigo: 'rgb(var(--accent-indigo) / <alpha-value>)',
        },
        border: {
          DEFAULT: 'rgb(var(--bg-border) / <alpha-value>)',
          bright:  'rgb(var(--bg-border) / <alpha-value>)',
        },
      },
      fontFamily: {
        display: ['Roboto', 'sans-serif'],
        mono:    ["'Roboto Mono'", 'ui-monospace', 'monospace'],
        body:    ['Roboto', 'sans-serif'],
        sans:    ['Roboto', 'sans-serif'],
      },
      animation: {
        'fade-in':        'fade-in 0.25s ease-out',
        'slide-up':       'slide-up 0.25s ease-out',
        'slide-right':    'slide-right 0.2s ease-out',
        'data-in':        'data-in 0.25s ease-out',
        'pulse-soft':     'pulse-soft 3s ease-in-out infinite',
        'pulse-glow':     'pulse-soft 3s ease-in-out infinite',
        'shimmer':        'shimmer 2s linear infinite',
        'count-in':       'count-in 0.35s ease-out',
        'alert-flash':    'alert-flash 0.8s ease-in-out 3',
        'ring-ping':      'ring-ping 2.5s ease-out infinite',
        'radar-ping':     'ring-ping 2.5s ease-out infinite',
        'float-up':       'float-up 6s ease-in-out infinite',
        'scanline':       'fade-in 0.01s',
        'cursor-blink':   'cursor-blink 1s step-end infinite',
        'flicker':        'fade-in 0.01s',
        'h-scan':         'fade-in 0.01s',
        'border-breathe': 'border-breathe 4s ease-in-out infinite',
      },
      keyframes: {
        'fade-in':  { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-right': {
          from: { opacity: '0', transform: 'translateX(-10px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        'data-in': {
          from: { opacity: '0', transform: 'translateX(-6px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '0.6' },
          '50%':      { opacity: '1' },
        },
        'shimmer': {
          '0%':   { backgroundPosition: '-200% center' },
          '100%': { backgroundPosition: '200% center' },
        },
        'count-in': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'alert-flash': {
          '0%, 100%': { backgroundColor: 'transparent' },
          '50%':      { backgroundColor: 'rgb(var(--accent-red) / 0.07)' },
        },
        'ring-ping': {
          '0%':   { transform: 'scale(0.9)', opacity: '0.7' },
          '100%': { transform: 'scale(2.2)', opacity: '0' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0' },
        },
        'border-breathe': {
          '0%, 100%': { borderColor: 'rgb(var(--accent-blue) / 0.15)' },
          '50%':      { borderColor: 'rgb(var(--accent-blue) / 0.35)' },
        },
        'float-up': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%':      { transform: 'translateY(-6px)' },
        },
      },
      boxShadow: {
        'neon-cyan':   '0 0 10px rgb(var(--accent-blue)   / 0.2), 0 0 20px rgb(var(--accent-blue)   / 0.08)',
        'neon-green':  '0 0 10px rgb(var(--accent-green)  / 0.2), 0 0 20px rgb(var(--accent-green)  / 0.08)',
        'neon-red':    '0 0 10px rgb(var(--accent-red)    / 0.2), 0 0 20px rgb(var(--accent-red)    / 0.08)',
        'neon-purple': '0 0 10px rgb(var(--accent-purple) / 0.2), 0 0 20px rgb(var(--accent-purple) / 0.08)',
        'neon-amber':  '0 0 10px rgb(var(--accent-amber)  / 0.2), 0 0 20px rgb(var(--accent-amber)  / 0.08)',
        'card':        '0 1px 3px rgba(0,0,0,0.12), 0 4px 16px rgba(0,0,0,0.08)',
        'card-hover':  '0 4px 24px rgba(0,0,0,0.18), 0 1px 3px rgba(0,0,0,0.1)',
        'modal':       '0 20px 60px rgba(0,0,0,0.4)',
        'glow':        '0 0 16px rgb(var(--accent-blue) / 0.15)',
        'danger':      '0 0 16px rgb(var(--accent-red)  / 0.12)',
        'inner-top':   'inset 0 1px 0 rgba(255,255,255,0.04)',
      },
    },
  },
  plugins: [],
}
