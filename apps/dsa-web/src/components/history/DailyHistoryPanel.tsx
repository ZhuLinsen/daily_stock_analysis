import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { History } from 'lucide-react';
import { historyApi } from '../../api/history';
import { Badge } from '../common';
import { DashboardStateBlock } from '../dashboard';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { DailyHistoryItem } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { getTodayInShanghai } from '../../utils/format';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { truncateStockName } from '../../utils/stockName';

interface DailyHistoryPanelProps {
  selectedRecordId?: number | null;
  onSelectRecord: (recordId: number) => void;
  className?: string;
}

/**
 * 首页历史区「日期回看」面板（issue #1661，G1a 方案一）。
 * 日期口径 = 北京时间（Asia/Shanghai）的分析生成日期；同股同日多份取最新一份
 * （analysis_count 标注份数，逐份下钻留待下期）；列表按日期 key 重挂载 +
 * 请求序号/AbortController 守卫竞态；只读，无删除/写操作入口。
 */
const DailyHistoryPanel: React.FC<DailyHistoryPanelProps> = ({
  selectedRecordId = null,
  onSelectRecord,
  className = '',
}) => {
  const { t } = useUiLanguage();
  const [dateKey, setDateKey] = useState(() => getTodayInShanghai());

  return (
    <div data-testid="daily-history-panel" className={`flex min-h-0 flex-col gap-2 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <label className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-secondary-text">
          <History className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
          {t('historyDaily.dateLabel')}
        </label>
        <input
          type="date"
          data-testid="daily-history-date-input"
          value={dateKey}
          onChange={(event) => {
            if (event.target.value) setDateKey(event.target.value);
          }}
          aria-label={t('historyDaily.dateLabel')}
          className="h-8 rounded-lg border border-subtle bg-base/40 px-2 text-xs text-foreground focus:border-primary/50 focus:outline-none"
        />
      </div>
      <p className="text-[10px] leading-snug text-muted-text">{t('historyDaily.tzHint')}</p>
      <DailyHistoryList
        // 按日期 key 重挂载：状态初始化即重置，旧日期的迟到响应落在新挂载之外，天然隔离
        key={dateKey}
        dateKey={dateKey}
        selectedRecordId={selectedRecordId}
        onSelectRecord={onSelectRecord}
        className="flex-1"
      />
    </div>
  );
};

const DailyHistoryList: React.FC<{
  dateKey: string;
  selectedRecordId?: number | null;
  onSelectRecord: (recordId: number) => void;
  className?: string;
}> = ({ dateKey, selectedRecordId = null, onSelectRecord, className = '' }) => {
  const { t } = useUiLanguage();
  // 初始态即重置态（配合按日期 key 重挂载）
  const [items, setItems] = useState<DailyHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    if (!dateKey) {
      return undefined;
    }
    const seq = ++requestSeqRef.current;
    const controller = new AbortController();
    let active = true;

    void historyApi
      .getDaily(dateKey, { signal: controller.signal })
      .then((response) => {
        if (!active || seq !== requestSeqRef.current) return;
        setItems(response.items);
        setTotal(response.total);
        setIsLoading(false);
      })
      .catch(() => {
        if (!active || seq !== requestSeqRef.current) return;
        setItems([]);
        setTotal(0);
        setLoadFailed(true);
        setIsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [dateKey]);

  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);

  if (isLoading) {
    return <DashboardStateBlock loading compact title={t('common.loading')} className={className} />;
  }
  if (loadFailed || total === 0) {
    const testid = loadFailed ? 'daily-history-load-error' : 'daily-history-empty';
    const title = loadFailed ? t('historyDaily.loadErrorTitle') : t('historyDaily.emptyTitle');
    const description = loadFailed
      ? t('historyDaily.loadErrorDescription')
      : t('historyDaily.emptyDescription');
    return (
      <div data-testid={testid} className={className}>
        <DashboardStateBlock compact title={title} description={description} />
      </div>
    );
  }

  return (
    <div className={`min-h-0 space-y-1.5 overflow-y-auto ${className}`} data-testid="daily-history-list">
      <p className="text-[11px] text-muted-text">{t('common.itemsCount', { count: total })}</p>
      {items.map((item) => {
        const stockName = item.name || item.code;
        const score = typeof item.sentimentScore === 'number' ? item.sentimentScore : null;
        const color = score !== null ? getSentimentColor(score) : null;
        const operationLabel = getDecisionActionLabel(
          item.action,
          item.actionLabel,
          item.operationAdvice,
          t('history.sentiment'),
          actionLabels,
        );
        return (
          <button
            key={`${item.code}-${item.id}`}
            type="button"
            data-testid={`daily-history-row-${item.id}`}
            aria-pressed={selectedRecordId === item.id}
            aria-label={t('history.itemAria', { name: stockName, code: item.code })}
            className={`home-subpanel flex min-w-0 w-full cursor-pointer items-center px-3 py-2 text-left transition-colors ${
              selectedRecordId === item.id
                ? 'border-primary/35 bg-primary/10'
                : 'hover:border-subtle-hover hover:bg-base/65'
            }`}
            onClick={() => onSelectRecord(item.id)}
          >
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                  {truncateStockName(stockName)}
                </span>
                <Badge
                  variant="default"
                  size="sm"
                  className={`shrink-0 text-[10px] font-semibold leading-none shadow-none ${
                    item.isLatest
                      ? 'border-success/30 bg-success/10 text-success'
                      : 'border-warning/30 bg-warning/10 text-warning'
                  }`}
                >
                  {item.isLatest ? t('historyDaily.isLatest') : t('historyDaily.superseded')}
                </Badge>
                {color ? (
                  <Badge
                    variant="default"
                    size="sm"
                    className="shrink-0 shadow-none text-[11px] font-semibold leading-none"
                    style={{ color, borderColor: `${color}30`, backgroundColor: `${color}10` }}
                  >
                    {operationLabel} {score}
                  </Badge>
                ) : null}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-text">
                <span className="font-mono">{item.code}</span>
                {/*
                  次级信息（维护者 spec 1：分析时间、趋势放次级位置）：字段缺失自适应精简。
                */}
                {[
                  item.createdAt ? item.createdAt.slice(11, 16) : '',
                  item.trendPrediction || '',
                  item.analysisCount > 1 ? t('historyDaily.dayCount', { count: item.analysisCount }) : '',
                ]
                  .filter(Boolean)
                  .map((meta, metaIndex) => (
                    <span key={`${item.id}-${metaIndex}`} className="min-w-0 truncate">
                      {meta}
                    </span>
                  ))}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
};

export default DailyHistoryPanel;
