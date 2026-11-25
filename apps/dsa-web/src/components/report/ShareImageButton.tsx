import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Loader2, Share2, TriangleAlert } from 'lucide-react';
import { historyApi } from '../../api/history';
import type { ReportLanguage } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Tooltip } from '../common/Tooltip';

type DesktopWindow = Window & {
  dsaDesktop?: {
    renderShareImage?: (recordId: number) => Promise<ArrayBuffer>;
  };
};

type ShareState = 'idle' | 'loading' | 'ready' | 'success' | 'error';

interface ShareImageButtonProps {
  recordId?: number;
  reportTitle: string;
  reportLanguage?: ReportLanguage;
  className?: string;
}

const safeFilenamePart = (value: string): string => {
  const normalized = value.trim().replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '-');
  return normalized.slice(0, 72) || 'report';
};

const downloadBlob = (blob: Blob, filename: string): void => {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
};

export const ShareImageButton: React.FC<ShareImageButtonProps> = ({
  recordId,
  reportTitle,
  reportLanguage = 'zh',
  className = '',
}) => {
  const desktopRuntime = typeof window !== 'undefined' ? (window as DesktopWindow).dsaDesktop : undefined;
  const renderDesktopShareImage = desktopRuntime?.renderShareImage;
  const activeRecordId = desktopRuntime && !renderDesktopShareImage ? undefined : recordId;
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const [prevRecordId, setPrevRecordId] = useState<number | undefined>(activeRecordId);
  const [state, setState] = useState<ShareState>('idle');

  if (prevRecordId !== activeRecordId) {
    setPrevRecordId(activeRecordId);
    setState('idle');
  }

  const resetTimerRef = useRef<number | null>(null);
  const loadTokenRef = useRef(0);
  const inFlightRef = useRef<{ recordId: number; token: number } | null>(null);
  const cachedImageRef = useRef<{ recordId: number; blob: Blob } | null>(null);
  const clearResetTimer = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const scheduleReset = useCallback((actionToken: number) => {
    clearResetTimer();
    resetTimerRef.current = window.setTimeout(() => {
      resetTimerRef.current = null;
      if (loadTokenRef.current === actionToken) {
        setState('idle');
      }
    }, 2200);
  }, [clearResetTimer]);

  useEffect(() => {
    clearResetTimer();
    loadTokenRef.current += 1;
    inFlightRef.current = null;
    cachedImageRef.current = null;

    return () => {
      clearResetTimer();
      loadTokenRef.current += 1;
      inFlightRef.current = null;
    };
  }, [activeRecordId, clearResetTimer]);

  const handleShare = useCallback(async () => {
    if (
      activeRecordId === undefined
      || state === 'loading'
      || inFlightRef.current?.recordId === activeRecordId
    ) {
      return;
    }
    clearResetTimer();

    const actionToken = loadTokenRef.current + 1;
    loadTokenRef.current = actionToken;
    inFlightRef.current = { recordId: activeRecordId, token: actionToken };

    try {
      let blob = cachedImageRef.current?.recordId === activeRecordId
        ? cachedImageRef.current.blob
        : null;
      let generatedNow = false;

      if (!blob) {
        setState('loading');
        try {
          if (renderDesktopShareImage) {
            const pngBytes = await renderDesktopShareImage(activeRecordId);
            blob = new Blob([pngBytes], { type: 'image/png' });
          } else {
            blob = await historyApi.getShareImage(activeRecordId);
          }
        } catch (error) {
          if (loadTokenRef.current !== actionToken) return;
          console.error('Generate share image failed:', error);
          setState('error');
          return;
        }
        if (loadTokenRef.current !== actionToken) return;
        cachedImageRef.current = { recordId: activeRecordId, blob };
        generatedNow = true;
      }

      const filename = `${safeFilenamePart(reportTitle)}-${activeRecordId}.png`;
      const file = new File([blob], filename, { type: 'image/png' });
      const canShareFile = typeof navigator.share === 'function'
        && typeof navigator.canShare === 'function'
        && navigator.canShare({ files: [file] });

      // A file cannot be shared before it exists, while navigator.share() must run
      // inside a transient user-activation event. Prepare on the first click and
      // let the next click invoke native sharing synchronously.
      if (generatedNow && canShareFile) {
        setState('ready');
        return;
      }

      setState('loading');
      try {
        if (canShareFile) {
          try {
            await navigator.share({
              files: [file],
              title: reportTitle,
            });
          } catch (error) {
            if (loadTokenRef.current !== actionToken) return;
            if (error instanceof DOMException && error.name === 'AbortError') {
              setState('ready');
              return;
            }
            console.warn('Native file sharing failed; falling back to download:', error);
            downloadBlob(blob, filename);
          }
          if (loadTokenRef.current !== actionToken) return;
        } else {
          downloadBlob(blob, filename);
        }

        setState('success');
        scheduleReset(actionToken);
      } catch (error) {
        if (loadTokenRef.current !== actionToken) return;
        console.error('Generate share image failed:', error);
        setState('error');
      }
    } finally {
      if (inFlightRef.current?.token === actionToken) {
        inFlightRef.current = null;
      }
    }
  }, [activeRecordId, clearResetTimer, renderDesktopShareImage, reportTitle, scheduleReset, state]);

  if (activeRecordId === undefined) return null;

  const tooltipText = state === 'loading'
    ? text.generatingShareImage
    : state === 'ready'
      ? text.shareImageReadyToShare
    : state === 'success'
      ? text.shareImageReady
      : state === 'error'
        ? text.shareImageFailed
        : text.generateShareImage;

  return (
    <Tooltip content={tooltipText}>
      <span className="inline-flex shrink-0">
        <button
          type="button"
          onClick={() => void handleShare()}
          disabled={state === 'loading'}
          className={`home-surface-button flex h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 text-sm font-medium text-secondary-text hover:text-foreground disabled:opacity-50 ${className}`}
          aria-label={tooltipText}
        >
          {state === 'loading' ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : null}
          {state === 'success' ? <Check className="h-5 w-5 text-success" aria-hidden="true" /> : null}
          {state === 'error' ? <TriangleAlert className="h-5 w-5 text-danger" aria-hidden="true" /> : null}
          {state === 'idle' || state === 'ready' ? <Share2 className="h-5 w-5" aria-hidden="true" /> : null}
          <span>{tooltipText}</span>
        </button>
      </span>
    </Tooltip>
  );
};
