import type React from 'react';

interface SettingsAlertProps {
  title: string;
  message: string;
  variant?: 'error' | 'success' | 'warning';
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

const variantStyles: Record<NonNullable<SettingsAlertProps['variant']>, string> = {
  error: 'border-danger/35 bg-danger/10 text-danger',
  success: 'border-success/35 bg-success/10 text-success',
  warning: 'border-warning/35 bg-warning/10 text-warning',
};

export const SettingsAlert: React.FC<SettingsAlertProps> = ({
  title,
  message,
  variant = 'error',
  actionLabel,
  onAction,
  className = '',
}) => {
  return (
    <div className={`rounded-xl border px-4 py-3 ${variantStyles[variant]} ${className}`} role="alert">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs opacity-90">{message}</p>
      {actionLabel && onAction ? (
        <button type="button" className="mt-3 btn-secondary !py-1.5 !px-3 !text-xs" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
};
