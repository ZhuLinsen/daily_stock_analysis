import type React from 'react';
import { isValidElement, useCallback, useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import type { ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { historyApi } from '../../api/history';
import type { AnalysisReport, ReportLanguage } from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Tooltip } from '../common/Tooltip';
import { MermaidDiagram } from './MermaidDiagram';
import { TwDailyReportView } from './TwDailyReportView';
import {
  buildTwDailyReportFromSnapshot,
  extractTwDailySnapshotFromReport,
  parseTwDailyReportMarkdown,
} from './twDailyReportAdapter';
import { FourMastersCommentarySection } from './visual/FourMastersCommentarySection';
import { adaptFourMastersCommentary } from './visual/fourMastersCommentaryAdapter';
import { ReportVisualSummary } from './visual/ReportVisualSummary';

type CodeProps = React.ComponentProps<'code'> & ExtraProps;

const cx = (...classes: Array<string | undefined>) => classes.filter(Boolean).join(' ');

const getNodeText = (node: React.ReactNode): string => {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(getNodeText).join('');
  }
  if (isValidElement<{ children?: React.ReactNode }>(node)) {
    return getNodeText(node.props.children);
  }
  return '';
};

const REPORT_LABEL_LINE_PATTERN =
  /^(?:📊|⚠️|⚠|🎯|⏱️|⏱|📈|📉|🧭|🔬|🛡️|🛡|✅|❌|💡|🔥|📌|🧾|🔎|🪙|💰|🧩|🚨|✨|📍|🌡️|🌡|🧠|📝)/u;
const DEPRECATED_REPORT_TERM_PATTERN = /籌碼(?:集中度|分布|分佈|判斷)?/u;
const DUPLICATE_SECTION_HEADING_PATTERN = /^#{1,3}\s+.*(?:當日行情|市場風險溫度計|多週期趨勢快照)\s*$/u;
const DUPLICATE_REPORT_TITLE_PATTERN = /^#\s+.*(?:股票分析報告|分析報告)\s*$/u;
const DUPLICATE_SIGNAL_LINE_PATTERN =
  /^\s*\*\*.*(?:買進|加倉|持有|減倉|賣出|觀望).*?\*\*\s*\|\s*(?:強烈看多|看多|震盪|震盪偏多|震盪偏空|看空|強烈看空)\s*$/u;
const CHECKLIST_MARKER_PATTERN = /(?:檢查清單|檢查未透過項)/u;
const CHECKLIST_LINE_PATTERN = /^\s*(?:[-*]\s*)?(✅|❌|⚠️|⚠)\s*(.+)$/u;

const stripMarkdownEmphasis = (text: string): string => text.replace(/\*\*/g, '').trim();

const shouldSuppressMarkdownLine = (line: string): boolean => {
  const trimmed = line.trim();
  return (
    DEPRECATED_REPORT_TERM_PATTERN.test(trimmed) ||
    DUPLICATE_REPORT_TITLE_PATTERN.test(trimmed) ||
    DUPLICATE_SIGNAL_LINE_PATTERN.test(trimmed)
  );
};

const shouldSuppressMarkdownSection = (section: string): boolean => {
  const heading = section.split(/\r?\n/).find((line) => line.trim());
  return Boolean(heading && (
    DEPRECATED_REPORT_TERM_PATTERN.test(heading) ||
    DUPLICATE_SECTION_HEADING_PATTERN.test(heading.trim())
  ));
};

const checklistRowFromLine = (line: string): string | null => {
  const match = CHECKLIST_LINE_PATTERN.exec(line);
  if (!match) return null;
  const status = match[1];
  const body = stripMarkdownEmphasis(match[2]).replace(/^\uFE0F/u, '').trim();
  const [item, ...rest] = body.split(/[:：]/u);
  return `| ${status} | ${item.trim()} | ${(rest.join('：').trim() || '—')} |`;
};

