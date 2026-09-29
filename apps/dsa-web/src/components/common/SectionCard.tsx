import type React from 'react';
import { Card } from './Card';

interface SectionCardProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export const SectionCard: React.FC<SectionCardProps> = ({
  title,
  subtitle,
  actions,
  children,
  className = '',
}) => {
  return (
    <Card className={className} padding="md" variant="bordered">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          {subtitle ? <span className="label-uppercase">{subtitle}</span> : null}
          <h2 className="mt-1 text-lg font-semibold text-foreground">{title}</h2>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </Card>
  );
};
