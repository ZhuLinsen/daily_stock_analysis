import type React from 'react';
import { cn } from '../../utils/cn';

type InlineAlertVariant = 'info' | 'success' | 'warning' | 'danger';

interface InlineAlertProps {
  title?: string;
  message: React.ReactNode;
  variant?: InlineAlertVariant;
  action?: React.ReactNode;
  className?: string;
}

const variantStyles: Record<InlineAlertVariant, string> = {
  info: 'border-cyan/20 bg-cyan/10 text-cyan',
  success: 'border-success/20 bg-success/10 text-success',
  warning: 'border-warning/20 bg-warning/10 text-warning',
  danger: 'border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] text-[hsl(var(--color-danger-alert-text))]',
};

export const InlineAlert: React.FC<InlineAlertProps> = ({
  title,
  message,
  variant = 'info',
  action,
  className = '',
}) => {
  return (
    <div className={cn('rounded-2xl border px-4 py-3 shadow-soft-card', variantStyles[variant], className)}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          {title ? <p className="text-sm font-semibold">{title}</p> : null}
          <div className={cn('text-sm', title ? 'mt-1 opacity-90' : 'opacity-90')}>{message}</div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
};
