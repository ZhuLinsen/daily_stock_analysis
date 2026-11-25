import type React from 'react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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

/** 各日期列表上次滚动到的位置（issue #1661 OR-COR-278fd558）。 */
interface DailyHistoryScrollMemory {
  current: Record<string, number>;
}

interface DailyHistoryPanelProps {
  selectedRecordId?: number | null;
  onSelectRecord: (recordId: number) => void;
  /**
   * 受控日期（issue #1661 OR-COR-278fd558）：首页历史抽屉在手机上随行点击关闭
   * 卸载，日期状态必须寄存在不卸载的父级（HomePage），重开抽屉才不回跳今天。
   * 缺省时退回组件内部状态（独立使用/测试）。
   */
  dateKey?: string;
  onDateKeyChange?: (dateKey: string) => void;
  /**
   * 滚动位置存储（issue #1661 OR-COR-278fd558）：与日期同理，抽屉卸载会连带丢掉
   * 列表的滚动位置，须寄存在不卸载的父级（HomePage），重开抽屉才能回到原位置。
   * 隐藏的桌面实例与抽屉实例共享同一份。缺省时退回组件内部存储（独立使用/测试）。
   */
  scrollMemory?: DailyHistoryScrollMemory;
  /**
   * 最近一份大盘复盘入口（OR-COM-91cc3feb）：旧个股栏把 MARKET 行注入历史区，
   * 换成按日列表后由 HomePage 传入最新复盘，保住「重开已保存复盘」的入口。
   */
  marketReviewEntry?: { id: number; name: string; createdAt?: string } | null;
  className?: string;
}

/** 单页条数：面板自动翻页取满 total（OR-COR-899887df），仅超长日才发后续请求 */
const DAILY_PAGE_SIZE = 100;
/** 防御上限：超过该页数视为异常响应，停止翻页避免死循环 */
const DAILY_MAX_PAGES = 50;
/**
 * 自动翻页重取上限（OR-COR-e9d99614）：后端每次请求重新排序并按偏移量切页，翻页
 * 期间有新报告写入/删除时页边界会移动（后一页重复前一页末尾的行、新报告无入口）。
 * 检测到边界移动即从第 1 页重取；持续写入时收尾于按记录去重后的结果。
 */
const DAILY_MAX_RESYNC_ATTEMPTS = 2;

/**
 * 第 1 页快照令牌（OR-COR-e9d99614 总数恒定的替换竞态）：按序拼接的记录 ID 串。
 * 翻页期间「删一条 + 新增一条」不改变 total，只有首页内容（ID 序列）能证明
 * 各页是否取自同一快照。
 */
const dailyFirstPageToken = (items: DailyHistoryItem[]): string =>
  items.map((item) => item.id).join(',');

/**
 * 首页历史区「日期回看」面板（issue #1661，G1a 方案一）。
 * 日期口径 = 北京时间（Asia/Shanghai）的分析生成日期；同股同日多份取最新一份
 * （analysis_count 标注份数，逐份下钻留待下期）；列表按日期 key 重挂载 +
 * 请求序号/AbortController 守卫竞态；只读，无删除/写操作入口。
 */
