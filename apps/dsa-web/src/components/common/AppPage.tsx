import type React from 'react';
import { cn } from '../../utils/cn';

interface AppPageProps {
  children: React.ReactNode;
  className?: string;
}

export const AppPage: React.FC<AppPageProps> = ({ children, className = '' }) => {
  return (
    <main className={cn('mx-auto min-h-screen w-full max-w-7xl px-4 pb-8 pt-4 md:px-6 lg:px-8', className)}>
      {children}
    </main>
  );
};
