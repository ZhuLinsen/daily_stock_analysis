import type React from 'react';
import { cn } from '../../utils/cn';

interface CardProps {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'bordered' | 'gradient';
  hoverable?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

/**
 * Card component with terminal-inspired variants and optional hover styling.
 */
export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  children,
  className = '',
  variant = 'default',
  hoverable = false,
  padding = 'md',
}) => {
  const paddingStyles = {
    none: '',
    sm: 'p-4',
    md: 'p-5',
    lg: 'p-6',
  };

  const variantStyles = {
    default: 'terminal-card',
    bordered: 'terminal-card',
    gradient: 'gradient-border-card',
  };

  const hoverStyles = hoverable ? 'terminal-card-hover cursor-pointer' : '';

  if (variant === 'gradient') {
    return (
      <div className={cn(variantStyles.gradient, className)}>
        <div className={cn('gradient-border-card-inner', paddingStyles[padding])}>
          {(title || subtitle) && (
            <div className="mb-3">
              {subtitle ? <span className="label-uppercase">{subtitle}</span> : null}
              {title ? <h3 className="mt-1 text-lg font-semibold text-foreground">{title}</h3> : null}
            </div>
          )}
          {children}
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn('rounded-2xl', variantStyles[variant], hoverStyles, paddingStyles[padding], className)}
    >
      {(title || subtitle) && (
        <div className="mb-3">
          {subtitle ? <span className="label-uppercase">{subtitle}</span> : null}
          {title ? <h3 className="mt-1 text-lg font-semibold text-foreground">{title}</h3> : null}
        </div>
      )}
      {children}
    </div>
  );
};
