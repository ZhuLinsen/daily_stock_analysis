import React, { useId } from 'react';
import { cn } from '../../utils/cn';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyText?: string;
}

/**
 * Select component with terminal-inspired styling.
 */
export const Select: React.FC<SelectProps> = ({
  id,
  value,
  onChange,
  options,
  label,
  placeholder = '请选择',
  disabled = false,
  className = '',
}) => {
  const selectId = useId();
  const resolvedId = id ?? selectId;

  return (
    <div className={cn('flex flex-col', className)}>
      {label ? <label htmlFor={resolvedId} className="mb-2 text-sm font-medium text-foreground">{label}</label> : null}
      <div className="relative">
        <select
          id={resolvedId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className={cn(
            'h-11 w-full appearance-none rounded-xl border border-subtle bg-card px-4 py-2.5 pr-10 text-sm text-foreground',
            'shadow-soft-card transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-cyan/15 focus:border-cyan/40',
            'hover:border-subtle-hover',
            disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
          )}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value} className="bg-elevated text-foreground">
              {option.label}
            </option>
          ))}
        </select>

        {/* Dropdown arrow */}
        <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
          <svg
            className="h-4 w-4 text-secondary-text"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>
    </div>
  );
};
