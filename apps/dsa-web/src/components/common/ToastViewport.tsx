import type React from 'react';
import { cn } from '../../utils/cn';

interface ToastViewportProps {
  children: React.ReactNode;
  className?: string;
}

export const ToastViewport: React.FC<ToastViewportProps> = ({ children, className = '' }) => {
  return (
    <div className={cn('pointer-events-none fixed bottom-5 right-5 z-50 flex w-[360px] max-w-[calc(100vw-24px)] flex-col gap-3', className)}>
      {children}
    </div>
  );
};
