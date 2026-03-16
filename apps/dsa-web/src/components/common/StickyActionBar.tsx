import type React from 'react';
import { cn } from '../../utils/cn';

interface StickyActionBarProps {
  children: React.ReactNode;
  className?: string;
}

export const StickyActionBar: React.FC<StickyActionBarProps> = ({ children, className = '' }) => {
  return (
    <div className={cn('sticky bottom-4 z-20 rounded-2xl border border-white/8 bg-card/85 p-3 shadow-soft-card backdrop-blur-md', className)}>
      <div className="flex flex-wrap items-center justify-end gap-2">{children}</div>
    </div>
  );
};
