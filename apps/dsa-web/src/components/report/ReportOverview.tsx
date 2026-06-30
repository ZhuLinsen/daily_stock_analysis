import type React from 'react';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportSummary as ReportSummaryType,
} from '../../types/analysis';
import { Badge, Button, Card, ScoreGauge } from '../common';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel, getPartialBarLabel } from '../../utils/marketPhase';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  details?: ReportDetailsType;
  isHistory?: boolean;
  watchlist?: {
    isInWatchlist: (code: string) => boolean;
    onToggle: (code: string) => void;
    isActioning: boolean;
    actionMessage: string | null;
  };
}

type BoardStatus = 'leading' | 'lagging';

type BoardSignal = {
  status: BoardStatus;
  changePct?: number;
};

type BoardSignalMaps = {
  sectors: Map<string, BoardSignal>;
  concepts: Map<string, BoardSignal>;
};

type PreparedBoard = {
  key: string;
  name: string;
  signal?: BoardSignal;
};

const normalizeBoardName = (value?: string): string =>
  (value || '').trim().replace(/\s+/g, ' ');

const normalizeBoardType = (value?: string): 'sector' | 'concept' | null => {
  const normalized = (value || '').trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (['行业', '行业板块', 'industry', 'sector'].includes(normalized)) {
    return 'sector';
  }
  if (['概念', '概念板块', '题材', 'concept', 'theme'].includes(normalized)) {
    return 'concept';
  }
  return null;
};

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

const buildRankingSignalMap = (rankings?: ReportDetailsType['sectorRankings']): Map<string, BoardSignal> => {
  const signalMap = new Map<string, BoardSignal>();
  const topBoards = Array.isArray(rankings?.top) ? rankings.top : [];
  const bottomBoards = Array.isArray(rankings?.bottom) ? rankings.bottom : [];

  topBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'leading',
      changePct,
    });
  });

  bottomBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    const changePct = coerceFiniteNumber(item?.changePct);
    if (!normalizedName || changePct === undefined) {
      return;
    }
    signalMap.set(normalizedName, {
      status: 'lagging',
      changePct,
    });
  });

  return signalMap;
};

const buildBoardSignalMaps = (details?: ReportDetailsType): BoardSignalMaps => ({
  sectors: buildRankingSignalMap(details?.sectorRankings),
  concepts: buildRankingSignalMap(details?.conceptRankings),
});

const resolveBoardSignal = (
  board: { name?: string; type?: string },
  signalMaps: BoardSignalMaps,
): BoardSignal | undefined => {
  const boardName = normalizeBoardName(board.name);
  if (!boardName) {
    return undefined;
  }
  const boardType = normalizeBoardType(board.type);
  if (boardType === 'sector') {
    return signalMaps.sectors.get(boardName);
  }
  if (boardType === 'concept') {
    return signalMaps.concepts.get(boardName);
  }
  const sectorSignal = signalMaps.sectors.get(boardName);
  const conceptSignal = signalMaps.concepts.get(boardName);
  if (sectorSignal && !conceptSignal) {
    return sectorSignal;
  }
  if (conceptSignal && !sectorSignal) {
    return conceptSignal;
  }
  return undefined;
};

