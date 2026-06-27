import type React from 'react';
import { AlertTriangle, DatabaseZap } from 'lucide-react';
import { InlineAlert } from '../common';

type WorkbenchDataNoticeProps = {
  stale?: boolean;
  error?: string | null;
  source?: string | null;
  className?: string;
};

export const WorkbenchDataNotice: React.FC<WorkbenchDataNoticeProps> = ({ stale, error, source, className }) => {
  if (!stale && !error) {
    return source ? (
      <div className={className}>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-card/70 px-2.5 py-1 text-xs text-secondary-text">
          <DatabaseZap className="h-3.5 w-3.5" />
          数据源：{source}
        </span>
      </div>
    ) : null;
  }

  return (
    <InlineAlert
      className={className}
      variant={error ? 'warning' : 'info'}
      title={error ? '数据接口异常，已降级展示' : '数据可能延迟'}
      message={(
        <span className="inline-flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {error || '当前行情可能来自缓存或最近一次成功数据。'}
            {source ? ` 来源：${source}` : ''}
          </span>
        </span>
      )}
    />
  );
};
