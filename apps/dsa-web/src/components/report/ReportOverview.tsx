import type React from 'react';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportSummary as ReportSummaryType,
} from '../../types/analysis';
import { ScoreGauge, Card } from '../common';
import { formatDateTime } from '../../utils/format';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  details?: ReportDetailsType;
  isHistory?: boolean;
}

type BoardStatus = 'leading' | 'lagging';

type BoardSignal = {
  status: BoardStatus;
  changePct?: number;
};

const normalizeBoardName = (value?: string): string =>
  (value || '').trim().replace(/\s+/g, ' ');

const coerceFiniteNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim().replace(/%$/, '');
    if (!trimmed) {
      return undefined;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const buildBoardSignalMap = (details?: ReportDetailsType): Map<string, BoardSignal> => {
  const signalMap = new Map<string, BoardSignal>();
  const topBoards = Array.isArray(details?.sectorRankings?.top) ? details.sectorRankings.top : [];
  const bottomBoards = Array.isArray(details?.sectorRankings?.bottom) ? details.sectorRankings.bottom : [];

  topBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    if (!normalizedName) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'leading',
      changePct: coerceFiniteNumber(item.changePct),
    });
  });

  bottomBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    if (!normalizedName) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'lagging',
      changePct: coerceFiniteNumber(item.changePct),
    });
  });

  return signalMap;
};

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  details,
}) => {
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const relatedBoards = (Array.isArray(details?.belongBoards) ? details.belongBoards : [])
    .filter((board) => normalizeBoardName(board?.name).length > 0)
    .slice(0, 3);
  const boardSignals = buildBoardSignalMap(details);

  const getPriceChangeStyle = (changePct: number | undefined): React.CSSProperties | undefined => {
    if (changePct === undefined || changePct === null) {
      return undefined;
    }

    if (changePct > 0) {
      return { color: 'var(--home-price-up)' };
    }

    if (changePct < 0) {
      return { color: 'var(--home-price-down)' };
    }

    return undefined;
  };

  const formatChangePct = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return '--';
    const sign = changePct > 0 ? '+' : '';
    return `${sign}${changePct.toFixed(2)}%`;
  };

  const getBoardStatusLabel = (status: BoardStatus): string => {
    if (status === 'leading') {
      return text.leadingBoard;
    }
    return text.laggingBoard;
  };

  const getBoardStatusClassName = (status: BoardStatus): string => {
    if (status === 'leading') {
      return 'bg-success/10 text-success';
    }
    return 'bg-danger/10 text-danger';
  };

  return (
    <div className="space-y-5">
      {/* 主信息区 - 两列布局，items-stretch 确保右侧与左侧同高 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-stretch">
        {/* 左侧：股票信息与结论 */}
        <div className="lg:col-span-2 space-y-5">
          {/* 股票头部 */}
          <Card variant="gradient" padding="md">
            <div className="flex items-start justify-between mb-5">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h2 className="text-[28px] font-bold leading-tight text-foreground">
                    {meta.stockName || meta.stockCode}
                  </h2>
                  {/* 价格和涨跌幅 */}
                  {meta.currentPrice != null && (
                    <div className="flex items-baseline gap-2">
                      <span className="text-xl font-bold font-mono" style={getPriceChangeStyle(meta.changePct)}>
                        {meta.currentPrice.toFixed(2)}
                      </span>
                      <span className="text-sm font-semibold font-mono" style={getPriceChangeStyle(meta.changePct)}>
                        {formatChangePct(meta.changePct)}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="home-accent-chip px-2 py-0.5 font-mono text-xs">
                    {meta.stockCode}
                  </span>
                  <span className="text-xs text-muted-text flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    {formatDateTime(meta.createdAt)}
                  </span>
                </div>
              </div>
            </div>

            {/* 关键结论 */}
            <div className="home-divider border-t pt-5">
              <span className="label-uppercase">{text.keyInsights}</span>
              <p className="mt-2 max-w-[62ch] whitespace-pre-wrap text-left text-[15px] leading-7 text-foreground">
                {summary.analysisSummary || text.noAnalysisSummary}
              </p>
            </div>
          </Card>

          {/* 操作建议和趋势预测 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 操作建议 */}
            <Card variant="bordered" padding="sm" hoverable className="home-panel-card">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-success/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="text-[11px] font-medium uppercase tracking-[0.16em] text-success">{text.actionAdvice}</h4>
                  <p className="text-sm leading-6 text-foreground">
                    {summary.operationAdvice || text.noAdvice}
                  </p>
                </div>
              </div>
            </Card>

            {/* 趋势预测 */}
            <Card variant="bordered" padding="sm" hoverable className="home-panel-card">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-warning/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="text-[11px] font-medium uppercase tracking-[0.16em] text-warning">{text.trendPrediction}</h4>
                  <p className="text-sm leading-6 text-foreground">
                    {summary.trendPrediction || text.noPrediction}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          {relatedBoards.length > 0 && (
            <Card variant="bordered" padding="sm" className="home-panel-card text-left">
              <div className="mb-3 flex items-baseline gap-2">
                <span className="label-uppercase">{text.boardLinkage}</span>
                <h3 className="mt-0.5 text-base font-semibold text-foreground">{text.relatedBoards}</h3>
              </div>

              <div className="space-y-2.5">
                {relatedBoards.map((board, index) => {
                  const boardName = normalizeBoardName(board.name);
                  const signal = boardSignals.get(boardName);
                  return (
                    <div
                      key={`${boardName}-${board.code || index}`}
                      className="flex flex-wrap items-center gap-2 text-sm"
                    >
                      <span className="home-accent-chip px-2 py-0.5 text-xs font-medium">
                        {boardName}
                      </span>
                      {board.type && (
                        <span className="rounded-full bg-muted/30 px-2 py-0.5 text-xs text-muted-text">
                          {board.type}
                        </span>
                      )}
                      {signal && (
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${getBoardStatusClassName(signal.status)}`}
                        >
                          {getBoardStatusLabel(signal.status)}
                        </span>
                      )}
                      {signal && signal.changePct !== undefined && signal.changePct !== null && (
                        <span
                          className="text-xs font-mono"
                          style={getPriceChangeStyle(signal.changePct)}
                        >
                          {formatChangePct(signal.changePct)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          )}
        </div>

        {/* 右侧：情绪指标 - 填满格子高度，消除与 STRATEGY POINTS 之间的空隙 */}
        <div className="flex flex-col self-stretch min-h-full">
          <Card variant="bordered" padding="md" className="home-panel-card !overflow-visible flex-1 flex flex-col min-h-0">
            <div className="text-center flex-1 flex flex-col justify-center">
              <h3 className="mb-5 text-sm font-medium tracking-wide text-foreground">{text.marketSentiment}</h3>
              <ScoreGauge score={summary.sentimentScore} size="lg" language={reportLanguage} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
