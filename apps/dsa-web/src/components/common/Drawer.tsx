import type React from 'react';
import { useEffect, useCallback } from 'react';
import { cn } from '../../utils/cn';

let activeDrawerCount = 0;

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  width?: string;
  zIndex?: number;
}

/**
 * Side drawer component with terminal-inspired styling.
 */
export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  children,
  width = 'max-w-2xl',
  zIndex = 50,
}) => {
  // Close the drawer when Escape is pressed.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      activeDrawerCount++;
      if (activeDrawerCount === 1) {
        document.body.style.overflow = 'hidden';
      }

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        activeDrawerCount--;
        if (activeDrawerCount === 0) {
          document.body.style.overflow = '';
        }
      };
    }
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 overflow-hidden" style={{ zIndex }}>
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm transition-opacity duration-300"
        onClick={onClose}
      />

      <div className={cn('absolute inset-y-0 right-0 flex w-full', width)}>
        <div
          className="relative flex w-full animate-slide-in-right flex-col border-l border-white/10 bg-card shadow-2xl"
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
            {title ? (
              <div>
                <span className="label-uppercase">DETAIL VIEW</span>
                <h2 className="mt-1 text-lg font-semibold text-white">{title}</h2>
              </div>
            ) : <div />}
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-secondary-text transition-colors hover:bg-white/10 hover:text-white"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
};
