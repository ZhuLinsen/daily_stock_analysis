import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Download, Loader2, TriangleAlert } from 'lucide-react';
import { historyApi } from '../../api/history';
import type { ReportLanguage } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Tooltip } from '../common/Tooltip';

type ExportState = 'idle' | 'loading' | 'success' | 'error';

interface ExportHtmlButtonProps {
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
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
};

export const ExportHtmlButton: React.FC<ExportHtmlButtonProps> = ({
  recordId,
  reportTitle,
  reportLanguage = 'zh',
  className = '',
}) => {
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const [stateSnapshot, setStateSnapshot] = useState<{
    recordId?: number;
    state: ExportState;
  }>(() => ({
    recordId,
    state: 'idle',
  }));
  const resetTimerRef = useRef<number | null>(null);
  const loadTokenRef = useRef(0);
  const state = stateSnapshot.recordId === recordId ? stateSnapshot.state : 'idle';

  const setState = useCallback((nextState: ExportState) => {
    setStateSnapshot({ recordId, state: nextState });
  }, [recordId]);

  const clearResetTimer = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const scheduleReset = useCallback(() => {
    clearResetTimer();
    const scheduledId = recordId;
    resetTimerRef.current = window.setTimeout(() => {
      setStateSnapshot((current) => (
        current.recordId === scheduledId
          ? { recordId: scheduledId, state: 'idle' }
          : current
      ));
    }, 2200);
  }, [recordId, clearResetTimer]);

  useEffect(() => {
    clearResetTimer();
    loadTokenRef.current += 1;
    return () => {
      clearResetTimer();
      loadTokenRef.current += 1;
    };
  }, [recordId, clearResetTimer]);

  const handleExport = useCallback(async () => {
    if (recordId === undefined || state === 'loading') return;
    clearResetTimer();
    const loadToken = loadTokenRef.current + 1;
    loadTokenRef.current = loadToken;
    setState('loading');

    try {
      const blob = await historyApi.exportHtml(recordId);
      if (loadTokenRef.current !== loadToken) return;
      const filename = `${safeFilenamePart(reportTitle)}-${recordId}.html`;
      downloadBlob(blob, filename);
      setState('success');
      scheduleReset();
    } catch (error) {
      if (loadTokenRef.current !== loadToken) return;
      console.error('Export HTML report failed:', error);
      setState('error');
    }
  }, [clearResetTimer, recordId, reportTitle, scheduleReset, setState, state]);

  if (recordId === undefined) return null;

  const labelText = state === 'loading'
    ? text.exportingHtml
    : state === 'success'
      ? text.exportHtmlReady
      : state === 'error'
        ? text.exportHtmlFailed
        : text.exportHtml;

  return (
    <Tooltip content={labelText}>
      <span className="inline-flex shrink-0 print:hidden">
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={state === 'loading'}
          className={`home-surface-button flex h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 text-sm font-medium text-secondary-text hover:text-foreground disabled:opacity-50 ${className}`}
          aria-label={labelText}
        >
          {state === 'loading' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
          {state === 'success' ? <Check className="h-4 w-4 text-success" aria-hidden="true" /> : null}
          {state === 'error' ? <TriangleAlert className="h-4 w-4 text-danger" aria-hidden="true" /> : null}
          {state === 'idle' ? <Download className="h-4 w-4" aria-hidden="true" /> : null}
          <span>{labelText}</span>
        </button>
      </span>
    </Tooltip>
  );
};
