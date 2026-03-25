import React, { useState } from 'react';
import { cn } from '../../utils/cn';

interface CollapsibleProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  icon?: React.ReactNode;
  className?: string;
}

/**
 * Collapsible panel with animated expand and collapse behavior.
 */
export const Collapsible: React.FC<CollapsibleProps> = ({
  title,
  children,
  defaultOpen = false,
  icon,
  className = '',
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div
      className={cn(
        'overflow-hidden rounded-2xl border border-subtle bg-card/70 shadow-soft-card transition-all duration-300',
        'hover:border-accent',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-hover"
      >
        <div className="flex items-center gap-3">
          {icon && <span className="text-cyan">{icon}</span>}
          <span className="font-medium text-foreground">{title}</span>
        </div>
        <svg
          className={cn('h-5 w-5 text-secondary-text transition-transform duration-300', isOpen && 'rotate-180')}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <div
        className={cn('overflow-hidden transition-all duration-300 ease-in-out', isOpen ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0')}
      >
        <div className="border-t border-subtle px-4 pb-4 pt-2">
          {children}
        </div>
      </div>
    </div>
  );
};
