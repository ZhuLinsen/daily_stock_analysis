import type { UiLanguage } from '../i18n/uiText';

export interface BacktestQuantText {
  panelTitle: string;
  portfolioScope: string;
  stockScopePrefix: string;
  collapsePanel: string;
  expandPanel: string;
  cumulativeReturn: string;
  profitFactor: string;
  expectancyPerTrade: string;
  payoffRatio: string;
  sharpeAndSortino: string;
  maxDrawdownAndCalmar: string;
  avgWinLoss: string;
  bestWorstTrade: string;
  streakRecord: string;
  sampleTrades: string;
  equityCurveTitle: string;
  equityCurveStart: string;
  equityCurveLatest: string;
  exitBreakdownTitle: string;
  adviceBreakdownTitle: string;
  legacyMetricsHint: string;
  outcomeFilterLabel: string;
  filterAll: string;
  filterWin: string;
  filterLoss: string;
  filterNeutral: string;
  sortLabel: string;
  sortDefault: string;
  sortSimDesc: string;
  sortSimAsc: string;
  sortStockDesc: string;
  noFilteredRows: string;
  resetLocalFilter: string;
  expandDetailAria: string;
  collapseDetailAria: string;
  replayTitle: string;
  simEntryExit: string;
  exitReason: string;
  simReturn: string;
  riskTargets: string;
  firstHitDetail: string;
  excursionRange: string;
  mfeMaeLabel: string;
  openReportAction: string;
  daysUnit: string;
  streakUnit: string;
  tradesCountUnit: string;
  equityCurveWindowHint: string;
  adviceLabels: Record<string, string>;
  exitReasons: Record<string, string>;
}