const buildPreparedRelatedBoards = (
  boards: ReportDetailsType['belongBoards'],
  signalMaps: BoardSignalMaps,
): PreparedBoard[] => {
  if (!Array.isArray(boards)) {
    return [];
  }

  return boards.reduce<PreparedBoard[]>((preparedBoards, board, index) => {
    const boardName = normalizeBoardName(board?.name);
    if (!boardName) {
      return preparedBoards;
    }
    preparedBoards.push({
      key: `${boardName}-${board?.code || index}`,
      name: boardName,
      signal: resolveBoardSignal(board, signalMaps),
    });
    return preparedBoards;
  }, []);
};

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  details,
  watchlist,
}) => {
  const { t } = useUiLanguage();
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const marketPhaseLabel = getMarketPhaseSummaryLabel(meta.marketPhaseSummary, reportLanguage);
  const partialBarLabel = meta.marketPhaseSummary?.isPartialBar === true
    ? getPartialBarLabel(reportLanguage)
    : null;
  const relatedBoards = (Array.isArray(details?.belongBoards) ? details.belongBoards : [])
    .filter((board) => normalizeBoardName(board?.name).length > 0);
  const boardSignals = buildBoardSignalMaps(details);
  const preparedRelatedBoards = buildPreparedRelatedBoards(relatedBoards, boardSignals);

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

  const getBoardStatusVariant = (status: BoardStatus): 'success' | 'danger' => {
    if (status === 'leading') {
      return 'success';
    }
    return 'danger';
  };

  const renderBoardChip = (board: PreparedBoard) => (
    <div
      key={board.key}
      className="inline-flex shrink-0 items-center gap-2 text-sm"
    >
      <span className="home-accent-chip px-2 py-0.5 text-xs font-medium">
        {board.name}
      </span>
      {board.signal && (
        <Badge
          variant={getBoardStatusVariant(board.signal.status)}
          className="home-board-status-badge shadow-none"
        >
          {getBoardStatusLabel(board.signal.status)}
        </Badge>
      )}
      {board.signal && board.signal.changePct !== undefined && board.signal.changePct !== null && (
        <span
          className="text-xs font-mono"
          style={getPriceChangeStyle(board.signal.changePct)}
        >
          {formatChangePct(board.signal.changePct)}
        </span>
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      {/* 主信息区 - 两列布局 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        {/* 左侧：股票信息与结论 */}
        <div className="lg:col-span-2 space-y-5">
          {/* 股票头部 */}
          <Card variant="gradient" padding="md" className="home-report-hero">
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
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  <span className="home-accent-chip px-2 py-0.5 font-mono text-xs">
                    {meta.stockCode}
                  </span>
                  {marketPhaseLabel ? (
                    <Badge variant="info" className="shrink-0 gap-1.5 shadow-none" aria-label={marketPhaseLabel}>
                      {marketPhaseLabel}
                    </Badge>
                  ) : null}
                  {partialBarLabel ? (
                    <Badge variant="warning" className="shrink-0 shadow-none" aria-label={partialBarLabel}>
                      {partialBarLabel}
                    </Badge>
                  ) : null}
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
            {/* 操作建议 */}
            <Card
              variant="bordered"
              padding="sm"
              hoverable
              className="home-panel-card home-insight-card"
              style={{ ['--home-insight-tone' as string]: 'var(--home-strategy-buy)' }}
            >
              <div className="flex items-start gap-3">
                <div className="home-insight-icon w-8 h-8 rounded-lg bg-success/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">{text.actionAdvice}</h4>
                  <p className="home-insight-body text-sm leading-6">
                    {summary.operationAdvice || text.noAdvice}
                  </p>
                </div>
              </div>
            </Card>

            {/* 趋势预测 */}
            <Card
              variant="bordered"
              padding="sm"
              hoverable
              className="home-panel-card home-insight-card"
              style={{ ['--home-insight-tone' as string]: 'var(--home-strategy-take)' }}
            >
              <div className="flex items-start gap-3">
                <div className="home-insight-icon w-8 h-8 rounded-lg bg-warning/10 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div className="space-y-1.5">
                  <h4 className="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">{text.trendPrediction}</h4>
                  <p className="home-insight-body text-sm leading-6">
                    {summary.trendPrediction || text.noPrediction}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          {preparedRelatedBoards.length > 0 && (
            <Card variant="bordered" padding="sm" className="home-panel-card min-w-0 max-w-full text-left">
              <section aria-label={text.relatedBoards} className="min-w-0 max-w-full">
                <div className="mb-3 flex min-w-0 items-baseline gap-2">
                  <span className="label-uppercase">{text.boardLinkage}</span>
                  <h3 className="mt-0.5 text-base font-semibold text-foreground">{text.relatedBoards}</h3>
                </div>

                <div className="home-related-board-list flex min-h-6 w-full min-w-0 max-w-full flex-nowrap items-center gap-2 overflow-x-auto overscroll-x-contain touch-pan-x pb-1">
                  {preparedRelatedBoards.map(renderBoardChip)}
                </div>
              </section>
            </Card>
          )}
        </div>

        {/* 右侧：情绪指标 / 自选操作 */}
        <div className="flex flex-col space-y-4">
          {watchlist && meta.reportType !== 'market_review' && (
            <Card variant="bordered" padding="sm" className="home-panel-card">
              <div className="text-center space-y-3">
                <span className="label-uppercase">{t('report.watchlist')}</span>
                <div className="text-xs text-muted-text font-mono">{meta.stockCode}</div>
                <Button
                  variant={watchlist.isInWatchlist(meta.stockCode) ? 'danger-subtle' : 'secondary'}
                  size="sm"
                  isLoading={watchlist.isActioning}
                  onClick={() => watchlist.onToggle(meta.stockCode)}
                  className="w-full text-xs"
                >
                  {watchlist.isInWatchlist(meta.stockCode) ? t('report.removeFromWatchlist') : t('report.addToWatchlist')}
                </Button>
                {watchlist.actionMessage && (
                  <p className="text-[11px] text-secondary-text animate-in fade-in">{watchlist.actionMessage}</p>
                )}
              </div>
            </Card>
          )}
          <Card variant="bordered" padding="md" className="home-panel-card home-rail-card !overflow-visible">
            <div className="text-center">
              <h3 className="mb-5 text-sm font-medium tracking-wide text-foreground">{text.marketSentiment}</h3>
              <ScoreGauge score={summary.sentimentScore} size="lg" language={reportLanguage} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
