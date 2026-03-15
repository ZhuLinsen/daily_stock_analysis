/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 主色调 - 青色
        'cyan': {
          DEFAULT: '#00d4ff',
          dim: '#00a8cc',
          glow: 'rgba(0, 212, 255, 0.4)',
        },
        // 辅助色 - 紫色
        'purple': {
          DEFAULT: '#6f61f1',
          dim: '#533483',
          glow: 'rgba(168, 85, 247, 0.3)',
        },
        // 状态色
        'success': '#00ff88',
        'warning': '#ffaa00',
        'danger': '#ff4466',
        // 背景色
        'base': '#08080c',
        'card': '#0d0d14',
        'elevated': '#12121a',
        'hover': '#1a1a24',
        // 文字色
        'primary': '#ffffff',
        'secondary': '#a0a0b0',
        'muted': '#606070',
        // 边框色
        'border': {
          dim: 'rgba(255, 255, 255, 0.06)',
          DEFAULT: 'rgba(255, 255, 255, 0.1)',
          accent: 'rgba(0, 212, 255, 0.3)',
          purple: 'rgba(168, 85, 247, 0.3)',
        },
      },
      backgroundImage: {
        'gradient-purple-cyan': 'linear-gradient(135deg, rgba(168, 85, 247, 0.2) 0%, rgba(0, 212, 255, 0.1) 100%)',
        'gradient-card-border': 'linear-gradient(180deg, rgba(168, 85, 247, 0.4) 0%, rgba(168, 85, 247, 0.1) 50%, rgba(0, 212, 255, 0.2) 100%)',
        'gradient-cyan': 'linear-gradient(135deg, #00d4ff 0%, #00a8cc 100%)',
      },
      boxShadow: {
        'glow-cyan': '0 0 20px rgba(0, 212, 255, 0.4)',
        'glow-purple': '0 0 20px rgba(168, 85, 247, 0.3)',
        'glow-success': '0 0 20px rgba(0, 255, 136, 0.3)',
        'glow-danger': '0 0 20px rgba(255, 68, 102, 0.3)',
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      fontSize: {
        'xxs': '10px',
        'label': '11px',
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'spin-slow': 'spin 2s linear infinite',
      },
      keyframes: {
        fadeIn: {
          'from': { opacity: '0' },
          'to': { opacity: '1' },
        },
        slideUp: {
          'from': { opacity: '0', transform: 'translateY(10px)' },
          'to': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          'from': { opacity: '0', transform: 'translateX(100%)' },
          'to': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(0, 212, 255, 0.4)' },
          '50%': { boxShadow: '0 0 40px rgba(0, 212, 255, 0.6)' },
        },
      },
    },
  },
  plugins: [],
}
