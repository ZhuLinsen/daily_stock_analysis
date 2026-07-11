import type { DecisionAction } from '../types/analysis';

export type DecisionActionTone = 'success' | 'warning' | 'danger' | 'default';
export type DecisionActionLabelMap = Record<DecisionAction, string>;
export type DecisionActionLabelTextKey =
  | 'history.actionBuy'
  | 'history.actionAdd'
  | 'history.actionHold'
  | 'history.actionReduce'
  | 'history.actionSell'
  | 'history.actionWatch'
  | 'history.actionAvoid'
  | 'history.actionAlert';
export type DecisionActionLabelTranslator = (key: DecisionActionLabelTextKey) => string;

export const DEFAULT_DECISION_ACTION_LABELS: DecisionActionLabelMap = {
  buy: '买入',
  add: '加仓',
  hold: '持有',
  reduce: '减仓',
  sell: '卖出',
  watch: '观望',
  avoid: '回避',
  alert: '预警',
};

const resolveActionLabels = (labels?: Partial<DecisionActionLabelMap>): DecisionActionLabelMap => ({
  ...DEFAULT_DECISION_ACTION_LABELS,
  ...labels,
});

export const buildDecisionActionLabelMap = (
  t: DecisionActionLabelTranslator,
): DecisionActionLabelMap => ({
  buy: t('history.actionBuy'),
  add: t('history.actionAdd'),
  hold: t('history.actionHold'),
  reduce: t('history.actionReduce'),
  sell: t('history.actionSell'),
  watch: t('history.actionWatch'),
  avoid: t('history.actionAvoid'),
  alert: t('history.actionAlert'),
});

const toneForAction = (action: DecisionAction): DecisionActionTone => {
  if (action === 'buy' || action === 'add' || action === 'hold') return 'success';
  if (action === 'sell' || action === 'reduce') return 'danger';
  return 'warning';
};

const includesAny = (value: string, phrases: readonly string[]): boolean =>
  phrases.some((phrase) => value.includes(phrase));

const normalizeEnglishAdvice = (value: string): string =>
  value.toLowerCase().replace(/[_-]/g, ' ');

const maskEnglishFinancialCompounds = (value: string): string =>
  value
    .replace(/(^|[^a-z0-9_])buy\s*back(?=$|[^a-z0-9_])/g, '$1financialcompound')
    .replace(/(^|[^a-z0-9_])sell\s*off(?=$|[^a-z0-9_])/g, '$1financialcompound');

const matchesEnglishTerm = (value: string, terms: readonly string[]): boolean =>
  terms.some((term) => new RegExp(`(^|[^a-z0-9_])${term}(?=$|[^a-z0-9_])`).test(value));

const matchesEnglishNegatedAction = (value: string, terms: readonly string[]): boolean => {
  const negationPrefix = String.raw`(?:not\s+(?:a\s+|an\s+|to\s+)?|no\s+(?:need\s+to\s+)?|need\s+not\s+|cannot\s+|can't\s+|cant\s+|do\s+not\s+|don't\s+|dont\s+)`;
  return terms.some((term) =>
    new RegExp(`(^|[^a-z0-9_])${negationPrefix}${term}(?=$|[^a-z0-9_])`).test(value),
  );
};

const hasEnglishAvoidedHoldAction = (value: string): boolean => {
  const terms = String.raw`(?:adding|accumulating|selling|reducing|trimming)`;
  return new RegExp(`(^|[^a-z0-9_])avoid\\s+${terms}(?=$|[^a-z0-9_])`).test(value);
};

const hasEnglishDeferredAction = (value: string): boolean => {
  const terms = String.raw`(?:buy|add|accumulate|sell|reduce|trim)`;
  return (
    new RegExp(`(^|[^a-z0-9_])wait(?:ing)?\\s+to\\s+${terms}(?=$|[^a-z0-9_])`).test(value) ||
    new RegExp(`(^|[^a-z0-9_])waiting\\s+(?:for|until)\\b.*?${terms}(?=$|[^a-z0-9_])`).test(value)
  );
};

export const getLegacyDecisionActionLabel = (
  advice?: string | null,
  labels?: Partial<DecisionActionLabelMap>,
): string | null => {
  const action = getLegacyDecisionAction(advice);
  if (!action) return null;
  return resolveActionLabels(labels)[action];
};

