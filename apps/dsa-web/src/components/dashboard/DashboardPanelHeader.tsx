import type React from 'react';
import { cn } from '../../utils/cn';

interface DashboardPanelHeaderProps {
  eyebrow?: React.ReactNode;
  title?: React.ReactNode;
  actions?: React.ReactNode;
  leading?: React.ReactNode;
  className?: string;
  headingClassName?: string;
  titleClassName?: string;
  accentEyebrow?: boolean;
}

export const DashboardPanelHeader: React.FC<DashboardPanelHeaderProps> = ({
  eyebrow,
  title,
  actions,
  leading,
  className = '',
  headingClassName = '',
  titleClassName = '',
  accentEyebrow = false,
}) => {
  if (!eyebrow && !title && !actions) {
    return null;
  }

  return (
    <div className={cn('mb-4 flex items-center justify-between gap-3', className)}>
      {(eyebrow || title) ? (
        <div className={cn('flex items-baseline gap-2', headingClassName)}>
          {leading ? <span className="shrink-0">{leading}</span> : null}
          {eyebrow ? (
            <span className={cn('label-uppercase', accentEyebrow && 'home-title-accent')}>
              {eyebrow}
            </span>
          ) : null}
          {title ? <h3 className={cn('text-base font-semibold text-foreground', titleClassName)}>{title}</h3> : null}
        </div>
      ) : null}
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
};
