import type React from 'react';
import { cn } from '../../utils/cn';

interface DashboardStateBlockProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  compact?: boolean;
  loading?: boolean;
  titleAs?: 'p' | 'h2' | 'h3' | 'h4' | 'span';
}

export const DashboardStateBlock: React.FC<DashboardStateBlockProps> = ({
  title,
  description,
  icon,
  action,
  className = '',
  titleClassName = '',
  descriptionClassName = '',
  compact = false,
  loading = false,
  titleAs = 'p',
}) => {
  const TitleTag = titleAs;

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 py-6' : 'gap-3 py-10',
        className,
      )}
    >
      {loading ? (
        <div className="home-spinner h-6 w-6 animate-spin border-2" aria-hidden="true" />
      ) : icon ? (
        <div className="home-state-icon-muted flex h-11 w-11 items-center justify-center rounded-full bg-subtle">
          {icon}
        </div>
      ) : null}
      <div className="space-y-1">
        <TitleTag className={cn('text-secondary-text', compact ? 'text-xs' : 'text-sm', titleClassName)}>
          {title}
        </TitleTag>
        {description ? (
          <p className={cn('mx-auto max-w-xs text-secondary-text', compact ? 'text-label' : 'text-xs', descriptionClassName)}>
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="flex items-center justify-center">{action}</div> : null}
    </div>
  );
};
