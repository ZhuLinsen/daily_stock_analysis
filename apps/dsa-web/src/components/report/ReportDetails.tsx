import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import type { ReportDetails as ReportDetailsType, ReportLanguage } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { copyTextToClipboard } from '../../utils/clipboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportDetailsProps {
  details?: ReportDetailsType;
  recordId?: number;  // 分析历史记录主键 ID
  language?: ReportLanguage;
}

type JsonPanel = 'raw' | 'snapshot';
type CopyStatus = 'idle' | 'copied' | 'failed';
type PanelCopyEntry = { key: string; status: CopyStatus };
type PanelCopyState = Record<JsonPanel, PanelCopyEntry>;

const createIdleCopyState = (): PanelCopyState => ({
  raw: { key: '', status: 'idle' },
  snapshot: { key: '', status: 'idle' },
});

function clearPanelResetTimers(timers: Partial<Record<JsonPanel, number>>): void {
  (Object.keys(timers) as JsonPanel[]).forEach((panel) => {
    const timerId = timers[panel];
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      delete timers[panel];
    }
  });
}

function serializeDetailValue(value: unknown): string {
  if (value === undefined || value === null) {
    return '';
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * 透明度与追溯区组件 - 终端风格
 */
export const ReportDetails: React.FC<ReportDetailsProps> = ({
  details,
  recordId,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const rawJsonStr = details?.rawResult ? serializeDetailValue(details.rawResult) : '';
  const snapshotJsonStr = details?.contextSnapshot ? serializeDetailValue(details.contextSnapshot) : '';
  const rawPanelKey = `${recordId ?? ''}\u0000${rawJsonStr}`;
  const snapshotPanelKey = `${recordId ?? ''}\u0000${snapshotJsonStr}`;
  const contentKey = `${rawPanelKey}\u0001${snapshotPanelKey}`;
  const [showRaw, setShowRaw] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [panelCopyState, setPanelCopyState] = useState<PanelCopyState>(createIdleCopyState);
  const [prevContentKey, setPrevContentKey] = useState(contentKey);
  if (prevContentKey !== contentKey) {
    setPrevContentKey(contentKey);
    setPanelCopyState(createIdleCopyState());
  }
  const copyResetTimerRef = useRef<Partial<Record<JsonPanel, number>>>({});
  const mountedRef = useRef(true);
  const copyTokenRef = useRef<Record<JsonPanel, number>>({ raw: 0, snapshot: 0 });
  const clipboardAttemptIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    const copyTokens = copyTokenRef.current;
    const resetTimers = copyResetTimerRef.current;
    return () => {
      mountedRef.current = false;
      clipboardAttemptIdRef.current += 1;
      copyTokens.raw += 1;
      copyTokens.snapshot += 1;
      clearPanelResetTimers(resetTimers);
    };
  }, []);

  useEffect(() => {
    clipboardAttemptIdRef.current += 1;
    copyTokenRef.current.raw += 1;
    copyTokenRef.current.snapshot += 1;
    clearPanelResetTimers(copyResetTimerRef.current);
  }, [contentKey]);

  if (!details?.rawResult && !details?.contextSnapshot && !recordId) {
    return null;
  }

  const copyToClipboard = async (content: string, panel: JsonPanel, panelKey: string) => {
    const token = ++copyTokenRef.current[panel];
    const clipboardAttemptId = ++clipboardAttemptIdRef.current;
    const prevTimer = copyResetTimerRef.current[panel];
    if (prevTimer !== undefined) {
      window.clearTimeout(prevTimer);
      delete copyResetTimerRef.current[panel];
    }
    setPanelCopyState((prev) =>
      prev[panel].key === panelKey && prev[panel].status === 'idle'
        ? prev
        : {
            ...prev,
            [panel]: { key: panelKey, status: 'idle' },
          },
    );
    const ok = await copyTextToClipboard(content, {
      shouldFallback: () =>
        mountedRef.current &&
        copyTokenRef.current[panel] === token &&
        clipboardAttemptIdRef.current === clipboardAttemptId,
    });
    if (
      !mountedRef.current ||
      copyTokenRef.current[panel] !== token ||
      clipboardAttemptIdRef.current !== clipboardAttemptId
    ) {
      return;
    }
    setPanelCopyState((prev) => ({
      ...prev,
      [panel]: { key: panelKey, status: ok ? 'copied' : 'failed' },
    }));
    if (!ok) {
      console.error('Copy failed: clipboard unavailable');
    }
    const existingTimer = copyResetTimerRef.current[panel];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
    }
    copyResetTimerRef.current[panel] = window.setTimeout(() => {
      delete copyResetTimerRef.current[panel];
      if (!mountedRef.current || copyTokenRef.current[panel] !== token) {
        return;
      }
      setPanelCopyState((prev) => ({
        ...prev,
        [panel]: { key: panelKey, status: 'idle' },
      }));
    }, 2000);
  };

  const renderJson = (jsonStr: string, panel: JsonPanel, panelKey: string) => {
    const activeEntry = panelCopyState[panel];
    const status: CopyStatus = activeEntry.key === panelKey ? activeEntry.status : 'idle';
    const buttonLabel =
      status === 'copied' ? text.copied : status === 'failed' ? text.copyFailed : text.copy;
    return (
      <div className="relative overflow-hidden">
        <span className="absolute top-2 right-2 z-10 inline-flex">
          <button
            type="button"
            onClick={() => void copyToClipboard(jsonStr, panel, panelKey)}
            className={`home-accent-link text-xs ${
              status === 'failed' ? 'text-danger' : 'text-muted-text'
            }`}
            aria-label={buttonLabel}
          >
            {buttonLabel}
          </button>
        </span>
        <pre className="home-trace-pre home-trace-pre-content text-xs text-foreground font-mono overflow-x-auto p-3 bg-base rounded-lg max-h-80 overflow-y-auto text-left w-0 min-w-full">
          {jsonStr}
        </pre>
      </div>
    );
  };

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <DashboardPanelHeader
        eyebrow={text.transparency}
        title={text.traceability}
        className="mb-3"
      />

      {/* Record ID */}
      {recordId && (
        <div className="home-divider mb-3 flex items-center gap-2 border-b pb-3 text-xs text-muted-text">
          <span>{text.recordId}:</span>
          <code className="home-accent-chip px-1.5 py-0.5 font-mono text-xs">
            {recordId}
          </code>
        </div>
      )}

      {/* 折叠区域 */}
      <div className="space-y-2">
        {/* 原始分析结果 */}
        {details?.rawResult && (
          <div>
            <button
              type="button"
              onClick={() => setShowRaw(!showRaw)}
              className="home-surface-button home-trace-toggle flex w-full items-center justify-between rounded-lg p-2.5"
            >
              <span className="text-xs text-foreground">{text.rawResult}</span>
              <svg
                className={`w-3.5 h-3.5 text-muted-text transition-transform ${showRaw ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showRaw && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(rawJsonStr, 'raw', rawPanelKey)}
              </div>
            )}
          </div>
        )}

        {/* 分析快照 */}
        {details?.contextSnapshot && (
          <div>
            <button
              type="button"
              onClick={() => setShowSnapshot(!showSnapshot)}
              className="home-surface-button home-trace-toggle flex w-full items-center justify-between rounded-lg p-2.5"
            >
              <span className="text-xs text-foreground">{text.analysisSnapshot}</span>
              <svg
                className={`w-3.5 h-3.5 text-muted-text transition-transform ${showSnapshot ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showSnapshot && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(snapshotJsonStr, 'snapshot', snapshotPanelKey)}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};