export const getLegacyDecisionAction = (advice?: string | null): DecisionAction | null => {
  const normalized = advice?.trim();
  if (!normalized) return null;
  const lower = maskEnglishFinancialCompounds(normalizeEnglishAdvice(normalized));

  if (hasEnglishDeferredAction(lower)) {
    return null;
  }

  if (
    includesAny(normalized, [
      '暂不买入',
      '不要买入',
      '不宜买入',
      '先不买入',
      '无需买入',
      '无须买入',
      '不建议建仓',
      '暂不建仓',
      '不要建仓',
      '不宜建仓',
      '先不建仓',
      '无需建仓',
      '无须建仓',
      '不建议布局',
      '暂不布局',
      '不要布局',
      '不宜布局',
      '先不布局',
      '无需布局',
      '无须布局',
    ]) ||
    matchesEnglishNegatedAction(lower, ['buy'])
  ) {
    return 'avoid';
  }
  if (
    includesAny(normalized, [
      '不建议加仓',
      '无需加仓',
      '无须加仓',
      '不要加仓',
      '不宜加仓',
      '暂不加仓',
      '不建议增持',
      '无需增持',
      '无须增持',
      '不要增持',
      '不宜增持',
      '暂不增持',
      '不建议卖出',
      '无需卖出',
      '无须卖出',
      '不要卖出',
      '不宜卖出',
      '暂不卖出',
      '不建议减仓',
      '无需减仓',
      '无须减仓',
      '不要减仓',
      '不宜减仓',
      '暂不减仓',
      '不建议清仓',
      '无需清仓',
      '无须清仓',
      '不要清仓',
      '不宜清仓',
      '暂不清仓',
    ]) ||
    hasEnglishAvoidedHoldAction(lower) ||
    matchesEnglishNegatedAction(lower, ['add', 'accumulate', 'sell', 'reduce', 'trim'])
  ) {
    return 'hold';
  }
  const guardMatches = new Set<DecisionAction>();
  if (
    normalized.includes('不建议买入') ||
    normalized.includes('避免买入') ||
    normalized.includes('回避') ||
    normalized.includes('规避') ||
    matchesEnglishTerm(lower, ['avoid'])
  ) {
    guardMatches.add('avoid');
  }
  if (
    normalized.includes('风险预警') ||
    normalized.includes('触发告警') ||
    normalized.includes('警惕') ||
    lower.includes('risk alert') ||
    matchesEnglishTerm(lower, ['alert'])
  ) {
    guardMatches.add('alert');
  }
  if (guardMatches.size === 1) {
    return Array.from(guardMatches)[0];
  }
  if (guardMatches.size > 1) {
    return null;
  }

  const matches = new Set<DecisionAction>();
  if (normalized.includes('加仓') || normalized.includes('增持') || matchesEnglishTerm(lower, ['add', 'accumulate'])) {
    matches.add('add');
  }
  if (normalized.includes('减仓') || matchesEnglishTerm(lower, ['reduce', 'trim'])) {
    matches.add('reduce');
  }
  if (normalized.includes('强烈卖出') || normalized.includes('卖出') || normalized.includes('清仓') || matchesEnglishTerm(lower, ['sell'])) {
    matches.add('sell');
  }
  if (normalized.includes('持有') || normalized.includes('洗盘观察') || matchesEnglishTerm(lower, ['hold'])) {
    matches.add('hold');
  }
  if (normalized.includes('观望') || normalized.includes('等待') || matchesEnglishTerm(lower, ['watch', 'wait'])) {
    matches.add('watch');
  }
  if (normalized.includes('强烈买入') || normalized.includes('买入') || normalized.includes('布局') || normalized.includes('建仓') || matchesEnglishTerm(lower, ['buy'])) {
    matches.add('buy');
  }

  if (matches.size === 1) {
    return Array.from(matches)[0];
  }
  return null;
};

export const getDecisionActionLabel = (
  action?: DecisionAction | null,
  actionLabel?: string | null,
  legacyAdvice?: string | null,
  emptyLabel: string | null = '建议',
  labels?: Partial<DecisionActionLabelMap>,
): string | null => {
  const actionLabels = resolveActionLabels(labels);
  if (action) return actionLabels[action];
  const explicitLabel = actionLabel?.trim();
  if (explicitLabel) return explicitLabel;
  return getLegacyDecisionActionLabel(legacyAdvice, actionLabels) || emptyLabel;
};

export const getDecisionActionTone = (
  action?: DecisionAction | null,
  actionLabel?: string | null,
  legacyAdvice?: string | null,
): DecisionActionTone => {
  if (action) return toneForAction(action);

  const label = actionLabel?.trim() || '';
  if (label) {
    const lowerLabel = normalizeEnglishAdvice(label);
    if (label.includes('买') || label.includes('加仓') || label.includes('持有')) return 'success';
    if (label.includes('卖') || label.includes('减仓') || label.includes('清仓')) return 'danger';
    if (label.includes('观望') || label.includes('等待') || label.includes('回避') || label.includes('预警')) {
      return 'warning';
    }
    if (matchesEnglishTerm(lowerLabel, ['buy', 'add', 'hold'])) return 'success';
    if (matchesEnglishTerm(lowerLabel, ['sell', 'reduce', 'trim'])) return 'danger';
    if (matchesEnglishTerm(lowerLabel, ['watch', 'wait', 'avoid', 'alert'])) return 'warning';
    return 'default';
  }

  const legacyAction = getLegacyDecisionAction(legacyAdvice);
  if (legacyAction) return toneForAction(legacyAction);

  return 'default';
};
