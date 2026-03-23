import type React from 'react';
import type { ParsedApiError } from '../../api/error';

interface ApiErrorAlertProps {
  error: ParsedApiError;
  className?: string;
  actionLabel?: string;
  onAction?: () => void;
  dismissLabel?: string;
  onDismiss?: () => void;
}

export const ApiErrorAlert: React.FC<ApiErrorAlertProps> = ({
  error,
  className = '',
  actionLabel,
  onAction,
  dismissLabel = '关闭',
  onDismiss,
}) => {
  const showDetails = error.rawMessage.trim() && error.rawMessage.trim() !== error.message.trim();

  return (
    <div
      className={`rounded-xl border border-red-500/35 bg-red-500/10 px-4 py-3 text-red-200 ${className}`}
      role="alert"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{error.title}</p>
          <p className="mt-1 text-xs opacity-90">{error.message}</p>
        </div>
        {onDismiss ? (
          <button
            type="button"
            className="shrink-0 rounded-md border border-danger/25 bg-danger/5 px-2 py-1 text-[11px] text-danger transition hover:bg-danger/12"
            onClick={onDismiss}
          >
            {dismissLabel}
          </button>
        ) : null}
      </div>
      {showDetails ? (
        <details className="mt-3 rounded-lg border border-subtle bg-surface-2 px-3 py-2">
          <summary className="cursor-pointer text-xs text-danger opacity-90">查看详情</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] leading-5 text-danger opacity-85">
            {error.rawMessage}
          </pre>
        </details>
      ) : null}
      {actionLabel && onAction ? (
        <button type="button" className="mt-3 btn-secondary !px-3 !py-1.5 !text-xs" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
};
