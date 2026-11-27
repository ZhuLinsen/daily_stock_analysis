import type React from 'react';
import { cloneElement, isValidElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../utils/cn';

const HOVER_CLOSE_DELAY_MS = 150;

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: 'top' | 'bottom';
  focusable?: boolean;
  className?: string;
  contentClassName?: string;
}

type TooltipStyle = {
  top: number;
  left: number;
};

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  side = 'top',
  focusable = false,
  className = '',
  contentClassName = '',
}) => {
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const [resolvedSide, setResolvedSide] = useState<'top' | 'bottom'>(side);
  const [style, setStyle] = useState<TooltipStyle>({ top: 0, left: 0 });

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const openTooltip = useCallback(() => {
    clearCloseTimer();
    setOpen(true);
  }, [clearCloseTimer]);

  const closeTooltipNow = useCallback(() => {
    clearCloseTimer();
    setOpen(false);
  }, [clearCloseTimer]);

  const scheduleClose = useCallback(() => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      setOpen(false);
    }, HOVER_CLOSE_DELAY_MS);
  }, [clearCloseTimer]);

  useEffect(() => () => {
    clearCloseTimer();
  }, [clearCloseTimer]);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const tooltip = tooltipRef.current;
    if (!trigger || !tooltip) {
      return;
    }

    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const gap = 10;
    const margin = 8;

    let nextSide = side;
    let top =
      side === 'top'
        ? triggerRect.top - tooltipRect.height - gap
        : triggerRect.bottom + gap;

    if (side === 'top' && top < margin) {
      nextSide = 'bottom';
      top = triggerRect.bottom + gap;
    } else if (side === 'bottom' && top + tooltipRect.height > viewportHeight - margin) {
      nextSide = 'top';
      top = triggerRect.top - tooltipRect.height - gap;
    }

    let left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    left = Math.max(margin, Math.min(left, viewportWidth - tooltipRect.width - margin));
    top = Math.max(margin, Math.min(top, viewportHeight - tooltipRect.height - margin));

    setResolvedSide(nextSide);
    setStyle({ top, left });
  }, [side]);

  useLayoutEffect(() => {
    if (!open) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      updatePosition();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [open, content, updatePosition]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleViewportChange = () => updatePosition();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeTooltipNow();
      }
    };
    window.addEventListener('resize', handleViewportChange);
    window.addEventListener('scroll', handleViewportChange, true);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('resize', handleViewportChange);
      window.removeEventListener('scroll', handleViewportChange, true);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, updatePosition, closeTooltipNow]);

  if (!content) {
    return <>{children}</>;
  }

  const canAttachDescribedByToChild = !focusable && isValidElement<{ 'aria-describedby'?: string }>(children);
  const triggerContent = canAttachDescribedByToChild
    ? cloneElement(children, {
        'aria-describedby': open
          ? [children.props['aria-describedby'], tooltipId].filter(Boolean).join(' ')
          : children.props['aria-describedby'],
      })
    : children;

  return (
    <>
      <span
        ref={triggerRef}
        className={cn('inline-flex', className)}
        onMouseEnter={openTooltip}
        onMouseLeave={scheduleClose}
        onFocus={openTooltip}
        onBlur={(event) => {
          const nextFocused = event.relatedTarget as Node | null;
          if (
            nextFocused &&
            (triggerRef.current?.contains(nextFocused) || tooltipRef.current?.contains(nextFocused))
          ) {
            return;
          }
          closeTooltipNow();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            closeTooltipNow();
          }
        }}
        tabIndex={focusable ? 0 : undefined}
        aria-describedby={!canAttachDescribedByToChild && open ? tooltipId : undefined}
      >
        {triggerContent}
      </span>

      {typeof document !== 'undefined' && open
        ? createPortal(
            <span
              ref={tooltipRef}
              id={tooltipId}
              role="tooltip"
              onMouseEnter={openTooltip}
              onMouseLeave={scheduleClose}
              style={{
                position: 'fixed',
                top: style.top,
                left: style.left,
              }}
              className={cn(
                'pointer-events-auto z-[120] w-max max-w-[min(18rem,calc(100vw-1rem))] whitespace-normal break-words rounded-xl border border-border/70 bg-elevated/95 px-3 py-1.5 text-xs leading-5 text-foreground shadow-[0_16px_40px_rgba(3,8,20,0.18)] backdrop-blur-xl',
                resolvedSide === 'top' ? 'origin-bottom' : 'origin-top',
                contentClassName,
              )}
            >
              {content}
            </span>,
            document.body,
          )
        : null}
    </>
  );
};
