import type { UiLanguage } from '../i18n/uiText';

export interface ScreeningQuantText {
  blueprintTitle: string;
  dailyFeaturesRequired: string;
  hardFiltersLabel: string;
  filtersCount: string;
  holdingPeriodLabel: string;
  riskStyleLabel: string;
  regimeLabel: string;
  filterInputPlaceholder: string;
  filterInputAria: string;
  riskAll: string;
  riskLow: string;
  riskMedium: string;
  riskHigh: string;
  sortLabel: string;
  sortDefault: string;
  sortScoreDesc: string;
  sortLlmDesc: string;
  sortChangeDesc: string;
  sortMomentumDesc: string;
  sortValueDesc: string;
  sortStabilityDesc: string;
  sortLiquidityDesc: string;
  exportCsv: string;
  filteredCandidateCount: string;
  noFilteredCandidates: string;
  resetCandidateFilters: string;
  compareAdd: string;
  compareAdded: string;
  compareRemove: string;
  compareSelectedProgress: string;
  compareLimitHint: string;
  compareTitle: string;
  compareClear: string;
  compareMetric: string;
  compareScore: string;
  compareFactorScore: string;
  compareLlmScore: string;
  compareChange: string;
  compareRisk: string;
  riskProfiles: Record<string, string>;
  holdingPeriods: Record<string, string>;
  marketRegimes: Record<string, string>;
}

export const SCREENING_QUANT_TEXT: Record<UiLanguage, ScreeningQuantText> = {
  zh: {
    blueprintTitle: '策略因子权重与画像蓝图',
    dailyFeaturesRequired: '日K量化特征增强',
    hardFiltersLabel: '硬性过滤条件',
    filtersCount: '{count} 项风控/阈值门槛',
    holdingPeriodLabel: '持仓周期',
    riskStyleLabel: '风险风格',
    regimeLabel: '适配环境',
    filterInputPlaceholder: '搜索代码 / 名称 / 行业...',
    filterInputAria: '按代码、名称或行业过滤候选',
    riskAll: '全部风险',
    riskLow: '仅低风险',
    riskMedium: '仅中风险',
    riskHigh: '仅高风险',
    sortLabel: '候选排序',
    sortDefault: '默认综合排名',
    sortScoreDesc: '综合因子分 ↓',
    sortLlmDesc: 'AI 评分 ↓',
    sortChangeDesc: '当日涨跌幅 ↓',
    sortMomentumDesc: '动量因子 ↓',
    sortValueDesc: '估值因子 ↓',
    sortStabilityDesc: '稳定性因子 ↓',
    sortLiquidityDesc: '流动性因子 ↓',
    exportCsv: '导出 CSV',
    filteredCandidateCount: '显示 {visible} / {total} 只候选',
    noFilteredCandidates: '当前过滤条件下没有匹配的候选股',
    resetCandidateFilters: '清除过滤条件',
    compareAdd: '+ 对比',
    compareAdded: '已选对比',
    compareRemove: '移除对比',
    compareSelectedProgress: '已选 {count}/3 只对比，再选 1 只展开因子矩阵',
    compareLimitHint: '最多同时对比 3 只候选',
    compareTitle: '候选量化多因子横向对比矩阵',
    compareClear: '清空对比',
    compareMetric: '评估维度',
    compareScore: '综合得分',
    compareFactorScore: '综合因子分',
    compareLlmScore: 'AI 重排分',
    compareChange: '今日涨跌幅',
    compareRisk: '风险等级',
    riskProfiles: {
      defensive: '稳健防守',
      balanced: '攻守均衡',
      aggressive: '高弹性进攻',
    },
    holdingPeriods: {
      short_term: '短线动量',
      swing: '波段持有',
      position: '中长线配置',
      watchlist: '持续观察',
    },
    marketRegimes: {
      neutral: '均衡震荡',
      rotation: '板块轮动',
      risk_off: '防御避险',
      range_bound: '区间震荡',
      low_rate: '低利率红利',
      risk_on: '风险偏好上行',
      high_liquidity: '高流动性活跃',
      low_volatility: '低波稳健',
      trend: '趋势延续',
      oversold_repair: '超跌修复',
      high_volume: '放量突破',
    },
  },
  en: {
    blueprintTitle: 'Strategy Factor Weights & Profile Blueprint',
    dailyFeaturesRequired: 'Daily-Bar Quant Enriched',
    hardFiltersLabel: 'Hard Filters',
    filtersCount: '{count} active thresholds',
    holdingPeriodLabel: 'Horizon',
    riskStyleLabel: 'Risk Profile',
    regimeLabel: 'Regimes',
    filterInputPlaceholder: 'Filter code / name / industry...',
    filterInputAria: 'Filter candidates by code, name, or industry',
    riskAll: 'All risks',
    riskLow: 'Low risk only',
    riskMedium: 'Medium risk only',
    riskHigh: 'High risk only',
    sortLabel: 'Sort candidates',
    sortDefault: 'Default rank',
    sortScoreDesc: 'Factor Score ↓',
    sortLlmDesc: 'AI Score ↓',
    sortChangeDesc: 'Change % ↓',
    sortMomentumDesc: 'Momentum Factor ↓',
    sortValueDesc: 'Value Factor ↓',
    sortStabilityDesc: 'Stability Factor ↓',
    sortLiquidityDesc: 'Liquidity Factor ↓',
    exportCsv: 'Export CSV',
    filteredCandidateCount: 'Showing {visible} / {total} candidates',
    noFilteredCandidates: 'No candidates match the active filter criteria.',
    resetCandidateFilters: 'Reset filters',
    compareAdd: '+ Compare',
    compareAdded: 'Compared',
    compareRemove: 'Remove',
    compareSelectedProgress: '{count}/3 selected — pick 1 more to compare',
    compareLimitHint: 'Select up to 3 candidates',
    compareTitle: 'Multi-Candidate Quant Factor Comparison Matrix',
    compareClear: 'Clear compare',
    compareMetric: 'Metric / Factor',
    compareScore: 'Composite Score',
    compareFactorScore: 'Factor Score',
    compareLlmScore: 'AI Score',
    compareChange: 'Daily Change',
    compareRisk: 'Risk Level',
    riskProfiles: {
      defensive: 'Defensive',
      balanced: 'Balanced',
      aggressive: 'Aggressive',
    },
    holdingPeriods: {
      short_term: 'Short-Term',
      swing: 'Swing',
      position: 'Position',
      watchlist: 'Watchlist',
    },
    marketRegimes: {
      neutral: 'Neutral',
      rotation: 'Rotation',
      risk_off: 'Risk-Off',
      range_bound: 'Range-Bound',
      low_rate: 'Low-Rate Income',
      risk_on: 'Risk-On',
      high_liquidity: 'High Liquidity',
      low_volatility: 'Low Volatility',
      trend: 'Trending',
      oversold_repair: 'Oversold Rebound',
      high_volume: 'High Volume',
    },
  },
};