const formatChecklistSection = (section: string): string => {
  const lines = section.split(/\r?\n/);
  if (!lines.some((line) => CHECKLIST_MARKER_PATTERN.test(stripMarkdownEmphasis(line)))) {
    return section;
  }

  const rows = lines.map(checklistRowFromLine).filter((row): row is string => Boolean(row));
  if (!rows.length) return section;

  const output: string[] = [];
  let insertedTable = false;
  for (const line of lines) {
    if (checklistRowFromLine(line)) {
      if (!insertedTable) {
        output.push('| 狀態 | 檢查項目 | 解讀 |');
        output.push('|---|---|---|');
        output.push(...rows);
        insertedTable = true;
      }
      continue;
    }
    output.push(line);
  }

  return output.join('\n').trim();
};

// Phase 25.7: markdown heading of the backend-generated four-masters section.
// Stripped (heading through the next h1/h2 or horizontal rule, including its
// ### sub-sections and disclaimer) only when the structured UI renders from
// raw_result, so the user never sees the same commentary twice.
const FOUR_MASTERS_SECTION_HEADING_PATTERN = /^#{1,3}\s+(?:四大師視角補充|Four Masters Commentary)\s*$/u;

function stripFourMastersMarkdownSection(markdown: string): string {
  const output: string[] = [];
  let inFence = false;
  let skipping = false;

  for (const line of markdown.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith('```')) inFence = !inFence;

    if (!inFence && FOUR_MASTERS_SECTION_HEADING_PATTERN.test(trimmed)) {
      skipping = true;
      continue;
    }
    if (skipping && !inFence && (/^#{1,2}\s+\S/.test(trimmed) || /^-{3,}\s*$/.test(trimmed))) {
      skipping = false;
    }
    if (!skipping) output.push(line);
  }

  return output.join('\n');
}

function sanitizeReportMarkdown(markdown: string, suppressFourMastersSection = false): string {
  const source = suppressFourMastersSection ? stripFourMastersMarkdownSection(markdown) : markdown;
  return splitMarkdownSections(source)
    .map((section) => section
      .split(/\r?\n/)
      .filter((line) => !shouldSuppressMarkdownLine(line))
      .join('\n')
      .trim())
    .filter((section) => section && !shouldSuppressMarkdownSection(section))
    .map(formatChecklistSection)
    .join('\n\n');
}

const MARKDOWN_COMPONENTS = {
  h1: ({ className, ...props }: React.ComponentProps<'h1'>) => (
    <h1 className={cx('report-body-title', className)} {...props} />
  ),
  h2: ({ className, ...props }: React.ComponentProps<'h2'>) => (
    <h2 className={cx('report-body-heading', className)} {...props} />
  ),
  h3: ({ className, ...props }: React.ComponentProps<'h3'>) => (
    <h3 className={cx('report-body-heading', 'report-body-heading-level3', className)} {...props} />
  ),
  p: ({ className, children, ...props }: React.ComponentProps<'p'>) => {
    const isLabelLine = REPORT_LABEL_LINE_PATTERN.test(getNodeText(children).trim());
    return (
      <p
        className={cx('report-body-paragraph', isLabelLine ? 'report-body-label-line' : undefined, className)}
        {...props}
      >
        {children}
      </p>
    );
  },
  strong: ({ className, ...props }: React.ComponentProps<'strong'>) => (
    <strong className={cx('report-body-strong', className)} {...props} />
  ),
  em: ({ className, ...props }: React.ComponentProps<'em'>) => (
    <em className={cx('report-body-emphasis', className)} {...props} />
  ),
  table: ({ className, children, ...props }: React.ComponentProps<'table'>) => {
    const text = getNodeText(children);
    const isBattlePlan = /(?:理想買進|次優買進|停損|停利|目標|操作建議|操作點位)/u.test(text);
    const isChecklist = /(?:檢查項目|解讀)/u.test(text);
    const isGapTable = (text.match(/資料不足/g) ?? []).length >= 2;
    return (
      <table
        className={cx(
          'report-body-table',
          isBattlePlan ? 'report-body-battle-table' : undefined,
          isChecklist ? 'report-body-checklist-table' : undefined,
          isGapTable ? 'report-body-gap-table' : undefined,
          className
        )}
        {...props}
      >
        {children}
      </table>
    );
  },
  blockquote: ({ className, children, ...props }: React.ComponentProps<'blockquote'>) => {
    const isMeta = /(?:分析日期|報告生成時間)/u.test(getNodeText(children));
    return (
      <blockquote
        className={cx('report-body-callout', isMeta ? 'report-body-meta-strip' : undefined, className)}
        {...props}
      >
        {children}
      </blockquote>
    );
  },
  ul: ({ className, ...props }: React.ComponentProps<'ul'>) => (
    <ul className={cx('report-body-list', className)} {...props} />
  ),
  ol: ({ className, ...props }: React.ComponentProps<'ol'>) => (
    <ol className={cx('report-body-list', className)} {...props} />
  ),
  li: ({ className, ...props }: React.ComponentProps<'li'>) => (
    <li className={cx('report-body-list-item', className)} {...props} />
  ),
  hr: ({ className, ...props }: React.ComponentProps<'hr'>) => (
    <hr className={cx('report-body-rule', className)} {...props} />
  ),
  pre: ({ className, ...props }: React.ComponentProps<'pre'>) => (
    <pre className={cx('report-body-pre', className)} {...props} />
  ),
  a: ({ className, ...props }: React.ComponentProps<'a'>) => (
    <a className={cx('report-body-link', className)} {...props} />
  ),
  code: ({ className, children, ...props }: CodeProps) => {
    if (className === 'language-mermaid') {
      return (
        <figure className="report-body-mermaid-figure">
          <figcaption className="report-body-figure-caption">
            Fig. 1 · 供應商 / 客戶 / 競爭者 / 互補者結構
          </figcaption>
          <div className="report-body-mermaid">
            <MermaidDiagram code={String(children).trim()} />
          </div>
        </figure>
      );
    }
    return (
      <code className={cx('report-body-code', className)} {...props}>
        {children}
      </code>
    );
  },
};

