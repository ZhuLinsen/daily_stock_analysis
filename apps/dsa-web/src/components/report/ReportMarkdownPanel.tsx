import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { historyApi } from '../../api/history';
import type { ReportLanguage } from '../../types/analysis';
import { copyTextToClipboard } from '../../utils/clipboard';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Tooltip } from '../common/Tooltip';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import { ShareImageButton } from './ShareImageButton';

export interface ReportMarkdownPanelProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onRequestClose: () => void;
  reportLanguage?: ReportLanguage;
}

type CopyType = 'markdown' | 'text';
type CopyStatus = 'copied' | 'failed';
type CopyFeedback = {
  type: CopyType;
  status: CopyStatus;
  contentKey: string;
};

export const ReportMarkdownPanel: React.FC<ReportMarkdownPanelProps> = ({
  recordId,
  stockName,
  stockCode,
  onRequestClose,
  reportLanguage = 'zh',
}) => {
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const loadReportFailedText = text.loadReportFailed;
  const [content, setContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<CopyFeedback | null>(null);
  const contentKey = `${recordId}\u0000${content}`;
  const [prevContentKey, setPrevContentKey] = useState(contentKey);
  if (prevContentKey !== contentKey) {
    setPrevContentKey(contentKey);
    setCopyFeedback(null);
  }
  const mountedRef = useRef(true);
  const copyTokenRef = useRef(0);
  const copyResetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      copyTokenRef.current += 1;
      if (copyResetTimerRef.current !== null) {
        window.clearTimeout(copyResetTimerRef.current);
        copyResetTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    copyTokenRef.current += 1;
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = null;
    }
  }, [contentKey]);

  const handleCopy = useCallback(async (type: CopyType) => {
    if (!content) return;
    const token = ++copyTokenRef.current;
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = null;
    }
    setCopyFeedback(null);

    const isAttemptCurrent = () =>
      mountedRef.current && copyTokenRef.current === token;

    let ok = false;
    try {
      const value = type === 'markdown' ? content : markdownToPlainText(content);
      ok = await copyTextToClipboard(value, {
        shouldFallback: isAttemptCurrent,
      });
      if (!ok && isAttemptCurrent()) {
        console.error('Copy failed: clipboard unavailable');
      }
    } catch (err) {
      if (isAttemptCurrent()) {
        console.error('Copy failed:', err);
      }
      ok = false;
    }

    if (!isAttemptCurrent()) {
      return;
    }

    setCopyFeedback({
      type,
      status: ok ? 'copied' : 'failed',
      contentKey,
    });

    copyResetTimerRef.current = window.setTimeout(() => {
      copyResetTimerRef.current = null;
      if (!mountedRef.current || copyTokenRef.current !== token) {
        return;
      }
      setCopyFeedback(null);
    }, 2000);
  }, [content, contentKey]);

  const handleCopyMarkdown = useCallback(() => {
    void handleCopy('markdown');
  }, [handleCopy]);

  const handleCopyPlainText = useCallback(() => {
    void handleCopy('text');
  }, [handleCopy]);

  useEffect(() => {
    let isMounted = true;

    const fetchMarkdown = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const markdownContent = await historyApi.getMarkdown(recordId);
        if (isMounted) {
          setContent(markdownContent);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : loadReportFailedText);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    fetchMarkdown();

    return () => {
      isMounted = false;
    };
  }, [recordId, loadReportFailedText]);

  const activeCopyFeedback =
    copyFeedback && copyFeedback.contentKey === contentKey ? copyFeedback : null;
  const markdownCopyStatus =
    activeCopyFeedback?.type === 'markdown' ? activeCopyFeedback.status : 'idle';
  const plainTextCopyStatus =
    activeCopyFeedback?.type === 'text' ? activeCopyFeedback.status : 'idle';
  const markdownButtonLabel =
    markdownCopyStatus === 'copied'
      ? text.copied
      : markdownCopyStatus === 'failed'
        ? text.copyFailed
        : text.copyMarkdownSource;
  const plainTextButtonLabel =
    plainTextCopyStatus === 'copied'
      ? text.copied
      : plainTextCopyStatus === 'failed'
        ? text.copyFailed
        : text.copyPlainText;

  return (
    <>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex flex-1 items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--home-action-report-bg)] text-[var(--home-action-report-text)]">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">{stockName || stockCode}</h2>
            <p className="text-xs text-muted-text">{text.fullReport}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <ShareImageButton
            recordId={recordId}
            reportTitle={`${stockName || stockCode}-${stockCode}`}
            reportLanguage={reportLanguage}
          />
          <Tooltip content={markdownButtonLabel}>
            <span className="inline-flex">
              <button
                type="button"
                onClick={handleCopyMarkdown}
                disabled={isLoading || !content}
                className={`home-surface-button flex h-10 w-10 items-center justify-center rounded-lg disabled:opacity-50 ${
                  markdownCopyStatus === 'failed'
                    ? 'text-danger hover:text-danger'
                    : 'text-secondary-text hover:text-foreground'
                }`}
                aria-label={markdownButtonLabel}
              >
                {markdownCopyStatus === 'copied' ? (
                  <svg className="h-6 w-6 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                ) : markdownCopyStatus === 'failed' ? (
                  <svg className="h-6 w-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                ) : (
                  <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                )}
              </button>
            </span>
          </Tooltip>

          <Tooltip content={plainTextButtonLabel}>
            <span className="inline-flex">
              <button
                type="button"
                onClick={handleCopyPlainText}
                disabled={isLoading || !content}
                className={`home-surface-button flex h-10 w-10 items-center justify-center rounded-lg disabled:opacity-50 ${
                  plainTextCopyStatus === 'failed'
                    ? 'text-danger hover:text-danger'
                    : 'text-secondary-text hover:text-foreground'
                }`}
                aria-label={plainTextButtonLabel}
              >
                {plainTextCopyStatus === 'copied' ? (
                  <svg className="h-6 w-6 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                ) : plainTextCopyStatus === 'failed' ? (
                  <svg className="h-6 w-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                ) : (
                  <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                )}
              </button>
            </span>
          </Tooltip>
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-64 flex-col items-center justify-center">
          <div className="home-spinner h-10 w-10 animate-spin border-[3px]" />
          <p className="mt-4 text-sm text-secondary-text">{text.loadingReport}</p>
        </div>
      ) : error ? (
        <div className="flex h-64 flex-col items-center justify-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-danger/10">
            <svg className="h-6 w-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <p className="text-sm text-danger">{error}</p>
          <button
            type="button"
            onClick={onRequestClose}
            className="home-surface-button mt-4 rounded-lg px-4 py-2 text-sm text-secondary-text"
          >
            {text.dismiss}
          </button>
        </div>
      ) : (
        <ReportMarkdownBody content={content} />
      )}

      <div className="home-divider mt-6 flex justify-end border-t pt-4">
        <button
          type="button"
          onClick={onRequestClose}
          className="home-surface-button rounded-lg px-4 py-2 text-sm text-secondary-text hover:text-foreground"
        >
          {text.dismiss}
        </button>
      </div>
    </>
  );
};
