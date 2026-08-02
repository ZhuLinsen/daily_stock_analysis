import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Loader2, Share2, TriangleAlert } from 'lucide-react';
import { historyApi } from '../../api/history';
import type { ReportLanguage } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Tooltip } from '../common/Tooltip';

type DesktopWindow = Window & {
  dsaDesktop?: unknown;
};

type ShareState = 'idle' | 'loading' | 'success' | 'error';

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
  const isDesktopRuntime = typeof window !== 'undefined' && Boolean((window as DesktopWindow).dsaDesktop);
  const activeRecordId = isDesktopRuntime ? undefined : recordId;
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const [stateSnapshot, setStateSnapshot] = useState<{
    recordId?: number;
    state: ShareState;
  }>(() => ({
    recordId: activeRecordId,
    state: activeRecordId === undefined ? 'idle' : 'loading',
  }));
  const resetTimerRef = useRef<number | null>(null);
  const loadTokenRef = useRef(0);
  const cachedImageRef = useRef<{ recordId: number; blob: Blob } | null>(null);
  const state = stateSnapshot.recordId === activeRecordId ? stateSnapshot.state : 'loading';
  const setState = useCallback((nextState: ShareState) => {
    setStateSnapshot({ recordId: activeRecordId, state: nextState });
  }, [activeRecordId]);
  const clearResetTimer = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    loadTokenRef.current += 1;
    clearResetTimer();
  }, [clearResetTimer]);

  const scheduleReset = useCallback(() => {
    clearResetTimer();
    const scheduledRecordId = activeRecordId;
    resetTimerRef.current = window.setTimeout(() => {
      setStateSnapshot((current) => (
        current.recordId === scheduledRecordId
          ? { recordId: scheduledRecordId, state: 'idle' }
          : current
      ));
    }, 2200);
  }, [activeRecordId, clearResetTimer]);

  const prepareShareImage = useCallback(() => {
    if (activeRecordId === undefined) return;

    const loadToken = loadTokenRef.current + 1;
    loadTokenRef.current = loadToken;
    cachedImageRef.current = null;
    setState('loading');

    void historyApi.getShareImage(activeRecordId).then((blob) => {
      if (loadTokenRef.current !== loadToken) return;
      cachedImageRef.current = { recordId: activeRecordId, blob };
      setState('idle');
    }).catch((error: unknown) => {
      if (loadTokenRef.current !== loadToken) return;
      console.error('Generate share image failed:', error);
      setState('error');
    });
  }, [activeRecordId, setState]);

  useEffect(() => {
    clearResetTimer();
    if (activeRecordId === undefined) return undefined;

    const loadToken = loadTokenRef.current + 1;
    loadTokenRef.current = loadToken;
    cachedImageRef.current = null;
    void historyApi.getShareImage(activeRecordId).then((blob) => {
      if (loadTokenRef.current !== loadToken) return;
      cachedImageRef.current = { recordId: activeRecordId, blob };
      setState('idle');
    }).catch((error: unknown) => {
      if (loadTokenRef.current !== loadToken) return;
      console.error('Generate share image failed:', error);
      setState('error');
    });

    return () => {
      clearResetTimer();
      loadTokenRef.current += 1;
    };
  }, [activeRecordId, clearResetTimer, setState]);

  const handleShare = useCallback(async () => {
    if (activeRecordId === undefined || state === 'loading') return;
    const cachedImage = cachedImageRef.current;
    if (!cachedImage || cachedImage.recordId !== activeRecordId) {
      prepareShareImage();
      return;
    }

    const blob = cachedImage.blob;
    const filename = `${safeFilenamePart(reportTitle)}-${activeRecordId}.png`;
    const file = new File([blob], filename, { type: 'image/png' });
    const canShareFile = typeof navigator.share === 'function'
      && typeof navigator.canShare === 'function'
      && navigator.canShare({ files: [file] });

    setState('loading');
    try {
      if (canShareFile) {
        try {
          // The image is preloaded before the click, so navigator.share() is
          // invoked while this user-activation event is still active.
          await navigator.share({
            files: [file],
            title: reportTitle,
          });
        } catch (error) {
          if (error instanceof DOMException && error.name === 'AbortError') {
            setState('idle');
            return;
          }
          console.warn('Native file sharing failed; falling back to download:', error);
          downloadBlob(blob, filename);
        }
      } else {
        downloadBlob(blob, filename);
      }

      setState('success');
      scheduleReset();
    } catch (error) {
      console.error('Generate share image failed:', error);
      setState('error');
    }
  }, [activeRecordId, prepareShareImage, reportTitle, scheduleReset, setState, state]);

  if (activeRecordId === undefined) return null;

  const tooltipText = state === 'loading'
    ? text.generatingShareImage
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
          {state === 'idle' ? <Share2 className="h-5 w-5" aria-hidden="true" /> : null}
          <span>{tooltipText}</span>
        </button>
      </span>
    </Tooltip>
  );
};
