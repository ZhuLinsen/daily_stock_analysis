import type { MarketPhaseValue } from '../types/analysis';
import type {
  DecisionSignalHorizon,
  DecisionSignalMarket,
  DecisionSignalPlanQuality,
  DecisionSignalSourceType,
} from '../types/decisionSignals';
import type { UiTextKey } from '../i18n/uiText';

type Translator = (key: UiTextKey) => string;

const MARKET_LABEL_KEYS: Record<DecisionSignalMarket, UiTextKey> = {
  cn: 'decisionSignals.market.cn',
  hk: 'decisionSignals.market.hk',
  us: 'decisionSignals.market.us',
  jp: 'decisionSignals.market.jp',
  kr: 'decisionSignals.market.kr',
  tw: 'decisionSignals.market.tw',
};

const MARKET_PHASE_LABEL_KEYS: Record<MarketPhaseValue, UiTextKey> = {
  premarket: 'decisionSignals.marketPhase.premarket',
  intraday: 'decisionSignals.marketPhase.intraday',
  lunch_break: 'decisionSignals.marketPhase.lunch_break',
  closing_auction: 'decisionSignals.marketPhase.closing_auction',
  postmarket: 'decisionSignals.marketPhase.postmarket',
  non_trading: 'decisionSignals.marketPhase.non_trading',
  unknown: 'decisionSignals.marketPhase.unknown',
};

const HORIZON_LABEL_KEYS: Record<DecisionSignalHorizon, UiTextKey> = {
  intraday: 'decisionSignals.horizon.intraday',
  '1d': 'decisionSignals.horizon.1d',
  '3d': 'decisionSignals.horizon.3d',
  '5d': 'decisionSignals.horizon.5d',
  '10d': 'decisionSignals.horizon.10d',
  swing: 'decisionSignals.horizon.swing',
  long: 'decisionSignals.horizon.long',
};

const PLAN_QUALITY_LABEL_KEYS: Record<DecisionSignalPlanQuality, UiTextKey> = {
  complete: 'decisionSignals.planQuality.complete',
  partial: 'decisionSignals.planQuality.partial',
  minimal: 'decisionSignals.planQuality.minimal',
  unknown: 'decisionSignals.planQuality.unknown',
};

const SOURCE_TYPE_LABEL_KEYS: Record<DecisionSignalSourceType, UiTextKey> = {
  analysis: 'decisionSignals.sourceType.analysis',
  agent: 'decisionSignals.sourceType.agent',
  alert: 'decisionSignals.sourceType.alert',
  market_review: 'decisionSignals.sourceType.market_review',
  manual: 'decisionSignals.sourceType.manual',
};

function translatedKnownValue<Value extends string>(
  value: Value | null | undefined,
  keys: Record<Value, UiTextKey>,
  t: Translator,
): string {
  if (!value) return '-';
  const key = keys[value];
  return key ? t(key) || '-' : '-';
}

export function getDecisionSignalMarketLabel(
  market: DecisionSignalMarket | null | undefined,
  t: Translator,
): string {
  return translatedKnownValue(market, MARKET_LABEL_KEYS, t);
}

export function getDecisionSignalMarketPhaseLabel(
  marketPhase: MarketPhaseValue | null | undefined,
  t: Translator,
): string {
  return translatedKnownValue(marketPhase, MARKET_PHASE_LABEL_KEYS, t);
}

export function getDecisionSignalHorizonLabel(
  horizon: DecisionSignalHorizon | null | undefined,
  t: Translator,
): string {
  return translatedKnownValue(horizon, HORIZON_LABEL_KEYS, t);
}

export function getDecisionSignalPlanQualityLabel(
  planQuality: DecisionSignalPlanQuality | null | undefined,
  t: Translator,
): string {
  return translatedKnownValue(planQuality, PLAN_QUALITY_LABEL_KEYS, t);
}

export function getDecisionSignalSourceTypeLabel(
  sourceType: DecisionSignalSourceType | null | undefined,
  t: Translator,
): string {
  return translatedKnownValue(sourceType, SOURCE_TYPE_LABEL_KEYS, t);
}
