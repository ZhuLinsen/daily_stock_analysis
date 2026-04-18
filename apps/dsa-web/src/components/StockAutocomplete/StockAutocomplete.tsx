/**
 * StockAutocomplete Component
 *
 * Stock code/name autocomplete input box
 * Supports keyboard navigation, IME input method, graceful degradation
 */

import { Component, useRef, useEffect, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useStockIndex } from '../../hooks/useStockIndex';
import { useAutocomplete } from '../../hooks/useAutocomplete';
import { SuggestionsList } from './SuggestionsList';
import { cn } from '../../utils/cn';

const AUTOCOMPLETE_INPUT_CLASS =
  'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';

export interface StockAutocompleteProps {
  /** Input value */
  value: string;
  /** Value change callback */
  onChange: (value: string) => void;
  /** Submit callback (code, name, source) */
  onSubmit: (code: string, name?: string, source?: 'manual' | 'autocomplete') => void;
  /** Whether disabled */
  disabled?: boolean;
  /** Placeholder text */
  placeholder?: string;
  /** Additional CSS class name */
  className?: string;
}

function FallbackInput({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = '输入股票代码或名称',
  className,
}: StockAutocompleteProps) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !disabled && value) {
          onSubmit(value);
        }
      }}
      placeholder={placeholder}
      disabled={disabled}
      className={cn(AUTOCOMPLETE_INPUT_CLASS, className)}
      data-autocomplete-mode="fallback"
    />
  );
}

interface StockAutocompleteBoundaryProps extends StockAutocompleteProps {
  children: ReactNode;
}

interface StockAutocompleteBoundaryState {
  hasError: boolean;
}

class StockAutocompleteBoundary extends Component<
  StockAutocompleteBoundaryProps,
  StockAutocompleteBoundaryState
> {
  override state: StockAutocompleteBoundaryState = { hasError: false };

  static getDerivedStateFromError(): StockAutocompleteBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Autocomplete runtime error. Falling back to plain input.', error, errorInfo);
  }

  override render() {
    if (this.state.hasError) {
      const { children, ...fallbackProps } = this.props;
      void children;
      return <FallbackInput {...fallbackProps} />;
    }

    return this.props.children;
  }
}

function StockAutocompleteInner({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = '输入股票代码或名称',
  className,
}: StockAutocompleteProps) {
  const { index, loading, fallback } = useStockIndex();
  const {
    // query,
    setQuery,
    suggestions,
    isOpen,
    highlightedIndex,
    setHighlightedIndex,
    highlightPrevious,
    highlightNext,
    close,
    // reset,
    isComposing,
    setIsComposing,
    runtimeFallback,
    error: autocompleteError,
  } = useAutocomplete(index);

  const inputRef = useRef<HTMLInputElement>(null);
  const prevValueRef = useRef(value);
  const [dropdownStyle, setDropdownStyle] = useState<{ top: number; left: number; width: string } | null>(null);

  const updateDropdownPosition = () => {
    if (!inputRef.current) {
      setDropdownStyle(null);
      return;
    }

    const rect = inputRef.current.getBoundingClientRect();
    setDropdownStyle({
      top: rect.bottom,
      left: rect.left,
      width: `${rect.width}px`,
    });
  };

  const closeSuggestions = () => {
    close();
    setDropdownStyle(null);
  };

  // Sync external value with internal query (only when value truly changes)
  useEffect(() => {
    if (prevValueRef.current !== value) {
      setQuery(value);
      prevValueRef.current = value;
    }
  }, [value, setQuery]);

  // Calculate suggestion box position (using fixed positioning)
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const frameId = window.requestAnimationFrame(updateDropdownPosition);
    window.addEventListener('resize', updateDropdownPosition);
    window.addEventListener('scroll', updateDropdownPosition, true);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener('resize', updateDropdownPosition);
      window.removeEventListener('scroll', updateDropdownPosition, true);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!autocompleteError) {
      return;
    }

    console.error('Autocomplete runtime fallback activated.', autocompleteError);
  }, [autocompleteError]);

  // Keyboard event handling
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // Skip if composing (IME)
    if (isComposing) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        highlightNext();
        break;
      case 'ArrowUp':
        e.preventDefault();
        highlightPrevious();
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedIndex >= 0 && suggestions[highlightedIndex]) {
          // Select highlighted item
          const selected = suggestions[highlightedIndex];
          onChange(selected.displayCode);
          closeSuggestions();
          onSubmit(selected.canonicalCode, selected.nameZh, 'autocomplete');
        } else {
          // Submit directly
          onSubmit(value);
        }
        break;
      case 'Escape':
        e.preventDefault();
        closeSuggestions();
        break;
    }
  };

  // IME handling
  const handleCompositionStart = () => {
    setIsComposing(true);
  };

  const handleCompositionEnd = () => {
    setIsComposing(false);
  };

  // Delay closing on blur (avoid immediate close when clicking suggestion items)
  const handleBlur = () => {
    setTimeout(() => closeSuggestions(), 200);
  };

  // Fallback mode: use normal input
  if (fallback || loading || runtimeFallback) {
    return (
      <FallbackInput
        value={value}
        onChange={onChange}
        onSubmit={onSubmit}
        disabled={disabled}
        placeholder={placeholder}
        className={className}
      />
    );
  }

  return (
    <div className="relative stock-autocomplete">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        onFocus={() => {
          if (isOpen) {
            updateDropdownPosition();
          }
        }}
        onBlur={handleBlur}
        placeholder={placeholder}
        disabled={disabled}
        className={cn(
          AUTOCOMPLETE_INPUT_CLASS,
          isOpen && "rounded-b-none",
          className
        )}
        aria-autocomplete="none"
        role="combobox"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-controls="suggestions-list"
      />

      {/* Loading indicator */}
      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
        </div>
      )}

      {/* Suggestion dropdown list */}
      {isOpen && dropdownStyle && createPortal(
        <SuggestionsList
          suggestions={suggestions}
          highlightedIndex={highlightedIndex}
          onSelect={(s) => {
            // Update external value (shown in input box)
            onChange(s.displayCode);
            // Close dropdown list
            closeSuggestions();
            // Submit analysis
            onSubmit(s.canonicalCode, s.nameZh, 'autocomplete');
          }}
          onMouseEnter={(index) => setHighlightedIndex(index)}
          style={{ position: 'fixed', ...dropdownStyle }}
        />,
        document.body
      )}
    </div>
  );
}

export function StockAutocomplete(props: StockAutocompleteProps) {
  return (
    <StockAutocompleteBoundary {...props}>
      <StockAutocompleteInner {...props} />
    </StockAutocompleteBoundary>
  );
}

export default StockAutocomplete;