const DailyHistoryPanel: React.FC<DailyHistoryPanelProps> = ({
  selectedRecordId = null,
  onSelectRecord,
  dateKey: controlledDateKey,
  onDateKeyChange,
  scrollMemory: controlledScrollMemory,
  marketReviewEntry = null,
  className = '',
}) => {
  const { t } = useUiLanguage();
  const [internalDateKey, setInternalDateKey] = useState(() => getTodayInShanghai());
  const dateKey = controlledDateKey ?? internalDateKey;
  const internalScrollMemory = useRef<Record<string, number>>({});
  const scrollMemory = controlledScrollMemory ?? internalScrollMemory;

  const changeDate = (nextDateKey: string) => {
    setInternalDateKey(nextDateKey);
    onDateKeyChange?.(nextDateKey);
  };

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
            if (event.target.value) changeDate(event.target.value);
          }}
          aria-label={t('historyDaily.dateLabel')}
          className="h-8 rounded-lg border border-subtle bg-base/40 px-2 text-xs text-foreground focus:border-primary/50 focus:outline-none"
        />
      </div>
      <p className="text-[10px] leading-snug text-muted-text">{t('historyDaily.tzHint')}</p>
      {marketReviewEntry ? (
        <button
          type="button"
          data-testid={`daily-history-market-entry-${marketReviewEntry.id}`}
          aria-pressed={selectedRecordId === marketReviewEntry.id}
          className={`home-subpanel flex min-w-0 w-full cursor-pointer items-center gap-2 px-3 py-2 text-left transition-colors ${
            selectedRecordId === marketReviewEntry.id ? 'home-subpanel-selected' : ''
          }`}
          onClick={() => onSelectRecord(marketReviewEntry.id)}
        >
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {marketReviewEntry.name}
          </span>
          {marketReviewEntry.createdAt ? (
            <span className="shrink-0 font-mono text-[11px] text-muted-text">
              {marketReviewEntry.createdAt.slice(0, 10)}
            </span>
          ) : null}
        </button>
      ) : null}
      <DailyHistoryList
        // 按日期 key 重挂载：状态初始化即重置，旧日期的迟到响应落在新挂载之外，天然隔离
        key={dateKey}
        dateKey={dateKey}
        selectedRecordId={selectedRecordId}
        onSelectRecord={onSelectRecord}
        scrollMemory={scrollMemory}
        className="flex-1"
      />
    </div>
  );
};

