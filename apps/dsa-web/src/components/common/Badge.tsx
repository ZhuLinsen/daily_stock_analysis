import React from 'react';
import { cn } from '../../utils/cn';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history';

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  glow?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'border-border/55 bg-elevated/75 text-secondary-text',
  success: 'border-success/20 bg-success/10 text-success',
  warning: 'border-warning/20 bg-warning/10 text-warning',
  danger: 'border-danger/20 bg-danger/10 text-danger',
  info: 'border-cyan/30 bg-cyan/12 text-cyan',
  history: 'border-purple/20 bg-purple/10 text-purple',
};

const glowStyles: Record<BadgeVariant, string> = {
  default: '',
  success: 'shadow-success/20',
  warning: 'shadow-warning/20',
  danger: 'shadow-danger/20',
  info: 'shadow-cyan/20',
  history: 'shadow-purple/20',
};

/**
 * Badge component with multiple variants and optional glow styling.
 */
export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  glow = false,
  className = '',
  style,
  ...rest
}) => {
  const sizeStyles = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <span
      {...rest}
      style={style}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border font-medium backdrop-blur-sm',
        sizeStyles,
        variantStyles[variant],
        glow && `shadow-lg ${glowStyles[variant]}`,
        className,
      )}
    >
      {children}
    </span>
  );
};
