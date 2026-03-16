import React from 'react';
import { cn } from '../../utils/cn';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'gradient' | 'danger';
  size?: 'sm' | 'md' | 'lg' | 'xl';
  isLoading?: boolean;
  /** Custom loading text. */
  loadingText?: string;
  glow?: boolean;
}

const BUTTON_SIZE_STYLES = {
  sm: 'h-9 rounded-lg px-3 text-sm',
  md: 'h-10 rounded-xl px-4 text-sm',
  lg: 'h-11 rounded-xl px-5 text-sm',
  xl: 'h-12 rounded-xl px-6 text-sm',
} as const;

const BUTTON_VARIANT_STYLES = {
  primary: 'border border-cyan/30 bg-primary-gradient text-slate-950 shadow-lg shadow-cyan/20 hover:brightness-105',
  secondary: 'border border-white/10 bg-card text-foreground shadow-soft-card hover:bg-hover',
  outline: 'border border-cyan/25 bg-transparent text-cyan hover:bg-cyan/10',
  ghost: 'border border-transparent bg-transparent text-secondary-text hover:bg-white/5 hover:text-foreground',
  gradient: 'border border-cyan/20 bg-gradient-to-r from-cyan to-purple text-white shadow-lg shadow-cyan/20 hover:brightness-105',
  danger: 'border border-danger/40 bg-danger text-white shadow-lg shadow-danger/20 hover:brightness-105',
} as const;

/**
 * Button component with multiple variants and terminal-inspired styling.
 */
export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  loadingText = '处理中...',
  glow = false,
  className = '',
  disabled,
  ...props
}) => {
  const glowStyles = glow ? 'shadow-glow-cyan hover:shadow-[0_0_30px_rgba(0,212,255,0.38)]' : '';

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 font-medium transition-all duration-200',
        'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15 focus-visible:ring-offset-0',
        'disabled:pointer-events-none disabled:opacity-50 disabled:transform-none',
        BUTTON_SIZE_STYLES[size],
        BUTTON_VARIANT_STYLES[variant],
        glowStyles,
        className,
      )}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span className="flex items-center justify-center gap-2">
          <svg
            className="h-4 w-4 animate-spin text-current"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          {loadingText}
        </span>
      ) : (
        children
      )}
    </button>
  );
};
