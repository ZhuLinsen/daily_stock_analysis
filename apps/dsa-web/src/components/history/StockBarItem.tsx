import type React from 'react';
import { Badge, Button } from '../common';
import type { StockBarItem as StockBarItemType } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel } from '../../utils/marketPhase';
import { truncateStockName } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface StockBarItemProps {
  item: StockBarItemType;
  isViewing: boolean;
  onClick: (recordId: number) => void;
  onDelete?: (stockCode: string) => void;
  isDeleting?: boolean;
  isMarketReview?: boolean;
}

export const StockBarItemComponent: React.FC<StockBarItemProps> = ({
  item,
  isViewing,
  onClick,
  onDelete,
  isDeleting = false,
  isMarketReview = false,
}) => {
  const { language, t } = useUiLanguage();
  const sentimentScore = typeof item.sentimentScore === 'number' ? item.sentimentScore : null;
  const sentimentColor = sentimentScore !== null ? getSentimentColor(sentimentScore) : null;
  const stockName = item.stockName || item.stockCode;
  const actionLabels = buildDecisionActionLabelMap(t);
  const operationLabel = getDecisionActionLabel(
    item.action,
    item.actionLabel,
    item.operationAdvice,
    t('history.sentiment'),
    actionLabels,
  );
  const phaseLabel = getMarketPhaseSummaryLabel(item.marketPhaseSummary, language)
    ?.replace('市场阶段: ', '')
    .replace('市场阶段：', '')
    .replace('Market phase: ', '');

  return (
    <button
      type="button"
      onClick={() => onClick(item.id)}
      aria-label={t('history.itemAria', { name: stockName, code: item.stockCode })}
      className={`home-history-item w-full min-w-0 flex-1 text-left p-2.5 group/item ${
        isViewing ? 'home-history-item-selected' : ''
      }`}
    >
      <div className="relative z-10 flex items-center gap-2.5">
        {isMarketReview ? (
          <div className="w-1 h-8 rounded-full flex-shrink-0 bg-amber-400" style={{ boxShadow: '0 0 10px rgba(251,191,36,0.4)' }} />
        ) : sentimentColor ? (
          <div
            className="w-1 h-8 rounded-full flex-shrink-0"
            style={{
              backgroundColor: sentimentColor,
              boxShadow: `0 0 10px ${sentimentColor}40`,
            }}
          />
        ) : (
          <div className="w-1 h-8 rounded-full flex-shrink-0 bg-subtle" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <span className="block w-full truncate text-sm font-semibold text-foreground tracking-tight">
                {truncateStockName(stockName)}
              </span>
            </div>
            <div className="flex items-center gap-1 shrink-0" data-testid="history-card-actions">
              {isMarketReview ? (
                <Badge
                  variant="default"
                  size="sm"
                  className="shrink-0 shadow-none text-[10px] font-semibold leading-none"
                  style={{
                    color: '#f59e0b',
                    borderColor: 'rgba(245,158,11,0.3)',
                    backgroundColor: 'rgba(245,158,11,0.1)',
                  }}
                >
                  {t('stockBar.market')}
                </Badge>
              ) : sentimentColor ? (
                <Badge
                  variant="default"
                  size="sm"
                  className="home-history-sentiment-badge shrink-0 shadow-none text-[11px] font-semibold leading-none transition-opacity duration-200"
                  style={{
                    color: sentimentColor,
                    borderColor: `${sentimentColor}30`,
                    backgroundColor: `${sentimentColor}10`,
                  }}
                >
                  {operationLabel} {sentimentScore}
                </Badge>
              ) : null}
              {onDelete && (
                <Button
                  variant="ghost"
                  size="xsm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(item.stockCode);
                  }}
                  disabled={isDeleting}
                  className="opacity-0 group-hover/item:opacity-100 transition-opacity h-6 w-6 p-0 flex items-center justify-center"
                  aria-label={t('history.deleteRecord', { name: item.stockName || item.stockCode })}
                >
                  <svg className="h-3.5 w-3.5 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </Button>
              )}
            </div>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2" data-testid="history-card-meta">
            <span className="text-[11px] text-secondary-text font-mono">
              {item.stockCode}
            </span>
            {item.lastAnalysisTime && (
              <>
                <span className="w-1 h-1 rounded-full bg-subtle-hover" />
                <span className="text-[11px] text-muted-text">
                  {formatDateTime(item.lastAnalysisTime)}
                </span>
              </>
            )}
            {item.analysisCount > 1 && (
              <>
                <span className="w-1 h-1 rounded-full bg-subtle-hover" />
                <span className="text-[10px] text-muted-text">
                  {t('history.analysisCount', { count: item.analysisCount })}
                </span>
              </>
            )}
            {phaseLabel ? (
              <>
                <span className="w-1 h-1 rounded-full bg-subtle-hover" />
                <Badge variant="default" size="sm" className="shrink-0 shadow-none text-[10px] leading-none">
                  {phaseLabel}
                </Badge>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </button>
  );
};
