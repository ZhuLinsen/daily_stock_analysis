import type React from 'react';
import { cn } from '../../utils/cn';

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  eyebrow,
  title,
  description,
  actions,
  className = '',
}) => {
  return (
    <header className={cn('glass-panel-lg px-5 py-4', className)}>
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          {eyebrow ? <span className="label-uppercase">{eyebrow}</span> : null}
          <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-foreground md:text-2xl">{title}</h1>
          {description ? <p className="mt-1.5 max-w-2xl text-[13px] leading-5 text-secondary-text md:text-sm">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
};
