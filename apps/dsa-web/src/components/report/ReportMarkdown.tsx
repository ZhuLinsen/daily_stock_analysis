import type React from 'react';
import { useEffect, useState, useCallback } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { historyApi } from '../../api/history';
import { Drawer } from '../common/Drawer';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import type { ReportLanguage } from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';

interface ReportMarkdownProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onClose: () => void;
  reportLanguage?: ReportLanguage;
}

/**
 * Markdown report drawer component
 * Uses common Drawer component to display full Markdown format analysis report
 */
export const ReportMarkdown: React.FC<ReportMarkdownProps> = ({
  recordId,
  stockName,
  stockCode,
  onClose,
  reportLanguage = 'zh',
}) => {
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const loadReportFailedText = text.loadReportFailed;
  const [content, setContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(true);
  const [copiedType, setCopiedType] = useState<'markdown' | 'text' | null>(null);

  // Handle close with animation
  const handleClose = useCallback(() => {
    setIsOpen(false);
    // Delay actual close to allow animation to complete
    setTimeout(onClose, 300);
  }, [onClose]);

  // Handle copy markdown source
  const handleCopyMarkdown = useCallback(async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopiedType('markdown');
      setTimeout(() => setCopiedType(null), 2000);
    } catch (error) {
      console.error('Copy failed:', error);
    }
  }, [content]);

  // Handle copy plain text
  const handleCopyPlainText = useCallback(async () => {
    if (!content) return;
    try {
      const plainText = markdownToPlainText(content);
      await navigator.clipboard.writeText(plainText);
      setCopiedType('text');
      setTimeout(() => setCopiedType(null), 2000);
    } catch (error) {
      console.error('Copy failed:', error);
    }
  }, [content]);

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

  return (
    <Drawer isOpen={isOpen} onClose={handleClose} width="max-w-3xl" zIndex={100}>
      {/* Custom Header */}
      <div className="flex items-center justify-between gap-3 mb-4">
        {/* Left: Icon + Title */}
        <div className="flex items-center gap-3 flex-1">
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

        {/* Right: Toolbar */}
        <div className="flex items-center gap-2">
          {/* Copy Markdown button */}
          <button
            type="button"
            onClick={handleCopyMarkdown}
            disabled={isLoading || !content || copiedType !== null}
            className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
            title={text.copyMarkdownSource}
            aria-label={text.copyMarkdownSource}
          >
            {copiedType === 'markdown' ? (
              <svg className="h-6 w-6 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            )}
          </button>

          {/* Copy plain text button */}
          <button
            type="button"
            onClick={handleCopyPlainText}
            disabled={isLoading || !content || copiedType !== null}
            className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
            title={text.copyPlainText}
            aria-label={text.copyPlainText}
          >
            {copiedType === 'text' ? (
              <svg className="h-6 w-6 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center h-64">
          <div className="home-spinner h-10 w-10 animate-spin border-[3px]" />
          <p className="mt-4 text-secondary-text text-sm">{text.loadingReport}</p>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center h-64">
          <div className="w-12 h-12 rounded-xl bg-danger/10 flex items-center justify-center mb-3">
            <svg className="w-6 h-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <p className="text-danger text-sm">{error}</p>
          <button
            type="button"
            onClick={handleClose}
            className="home-surface-button mt-4 rounded-lg px-4 py-2 text-sm text-secondary-text"
          >
            {text.dismiss}
          </button>
        </div>
      ) : (
        <div
          className="home-markdown-prose prose prose-invert prose-sm max-w-none
            prose-headings:text-foreground prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2
            prose-h1:text-xl
            prose-h2:text-lg
            prose-h3:text-base
            prose-p:leading-relaxed prose-p:mb-3 prose-p:last:mb-0
            prose-strong:text-foreground prose-strong:font-semibold
            prose-ul:my-2 prose-ol:my-2 prose-li:my-1
            prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none
            prose-pre:border
            prose-table:border-collapse
            prose-hr:my-4
            prose-a:no-underline hover:prose-a:underline
            prose-blockquote:text-secondary-text
            whitespace-pre-line break-words
          "
        >
          <Markdown remarkPlugins={[remarkGfm]}>
            {content}
          </Markdown>
        </div>
      )}

      {/* Footer */}
      <div className="home-divider mt-6 flex justify-end border-t pt-4">
        <button
          type="button"
          onClick={handleClose}
          className="home-surface-button rounded-lg px-4 py-2 text-sm text-secondary-text hover:text-foreground"
        >
          {text.dismiss}
        </button>
      </div>
    </Drawer>
  );
};