function splitMarkdownSections(markdown: string): string[] {
  const sections: string[] = [];
  const current: string[] = [];
  let inFence = false;

  for (const line of markdown.split(/\r?\n/)) {
    const isFence = line.trim().startsWith('```');
    const isSectionHeading = !inFence && /^#{1,3}\s+\S/.test(line);

    if (isSectionHeading && current.some((item) => item.trim())) {
      sections.push(current.join('\n').trim());
      current.length = 0;
    }

    current.push(line);
    if (isFence) inFence = !inFence;
  }

  if (current.some((item) => item.trim())) {
    sections.push(current.join('\n').trim());
  }

  return sections;
}

export interface ReportMarkdownPanelProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onRequestClose: () => void;
  reportLanguage?: ReportLanguage;
  variant?: 'drawer' | 'print';
  initialDetail?: AnalysisReport | null;
  onContentReady?: () => void;
}

export const ReportMarkdownPanel: React.FC<ReportMarkdownPanelProps> = ({
  recordId,
  stockName,
  stockCode,
  onRequestClose,
  reportLanguage = 'zh',
  variant = 'drawer',
  initialDetail,
  onContentReady,
}) => {
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const loadReportFailedText = text.loadReportFailed;
  const [content, setContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedType, setCopiedType] = useState<'markdown' | 'text' | null>(null);
  const [detail, setDetail] = useState<AnalysisReport | null>(initialDetail ?? null);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const fourMastersVM = adaptFourMastersCommentary(
    (detail?.details?.rawResult as Record<string, unknown> | undefined)?.fourMastersCommentary
  );
  const sanitizedContent = sanitizeReportMarkdown(content, fourMastersVM !== null);
  const sections = splitMarkdownSections(sanitizedContent);
  const isMarketReviewReport = detail?.meta?.reportType === 'market_review' || stockCode === 'MARKET';
  const twDailyReport = isMarketReviewReport
    ? buildTwDailyReportFromSnapshot(extractTwDailySnapshotFromReport(detail)) ?? parseTwDailyReportMarkdown(sanitizedContent)
    : null;
  const isPrintVariant = variant === 'print';

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

  const handleDownloadPdf = useCallback(async () => {
    if (!content || isGeneratingPdf) return;
    setPdfError(null);
    setIsGeneratingPdf(true);
    try {
      const { blob, filename } = await historyApi.getPdf(recordId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.style.display = 'none';
      document.body.appendChild(link);
      try {
        link.click();
      } finally {
        link.remove();
        URL.revokeObjectURL(url);
      }
    } catch {
      setPdfError('PDF 產生失敗，請稍後再試。');
    } finally {
      setIsGeneratingPdf(false);
    }
  }, [content, isGeneratingPdf, recordId]);

  useEffect(() => {
    let isMounted = true;

    const fetchMarkdown = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const shouldFetchDetail = initialDetail === undefined;
        const [markdownContent, detailResult] = await Promise.allSettled([
          historyApi.getMarkdown(recordId),
          shouldFetchDetail ? historyApi.getDetail(recordId) : Promise.resolve(initialDetail),
        ]);
        if (isMounted) {
          if (markdownContent.status === 'fulfilled') {
            setContent(markdownContent.value);
          } else {
            setError(markdownContent.reason instanceof Error ? markdownContent.reason.message : loadReportFailedText);
          }
          if (detailResult.status === 'fulfilled') {
            setDetail(detailResult.value);
          }
          // ponytail: detail fetch failure is silent — visual summary just won't render
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
  }, [recordId, loadReportFailedText, initialDetail]);

  useEffect(() => {
    if (!isLoading && !error && content) {
      onContentReady?.();
    }
  }, [content, error, isLoading, onContentReady]);

  return (
    <>
      {!isPrintVariant && (
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

        {!isPrintVariant && (
        <div className="flex items-center gap-2">
          <Tooltip content={isGeneratingPdf ? '產生 PDF...' : text.downloadPdf}>
            <span className="inline-flex">
              <button
                type="button"
                onClick={handleDownloadPdf}
                disabled={isLoading || !content || isGeneratingPdf}
                className="home-surface-button flex h-10 min-w-10 items-center justify-center rounded-lg px-2 text-xs font-bold text-secondary-text hover:text-foreground disabled:opacity-50"
                aria-label={text.downloadPdf}
              >
                {isGeneratingPdf ? '產生 PDF...' : 'PDF'}
              </button>
            </span>
          </Tooltip>

          <Tooltip content={text.copyMarkdownSource}>
            <span className="inline-flex">
              <button
                type="button"
                onClick={handleCopyMarkdown}
                disabled={isLoading || !content || copiedType !== null}
                className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
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
            </span>
          </Tooltip>

          <Tooltip content={text.copyPlainText}>
            <span className="inline-flex">
              <button
                type="button"
                onClick={handleCopyPlainText}
                disabled={isLoading || !content || copiedType !== null}
                className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
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
            </span>
          </Tooltip>
        </div>
        )}
      </div>
      )}

      {!isPrintVariant && pdfError && (
        <p role="alert" className="mb-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
          {pdfError}
        </p>
      )}

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
          <p className="text-sm font-semibold text-danger">
            {isPrintVariant ? '無法載入列印報告' : error}
          </p>
          {isPrintVariant ? (
            <p className="mt-2 text-sm text-muted-text">請返回完整分析報告後再試一次。</p>
          ) : (
            <button
              type="button"
              onClick={onRequestClose}
              className="home-surface-button mt-4 rounded-lg px-4 py-2 text-sm text-secondary-text"
            >
              {text.dismiss}
            </button>
          )}
        </div>
      ) : (
        <>
        {detail && !isMarketReviewReport && <ReportVisualSummary report={detail} historyId={recordId} />}
        {twDailyReport ? (
          <TwDailyReportView report={twDailyReport} />
        ) : (
          <>
            <div
              data-testid="report-markdown-body"
              className="report-light-surface report-markdown-body report-body-paper break-words"
            >
              {sections.map((section, index) => (
                <section
                  key={`${index}-${section.slice(0, 24)}`}
                  data-testid="report-body-section"
                  className="report-body-section"
                >
                  <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                    {section}
                  </Markdown>
                </section>
              ))}
            </div>
            {fourMastersVM !== null && (
              <FourMastersCommentarySection
                rawCommentary={
                  (detail?.details?.rawResult as Record<string, unknown> | undefined)?.fourMastersCommentary
                }
              />
            )}
          </>
        )}
        </>
      )}

      {!isPrintVariant && (
      <div className="home-divider mt-6 flex justify-end border-t pt-4">
        <button
          type="button"
          onClick={onRequestClose}
          className="home-surface-button rounded-lg px-4 py-2 text-sm text-secondary-text hover:text-foreground"
        >
          {text.dismiss}
        </button>
      </div>
      )}
    </>
  );
};
