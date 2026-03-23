import type React from 'react';
import { cn } from '../../utils/cn';

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon,
  action,
  className = '',
}) => {
  return (
    <div className={cn('rounded-2xl border border-dashed border-border/60 bg-card/50 px-6 py-10 text-center shadow-soft-card', className)}>
      {icon ? <div className="mb-4 flex justify-center text-cyan">{icon}</div> : null}
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description ? <p className="mx-auto mt-2 max-w-md text-sm text-secondary-text">{description}</p> : null}
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
};