const DailyHistoryList: React.FC<{
  dateKey: string;
  selectedRecordId?: number | null;
  onSelectRecord: (recordId: number) => void;
  scrollMemory: DailyHistoryScrollMemory;
  className?: string;
}> = ({ dateKey, selectedRecordId = null, onSelectRecord, scrollMemory, className = '' }) => {
  const { t } = useUiLanguage();
  // 初始态即重置态（配合按日期 key 重挂载）
  const [items, setItems] = useState<DailyHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestSeqRef = useRef(0);
  const listRef = useRef<HTMLDivElement>(null);
  const didRestoreScrollRef = useRef(false);
  const didScrollToSelectedRef = useRef(false);

  useEffect(() => {
    if (!dateKey) {
      return undefined;
    }
    const seq = ++requestSeqRef.current;
    const controller = new AbortController();
    let active = true;

    // 自动翻页取满当日全集（OR-COR-899887df/adc0d89a）：面板展示 total 只股票，
    // 就必须提供 total 个报告入口，不能停留在默认第一页
    const load = async () => {
      try {
        // 有界重取（OR-COR-e9d99614）：后端按偏移量切页，翻页期间有新报告写入/删除
        // 会让页边界移动。各页 total 不一致、或按记录去重后不足 total，都说明拼起来
        // 的不是同一快照——从第 1 页重取，而不是把偏移过的页直接拼上去。
        // 总数恒定的替换（OR-COR-e9d99614）：翻页期间「删一条 + 新增一条」不改变
        // total——新报告按时间倒序排到首位，落在已取过的第 1 页区间（不会再被
        // 请求），第 2 页顺移补上一条旧记录，去重后恰好凑满 total，拼出的却是
        // 撕裂快照：已删记录仍可点击、新股票无入口。因此多页加载在完成前重取第
        // 1 页比对快照令牌（首页 ID 序列签名）：内容漂移即从第 1 页重取（有界，
        // 与 boundaryMoved 同一重试上限）；首页一致即通过——稳态只多一次首页
        // 请求且仅发生在多页加载，单页响应本身原子一致无需校验，不会无限重取。
        for (let attempt = 0; ; attempt += 1) {
          const collectedById = new Map<number, DailyHistoryItem>();
          let snapshotTotal: number | null = null;
          let firstPageToken: string | null = null;
          let boundaryMoved = false;
          let page = 1;
          while (true) {
            const response = await historyApi.getDaily(dateKey, {
              signal: controller.signal,
              page,
              limit: DAILY_PAGE_SIZE,
            });
            if (!active || seq !== requestSeqRef.current) return;
            if (snapshotTotal === null) {
              snapshotTotal = response.total;
              firstPageToken = dailyFirstPageToken(response.items);
            } else if (response.total !== snapshotTotal) {
              boundaryMoved = true;
              break;
            }
            // 按记录去重：页边界移动时后一页会重复前一页末尾的行
            for (const item of response.items) {
              if (!collectedById.has(item.id)) {
                collectedById.set(item.id, item);
              }
            }
            if (response.items.length === 0 || collectedById.size >= snapshotTotal || page >= DAILY_MAX_PAGES) {
              break;
            }
            page += 1;
          }
          const collected = Array.from(collectedById.values());
          let complete = !boundaryMoved && (
            page >= DAILY_MAX_PAGES || collected.length >= (snapshotTotal ?? 0)
          );
          if (complete && page > 1 && attempt < DAILY_MAX_RESYNC_ATTEMPTS && firstPageToken !== null) {
            const recheck = await historyApi.getDaily(dateKey, {
              signal: controller.signal,
              page: 1,
              limit: DAILY_PAGE_SIZE,
            });
            if (!active || seq !== requestSeqRef.current) return;
            if (recheck.total !== snapshotTotal || dailyFirstPageToken(recheck.items) !== firstPageToken) {
              complete = false;
            }
          }
          if (complete || attempt >= DAILY_MAX_RESYNC_ATTEMPTS) {
            setItems(collected);
            // 计数标签与实际展示的行数一致（去重后不足 total 时不虚报）
            setTotal(collected.length);
            setIsLoading(false);
            return;
          }
        }
      } catch {
        if (!active || seq !== requestSeqRef.current) return;
        setItems([]);
        setTotal(0);
        setLoadFailed(true);
        setIsLoading(false);
      }
    };
    void load();

    return () => {
      active = false;
      controller.abort();
    };
  }, [dateKey]);

  // 重开抽屉/换日期重挂载后，回到该日期上次滚动到的位置（OR-COR-278fd558）。手机上
  // 点行会关闭并卸载抽屉，位置由不卸载的父级存储；绘制前恢复，避免先闪一下顶部。
  useLayoutEffect(() => {
    if (didRestoreScrollRef.current || items.length === 0) {
      return;
    }
    const container = listRef.current;
    if (!container) {
      return;
    }
    didRestoreScrollRef.current = true;
    const rememberedScrollTop = scrollMemory.current[dateKey];
    if (rememberedScrollTop !== undefined) {
      container.scrollTop = rememberedScrollTop;
    }
  }, [items, dateKey, scrollMemory]);

  // 让当前报告所在行可见（OR-COR-278fd558 的滚动定位部分）。行查找限定在本列表容器
  // 内：手机上隐藏的桌面实例与新挂载的抽屉实例在 DOM 中并存且桌面在前，全局
  // document.querySelector 会先命中桌面那份，抽屉自己的选中行反而没有滚动。
  // block: 'nearest'——行已在恢复的位置里可见时不改动滚动位置。
  useEffect(() => {
    if (didScrollToSelectedRef.current || selectedRecordId == null || items.length === 0) {
      return;
    }
    const container = listRef.current;
    if (!container) {
      return;
    }
    const selectedRow = container.querySelector<HTMLElement>(
      `[data-testid="daily-history-row-${selectedRecordId}"]`,
    );
    if (selectedRow && typeof selectedRow.scrollIntoView === 'function') {
      didScrollToSelectedRef.current = true;
      selectedRow.scrollIntoView({ block: 'nearest' });
    }
  }, [items, selectedRecordId]);

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
    <div
      ref={listRef}
      data-testid="daily-history-list"
      className={`min-h-0 space-y-1.5 overflow-y-auto ${className}`}
      onScroll={(event) => {
        scrollMemory.current[dateKey] = event.currentTarget.scrollTop;
      }}
    >
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
        const isSelected = selectedRecordId === item.id;
        return (
          <button
            key={`${item.code}-${item.id}`}
            type="button"
            data-testid={`daily-history-row-${item.id}`}
            aria-pressed={isSelected}
            aria-label={t('history.itemAria', { name: stockName, code: item.code })}
            className={`home-subpanel flex min-w-0 w-full cursor-pointer items-center px-3 py-2 text-left transition-colors ${
              // 选中态用非分层专用类：Tailwind 分层工具类会被 .home-subpanel 的
              // 同属性非分层规则覆盖（OR-COR-3a68c9f3）
              isSelected ? 'home-subpanel-selected' : ''
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
