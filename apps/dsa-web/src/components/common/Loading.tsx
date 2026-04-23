import React from 'react';

interface LoadingProps {
  label?: string;
  className?: string;
}

export const Loading: React.FC<LoadingProps> = ({ label = '正在加载', className = '' }) => {
  return (
    <div className={`flex items-center justify-center p-8 ${className}`}>
      <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-4 py-2 text-sm text-secondary-text shadow-soft-card">
        <svg className="h-4 w-4 animate-spin text-cyan" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        {label}
      </div>
    </div>
  );
};
