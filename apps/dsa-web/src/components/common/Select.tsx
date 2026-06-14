import React, { useId } from 'react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
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
  placeholder,
  disabled = false,
  className = '',
}) => {
  const { t } = useUiLanguage();
  const selectId = useId();
  const resolvedId = id ?? selectId;
  const hasEmptyOption = options.some((option) => option.value === '');
  const resolvedPlaceholder = placeholder ?? t('common.selectPlaceholder');

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
            'input-surface input-focus-glow h-11 w-full appearance-none rounded-xl border bg-transparent px-4 py-2.5 pr-10 text-sm text-foreground',
            'transition-all duration-200 focus:outline-none',
            disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
          )}
        >
          {resolvedPlaceholder && !hasEmptyOption && (
            <option value="" disabled>
              {resolvedPlaceholder}
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
