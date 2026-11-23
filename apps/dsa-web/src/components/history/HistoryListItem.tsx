import type React from 'react';
import { Badge } from '../common';
import type { HistoryItem } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel } from '../../utils/marketPhase';
import { truncateStockName } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface HistoryListItemProps {
  item: HistoryItem;
  isViewing: boolean; // Indicates if this report is currently being viewed in the right panel
  isChecked: boolean; // Indicates if the checkbox is checked for bulk operations
  isDeleting: boolean;
  onToggleChecked: (recordId: number) => void;
  onClick: (recordId: number) => void;
}

export const HistoryListItem: React.FC<HistoryListItemProps> = ({
  item,
  isViewing,
  isChecked,
  isDeleting,
  onToggleChecked,
  onClick,
}) => {
  const { language, t } = useUiLanguage();
  const sentimentColor = item.sentimentScore !== undefined ? getSentimentColor(item.sentimentScore) : null;
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
    <div className="flex items-start gap-2 group">
      <div className="pt-5">
        <input
          type="checkbox"
          checked={isChecked}
          onChange={() => onToggleChecked(item.id)}
          disabled={isDeleting}
          className="h-3.5 w-3.5 cursor-pointer rounded border-subtle-hover bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
        />
      </div>
      <button
        type="button"
        onClick={() => onClick(item.id)}
        aria-label={t('history.itemAria', { name: stockName, code: item.stockCode })}
        className={`home-history-item w-full min-w-0 flex-1 text-left p-2.5 group/item ${
          isViewing ? 'home-history-item-selected' : ''
        }`}
      >
        <div className="relative z-10 flex items-center gap-2.5">
          {sentimentColor && (
            <div
              className="w-1 h-8 rounded-full flex-shrink-0"
              style={{
                backgroundColor: sentimentColor,
                boxShadow: `0 0 10px ${sentimentColor}40`,
              }}
            />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <span className="block w-full truncate text-sm font-semibold text-foreground tracking-tight">
                  {truncateStockName(stockName)}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-1" data-testid="history-card-actions">
                {sentimentColor && (
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
                    {operationLabel} {item.sentimentScore}
                  </Badge>
                )}
              </div>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2" data-testid="history-card-meta">
              <span className="text-[11px] text-secondary-text font-mono">
                {item.stockCode}
              </span>
              <span className="w-1 h-1 rounded-full bg-subtle-hover" />
              <span className="text-[11px] text-muted-text">
                {formatDateTime(item.createdAt)}
              </span>
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
    </div>
  );
};