export const BACKTEST_QUANT_TEXT: Record<UiLanguage, BacktestQuantText> = {
  zh: {
    panelTitle: '量化风险绩效与模拟净值',
    portfolioScope: '组合总览',
    stockScopePrefix: '单股视角',
    collapsePanel: '收起量化看板',
    expandPanel: '展开量化看板',
    cumulativeReturn: '累计模拟收益',
    profitFactor: '获利因子 (PF)',
    expectancyPerTrade: '单次期望收益',
    payoffRatio: '平均赔率 (盈/亏)',
    sharpeAndSortino: '夏普 / 索提诺',
    maxDrawdownAndCalmar: '最大回撤 / 卡玛',
    avgWinLoss: '均盈 / 均亏',
    bestWorstTrade: '单次极值 (最优/最差)',
    streakRecord: '连胜 / 连败极值',
    sampleTrades: '有效样本',
    equityCurveTitle: '策略顺序模拟净值曲线',
    equityCurveStart: '起点 0.0%',
    equityCurveLatest: '最新',
    exitBreakdownTitle: '模拟离场分布',
    adviceBreakdownTitle: '按操作建议胜率分布',
    legacyMetricsHint: '当前汇总缺少扩展量化指标，勾选“强制重跑”可重算完整风险比率与净值曲线。',
    outcomeFilterLabel: '当前页模拟盈亏筛选',
    filterAll: '全部',
    filterWin: '仅盈利',
    filterLoss: '仅亏损',
    filterNeutral: '仅中性',
    sortLabel: '排序',
    sortDefault: '默认顺序',
    sortSimDesc: '模拟收益 ↓',
    sortSimAsc: '模拟收益 ↑',
    sortStockDesc: '窗口涨幅 ↓',
    noFilteredRows: '当前页没有匹配筛选条件的回测记录',
    resetLocalFilter: '重置筛选',
    expandDetailAria: '展开回测交易回放详情',
    collapseDetailAria: '收起回测交易回放详情',
    replayTitle: '单笔回测执行与波动回放',
    simEntryExit: '模拟入场 / 离场价',
    exitReason: '离场触发机制',
    simReturn: '模拟策略收益',
    riskTargets: '止损 / 止盈位',
    firstHitDetail: '首次触发与耗时',
    excursionRange: '窗口价格区间 (高 / 低)',
    mfeMaeLabel: '最大顺势浮盈 / 最大逆势回撤',
    openReportAction: '查看分析工作台',
    daysUnit: '第 {days} 交易日',
    streakUnit: '{wins}连胜 / {losses}连败',
    tradesCountUnit: '{count} 笔 ({active} 做多)',
    exitReasons: {
      take_profit: '触发止盈',
      takeProfit: '触发止盈',
      stop_loss: '触发止损',
      stopLoss: '触发止损',
      window_end: '窗口期满平仓',
      windowEnd: '窗口期满平仓',
      ambiguous_stop_loss: '同日双触(按止损)',
      ambiguousStopLoss: '同日双触(按止损)',
      cash: '观望空仓',
      invalid_targets: '目标位失效',
      invalidTargets: '目标位失效',
      neither: '未触发目标',
    },
    equityCurveWindowHint: '展示最近 {count} 笔（起始于 #{start}，未从 0% 原点绘制）',
    adviceLabels: {
      强烈买入: '强烈买入',
      买入: '买入',
      加仓: '加仓',
      持有: '持有',
      观望: '观望',
      减仓: '减仓',
      卖出: '卖出',
      强烈卖出: '强烈卖出',
    },
  },
  en: {
    panelTitle: 'Quant Risk Telemetry & Equity Curve',
    portfolioScope: 'Portfolio Scope',
    stockScopePrefix: 'Stock Scope',
    collapsePanel: 'Collapse quant panel',
    expandPanel: 'Expand quant panel',
    cumulativeReturn: 'Cumulative Sim Return',
    profitFactor: 'Profit Factor',
    expectancyPerTrade: 'Expectancy / Trade',
    payoffRatio: 'Payoff Ratio',
    sharpeAndSortino: 'Sharpe / Sortino',
    maxDrawdownAndCalmar: 'Max DD / Calmar',
    avgWinLoss: 'Avg Win / Avg Loss',
    bestWorstTrade: 'Best / Worst Trade',
    streakRecord: 'Max Win / Loss Streak',
    sampleTrades: 'Sample Size',
    equityCurveTitle: 'Chronological Simulated Equity Curve',
    equityCurveStart: 'Start 0.0%',
    equityCurveLatest: 'Latest',
    exitBreakdownTitle: 'Exit Mechanism Breakdown',
    adviceBreakdownTitle: 'Win Rate by Advice Category',
    legacyMetricsHint: 'Extended quant telemetry is unavailable for this cached summary. Enable "Force rerun" to recompute full risk ratios and the equity curve.',
    outcomeFilterLabel: 'Page sim P&L filter',
    filterAll: 'All',
    filterWin: 'Wins',
    filterLoss: 'Losses',
    filterNeutral: 'Neutral',
    sortLabel: 'Sort',
    sortDefault: 'Default order',
    sortSimDesc: 'Sim Return ↓',
    sortSimAsc: 'Sim Return ↑',
    sortStockDesc: 'Window Return ↓',
    noFilteredRows: 'No rows on this page match the current outcome filter.',
    resetLocalFilter: 'Reset filter',
    expandDetailAria: 'Expand trade replay details',
    collapseDetailAria: 'Collapse trade replay details',
    replayTitle: 'Trade Execution & Window Excursion Replay',
    simEntryExit: 'Simulated Entry / Exit',
    exitReason: 'Exit Trigger',
    simReturn: 'Simulated Return',
    riskTargets: 'Stop Loss / Take Profit',
    firstHitDetail: 'First Hit & Timing',
    excursionRange: 'Window High / Low',
    mfeMaeLabel: 'Max Favorable / Adverse Excursion',
    openReportAction: 'Open in Workspace',
    daysUnit: 'Day {days}',
    streakUnit: '{wins}W / {losses}L',
    tradesCountUnit: '{count} evals ({active} long)',
    exitReasons: {
      take_profit: 'Take-Profit Hit',
      takeProfit: 'Take-Profit Hit',
      stop_loss: 'Stop-Loss Hit',
      stopLoss: 'Stop-Loss Hit',
      window_end: 'Window End Exit',
      windowEnd: 'Window End Exit',
      ambiguous_stop_loss: 'Same-Bar Hit (Stop)',
      ambiguousStopLoss: 'Same-Bar Hit (Stop)',
      cash: 'Cash / Stand Aside',
      invalid_targets: 'Invalid Targets',
      invalidTargets: 'Invalid Targets',
      neither: 'No Target Hit',
    },
    equityCurveWindowHint: 'Showing latest {count} trades (starts at #{start}, not 0% origin)',
    adviceLabels: {
      强烈买入: 'Strong Buy',
      买入: 'Buy',
      加仓: 'Add',
      持有: 'Hold',
      观望: 'Wait',
      减仓: 'Reduce',
      卖出: 'Sell',
      强烈卖出: 'Strong Sell',
    },
  },
};
