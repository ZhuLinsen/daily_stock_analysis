import type React from 'react';

interface CardProps {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'bordered' | 'gradient';
  hoverable?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

/**
 * 终端风格卡片组件
 * 支持渐变边框、悬浮效果
 */
export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  children,
  className = '',
  variant = 'default',
  hoverable = false,
  padding = 'md',
}) => {
  const paddingStyles = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-5',
  };

  const baseStyles = 'rounded-2xl';

  const variantStyles = {
    default: 'terminal-card',
    bordered: 'terminal-card terminal-card-hover',
    gradient: 'gradient-border-card',
  };

  const hoverStyles = hoverable
    ? 'terminal-card-hover cursor-pointer'
    : '';

  if (variant === 'gradient') {
    return (
      <div className={`${variantStyles.gradient} ${className}`}>
        <div className={`gradient-border-card-inner ${paddingStyles[padding]}`}>
          {(title || subtitle) && (
            <div className="mb-3">
              {subtitle && (
                <span className="label-uppercase">{subtitle}</span>
              )}
              {title && (
                <h3 className="text-lg font-semibold text-white mt-1">
                  {title}
                </h3>
              )}
            </div>
          )}
          {children}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`
        ${baseStyles}
        ${variantStyles[variant]}
        ${hoverStyles}
        ${paddingStyles[padding]}
        ${className}
      `}
    >
      {(title || subtitle) && (
        <div className="mb-3">
          {subtitle && (
            <span className="label-uppercase">{subtitle}</span>
          )}
          {title && (
            <h3 className="text-lg font-semibold text-white mt-1">
              {title}
            </h3>
          )}
        </div>
      )}
      {children}
    </div>
  );
};
