import type React from 'react';
import { useId } from 'react';
import { cn } from '../../utils/cn';

interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string;
  containerClassName?: string;
}

/**
 * 定制化的大尺寸勾选框组件
 */
export const Checkbox: React.FC<CheckboxProps> = ({
  label,
  id,
  className = '',
  containerClassName = '',
  ...props
}) => {
  const generatedId = useId();
  const checkboxId = id ?? generatedId;

  return (
    <div className={cn('flex items-center gap-3', containerClassName)}>
      <input
        id={checkboxId}
        type="checkbox"
        className={cn(
          'h-4 w-4 cursor-pointer rounded border border-border/70 bg-base text-cyan transition-all',
          'focus:ring-2 focus:ring-cyan/20 focus:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className
        )}
        {...props}
      />
      {label && (
        <label
          htmlFor={checkboxId}
          className="cursor-pointer select-none text-sm font-medium text-foreground"
        >
          {label}
        </label>
      )}
    </div>
  );
};
