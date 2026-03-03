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
  error: 'border-red-500/35 bg-red-500/10 text-red-200',
  success: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200',
  warning: 'border-amber-500/35 bg-amber-500/10 text-amber-200',
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
