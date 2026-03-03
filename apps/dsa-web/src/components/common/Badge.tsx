import React from 'react';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  glow?: boolean;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-slate-700/50 text-gray-300 border-slate-600/50',
  success: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  warning: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  danger: 'bg-red-500/20 text-red-400 border-red-500/30',
  info: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  history: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
};

const glowStyles: Record<BadgeVariant, string> = {
  default: '',
  success: 'shadow-emerald-500/20',
  warning: 'shadow-amber-500/20',
  danger: 'shadow-red-500/20',
  info: 'shadow-cyan-500/20',
  history: 'shadow-purple-500/20',
};

/**
 * 标签徽章组件
 * 支持多种变体和发光效果
 */
export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  glow = false,
  className = '',
}) => {
  const sizeStyles = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <span
      className={`
        inline-flex items-center gap-1 rounded-full font-medium
        border backdrop-blur-sm
        ${sizeStyles}
        ${variantStyles[variant]}
        ${glow ? `shadow-lg ${glowStyles[variant]}` : ''}
        ${className}
      `}
    >
      {children}
    </span>
  );
};
