import type React from 'react';
import { cn } from '../../utils/cn';

interface SettingsSectionCardProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export const SettingsSectionCard: React.FC<SettingsSectionCardProps> = ({
  title,
  description,
  actions,
  children,
  className = '',
}) => {
  return (
    <section className={cn('rounded-lg border settings-border bg-card/90 p-4 shadow-soft-card backdrop-blur-sm md:p-5', className)}>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
          {description ? <p className="text-sm leading-6 text-muted-text">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
};
