/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: '1.5rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        cyan: {
          DEFAULT: 'hsl(var(--primary))',
          dim: 'hsl(var(--primary) / 0.8)',
          glow: 'hsl(var(--primary) / 0.4)',
        },
        purple: {
          DEFAULT: 'hsl(var(--accent))',
          dim: 'hsl(var(--accent) / 0.8)',
          glow: 'hsl(var(--accent) / 0.3)',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          dim: 'hsl(var(--success) / 0.8)',
          glow: 'hsl(var(--success) / 0.3)',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          dim: 'hsl(var(--warning) / 0.8)',
          glow: 'hsl(var(--warning) / 0.3)',
        },
        danger: {
          DEFAULT: 'hsl(var(--destructive))',
          dim: 'hsl(var(--destructive) / 0.8)',
          glow: 'hsl(var(--destructive) / 0.3)',
        },
        base: 'hsl(var(--background))',
        elevated: 'hsl(var(--elevated))',
        hover: 'hsl(var(--hover))',
        'secondary-bg': 'hsl(var(--secondary))',
        'muted-bg': 'hsl(var(--muted))',
        'secondary-text': 'hsl(var(--secondary-text))',
        'muted-text': 'hsl(var(--muted-text))',
        // 设计令牌 (Design Tokens)
        dim: 'hsl(var(--border-dim-raw) / 0.06)',
        subtle: 'hsl(var(--bg-subtle-raw) / 0.05)',
        'subtle-hover': 'hsl(var(--bg-subtle-raw) / 0.1)',
        'subtle-soft': 'hsl(var(--bg-subtle-raw) / 0.03)',
        'subtle-active': 'hsl(var(--bg-subtle-raw) / 0.15)',
        'surface-1': 'var(--surface-1)',
        'surface-2': 'var(--surface-2)',
        'surface-3': 'var(--surface-3)',
        'overlay-hover': 'var(--overlay-hover)',
        'overlay-selected': 'var(--overlay-selected)',
      },
      borderColor: {
        dim: 'hsl(var(--border-dim-raw) / 0.06)',
        subtle: 'hsl(var(--border-subtle-raw) / 0.08)',
        'subtle-hover': 'hsl(var(--border-subtle-raw) / 0.15)',
      },
      backgroundColor: {
        subtle: 'hsl(var(--bg-subtle-raw) / 0.05)',
        'subtle-hover': 'hsl(var(--bg-subtle-raw) / 0.1)',
        'subtle-soft': 'hsl(var(--bg-subtle-raw) / 0.03)',
        'subtle-active': 'hsl(var(--bg-subtle-raw) / 0.15)',
      },
      backgroundImage: {
        'gradient-purple-cyan': 'linear-gradient(135deg, hsla(var(--accent), 0.2) 0%, hsla(var(--primary), 0.1) 100%)',
        'gradient-card-border': 'linear-gradient(180deg, hsla(var(--accent), 0.4) 0%, hsla(var(--accent), 0.1) 50%, hsla(var(--primary), 0.2) 100%)',
        'gradient-cyan': 'linear-gradient(135deg, hsl(var(--primary)) 0%, hsl(var(--primary) / 0.8) 100%)',
        'primary-gradient': 'linear-gradient(135deg, #00d4ff 0%, #00a8cc 100%)',
      },
      boxShadow: {
        'soft-card': '0 18px 48px rgba(3, 8, 20, 0.18)',
        'glow-cyan': '0 0 20px rgba(0, 212, 255, 0.4)',
        'glow-purple': '0 0 20px rgba(168, 85, 247, 0.3)',
        'glow-success': '0 0 20px rgba(0, 255, 136, 0.3)',
        'glow-danger': '0 0 20px rgba(255, 68, 102, 0.3)',
        'cyan/20': '0 12px 28px rgba(0, 212, 255, 0.2)',
        'cyan/22': '0 18px 34px rgba(0, 212, 255, 0.22)',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
        xl: '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      fontSize: {
        xxs: '10px',
        label: '11px',
      },
      spacing: {
        18: '4.5rem',
        22: '5.5rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'spin-slow': 'spin 2s linear infinite',
        'float-in': 'floatIn 0.45s ease-out',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          from: { opacity: '0', transform: 'translateX(100%)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        floatIn: {
          from: { opacity: '0', transform: 'translateY(16px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(0, 212, 255, 0.4)' },
          '50%': { boxShadow: '0 0 40px rgba(0, 212, 255, 0.6)' },
        },
      },
    },
  },
  plugins: [],
};
