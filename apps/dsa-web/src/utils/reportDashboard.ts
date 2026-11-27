import type {
  ReportDetails,
  ReportLanguage,
  ReportMeta,
  ReportStrategy,
  ReportSummary,
} from '../types/analysis';
import { parseStrategyPriceLevel } from './priceChart';
import {
  formatStrategySynthesisSummary,
  getReportText,
  localizeConflictSeverity,
  localizeConsensusLevel,
  localizeStrategySignal,
  normalizeReportLanguage,
} from './reportLanguage';

export interface ParsedChecklistItem {
  text: string;
  status: 'pass' | 'warn' | 'fail';
}

export interface ParsedStrategySkillItem {
  skillId: string;
  signal: string;
  confidence?: number;
  reasoning?: string;
  scoreAdjustment?: number;
}

export interface ParsedStrategySynthesis {
  finalSignal: string;
  consensusLevel: string;
  conflictSeverity: string;
  conflictCount: number;
  confidence?: number;
  opinionCount: number;
  invalidOpinionCount: number;
  supportingSkills: ParsedStrategySkillItem[];
  opposingSkills: ParsedStrategySkillItem[];
  minorityViewPreserved: boolean;
}

export interface ParsedSignalAttribution {
  weights: Array<{
    key: 'technical' | 'news' | 'fundamentals' | 'market';
    value: number;
  }>;
  strongestBullish?: string;
  strongestBearish?: string;
}

export interface ParsedReportDashboard {
  oneSentence?: string;
  timeSensitivity?: string;
  positionAdvice: {
    noPosition?: string;
    hasPosition?: string;
  };
  positionStrategy: {
    suggestedPosition?: string;
    entryPlan?: string;
    riskControl?: string;
  };
  riskAlerts: string[];
  positiveCatalysts: string[];
  sentimentSummary?: string;
  earningsOutlook?: string;
  actionChecklist: ParsedChecklistItem[];
  signalAttribution: ParsedSignalAttribution | null;
  strategySynthesis: ParsedStrategySynthesis | null;
}

export interface StrategyPriceMetrics {
  idealBuyNum?: number;
  secondaryBuyNum?: number;
  stopLossNum?: number;
  takeProfitNum?: number;
  idealBuyDeltaPct?: number;
  secondaryBuyDeltaPct?: number;
  stopLossDeltaPct?: number;
  takeProfitDeltaPct?: number;
  riskRewardRatio?: number;
  upsidePct?: number;
  downsidePct?: number;
  refBasis?: 'idealBuy' | 'current';
  priceZone?: 'belowStop' | 'inRange' | 'aboveTarget';
  range?: {
    stopLoss: number;
    idealBuy?: number;
    secondaryBuy?: number;
    currentPrice?: number;
    takeProfit: number;
    refPrice: number;
    idealBuyPct?: number;
    currentPct?: number;
  };
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === 'object' && !Array.isArray(value));

const getNestedValue = (obj: Record<string, unknown> | undefined, ...keys: string[]): unknown => {
  if (!obj) return undefined;
  for (const key of keys) {
    if (key in obj && obj[key] !== undefined && obj[key] !== null) {
      return obj[key];
    }
  }
  return undefined;
};

const asTrimmedString = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const asStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : String(item ?? '').trim()))
      .filter((item) => item.length > 0);
  }
  const single = asTrimmedString(value);
  return single ? [single] : [];
};

const classifyChecklistItem = (raw: string): ParsedChecklistItem => {
  const text = raw.trim();
  if (/^(?:✅|✔|☑|\[\s*pass\s*\])/i.test(text)) {
    return { text, status: 'pass' };
  }
  if (/^(?:❌|✗|✘|\[x\]|\[\s*fail\s*\])/i.test(text)) {
    return { text, status: 'fail' };
  }
  if (/^(?:⚠️|⚠|\[!\])/i.test(text)) {
    return { text, status: 'warn' };
  }
  if (/不通过|未满足|fail/i.test(text)) {
    return { text, status: 'fail' };
  }
  if (/注意|警告|caution|warn/i.test(text)) {
    return { text, status: 'warn' };
  }
  return { text, status: 'pass' };
};

const parseWeightValue = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const cleaned = value.trim().replace(/%$/, '');
    if (!cleaned) return undefined;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

const parseStrictNonNegativeInt = (value: unknown): number => {
  if (typeof value === 'boolean') return 0;
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 0 ? Math.trunc(value) : 0;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (/^\d+$/.test(trimmed)) {
      const parsed = Number.parseInt(trimmed, 10);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    }
  }
  return 0;
};

const parseStrictConfidence = (value: unknown): number | undefined => {
  if (typeof value === 'boolean') return undefined;
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value.trim()) : Number.NaN;
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) return undefined;
  return parsed;
};

const parseSkillItems = (rawItems: unknown): ParsedStrategySkillItem[] => {
  if (!Array.isArray(rawItems)) return [];
  const items: ParsedStrategySkillItem[] = [];
  for (const entry of rawItems) {
    if (!isRecord(entry)) continue;
    const skillId = asTrimmedString(getNestedValue(entry, 'skillId', 'skill_id', 'agentName', 'agent_name'));
    const signal = asTrimmedString(getNestedValue(entry, 'signal', 'normalizedSignal', 'normalized_signal'));
    if (!skillId) continue;
    const confidence = parseStrictConfidence(entry.confidence);
    const reasoning = asTrimmedString(entry.reasoning);
    const rawAdj = getNestedValue(entry, 'scoreAdjustment', 'score_adjustment');
    const scoreAdjustment = typeof rawAdj === 'number' && Number.isFinite(rawAdj) ? rawAdj : undefined;
    items.push({
      skillId,
      signal: signal || 'hold',
      confidence,
      reasoning,
      scoreAdjustment,
    });
  }
  return items;
};

/**
 * Extract structured multi-strategy consensus synthesis from ReportDetails.rawResult.
 */
export const parseStrategySynthesis = (details?: ReportDetails): ParsedStrategySynthesis | null => {
  if (!details || !isRecord(details.rawResult)) {
    return null;
  }

  const raw = details.rawResult;
  const dashboardVal = getNestedValue(raw, 'dashboard');
  const dashboard = isRecord(dashboardVal) ? dashboardVal : undefined;
  const synthesisVal = getNestedValue(
    dashboard ?? raw,
    'strategySynthesis',
    'strategy_synthesis',
  ) ?? getNestedValue(raw, 'strategySynthesis', 'strategy_synthesis');
  if (!isRecord(synthesisVal)) {
    return null;
  }

  const finalSignal = asTrimmedString(getNestedValue(synthesisVal, 'finalSignal', 'final_signal')) || '';
  const consensusLevel = asTrimmedString(getNestedValue(synthesisVal, 'consensusLevel', 'consensus_level')) || 'N/A';
  const conflictSeverity = asTrimmedString(getNestedValue(synthesisVal, 'conflictSeverity', 'conflict_severity')) || 'none';
  const conflictCount = parseStrictNonNegativeInt(getNestedValue(synthesisVal, 'conflictCount', 'conflict_count'));
  const confidence = parseStrictConfidence(synthesisVal.confidence);

  const supportingSkills = parseSkillItems(getNestedValue(synthesisVal, 'supportingSkills', 'supporting_skills'));
  const opposingSkills = parseSkillItems(getNestedValue(synthesisVal, 'opposingSkills', 'opposing_skills'));

  if (!finalSignal && supportingSkills.length === 0 && opposingSkills.length === 0) {
    return null;
  }

  const summaryParamsVal = getNestedValue(synthesisVal, 'summaryParams', 'summary_params');
  const summaryParams = isRecord(summaryParamsVal) ? summaryParamsVal : undefined;
  const explicitOpinionCount = parseStrictNonNegativeInt(
    getNestedValue(summaryParams, 'opinionCount', 'opinion_count'),
  );
  const opinionCount = explicitOpinionCount > 0
    ? explicitOpinionCount
    : (supportingSkills.length + opposingSkills.length);
  const invalidOpinionCount = parseStrictNonNegativeInt(
    getNestedValue(summaryParams, 'invalidOpinionCount', 'invalid_opinion_count'),
  );

  const deliberationVal = getNestedValue(synthesisVal, 'deliberation');
  const deliberation = isRecord(deliberationVal) ? deliberationVal : undefined;
  const deliberationSummaryVal = getNestedValue(deliberation, 'summary');
  const deliberationSummary = isRecord(deliberationSummaryVal) ? deliberationSummaryVal : undefined;
  const minorityFlag = getNestedValue(
    deliberationSummary ?? synthesisVal,
    'minorityViewPreserved',
    'minority_view_preserved',
  );
  const minorityViewPreserved = minorityFlag === true;

  return {
    finalSignal: finalSignal || 'hold',
    consensusLevel,
    conflictSeverity,
    conflictCount,
    confidence,
    opinionCount,
    invalidOpinionCount,
    supportingSkills,
    opposingSkills,
    minorityViewPreserved,
  };
};

/**
 * Extract structured decision brief fields from ReportDetails.rawResult.
 * Supports both camelCase (transformed by historyApi toCamelCase) and snake_case.
 */
export const parseReportDashboard = (details?: ReportDetails): ParsedReportDashboard | null => {
  if (!details || !isRecord(details.rawResult)) {
    return null;
  }

  const raw = details.rawResult;
  const dashboardVal = getNestedValue(raw, 'dashboard');
  const dashboard = isRecord(dashboardVal) ? dashboardVal : undefined;

  const coreVal = getNestedValue(dashboard, 'coreConclusion', 'core_conclusion');
  const core = isRecord(coreVal) ? coreVal : undefined;

  const intelVal = getNestedValue(dashboard, 'intelligence');
  const intel = isRecord(intelVal) ? intelVal : undefined;

  const battleVal = getNestedValue(dashboard, 'battlePlan', 'battle_plan');
  const battle = isRecord(battleVal) ? battleVal : undefined;

  const posAdviceVal = getNestedValue(core, 'positionAdvice', 'position_advice');
  const posAdvice = isRecord(posAdviceVal) ? posAdviceVal : undefined;

  const posStratVal = getNestedValue(battle, 'positionStrategy', 'position_strategy');
  const posStrat = isRecord(posStratVal) ? posStratVal : undefined;

  const attrVal = getNestedValue(dashboard, 'signalAttribution', 'signal_attribution');
  const attr = isRecord(attrVal) ? attrVal : undefined;

  const oneSentence = asTrimmedString(getNestedValue(core, 'oneSentence', 'one_sentence'));
  const timeSensitivity = asTrimmedString(getNestedValue(core, 'timeSensitivity', 'time_sensitivity'));

  const positionAdvice = {
    noPosition: asTrimmedString(getNestedValue(posAdvice, 'noPosition', 'no_position')),
    hasPosition: asTrimmedString(getNestedValue(posAdvice, 'hasPosition', 'has_position')),
  };

  const positionStrategy = {
    suggestedPosition: asTrimmedString(getNestedValue(posStrat, 'suggestedPosition', 'suggested_position')),
    entryPlan: asTrimmedString(getNestedValue(posStrat, 'entryPlan', 'entry_plan')),
    riskControl: asTrimmedString(getNestedValue(posStrat, 'riskControl', 'risk_control')),
  };

  const intelRisks = asStringArray(getNestedValue(intel, 'riskAlerts', 'risk_alerts'));
  const fallbackRisks = asStringArray(getNestedValue(raw, 'riskWarning', 'risk_warning'));
  const riskAlerts = intelRisks.length > 0 ? intelRisks : fallbackRisks;

  const positiveCatalysts = asStringArray(getNestedValue(intel, 'positiveCatalysts', 'positive_catalysts'));
  const sentimentSummary = asTrimmedString(getNestedValue(intel, 'sentimentSummary', 'sentiment_summary'));
  const earningsOutlook = asTrimmedString(getNestedValue(intel, 'earningsOutlook', 'earnings_outlook'));

  const checklistRaw = asStringArray(getNestedValue(battle, 'actionChecklist', 'action_checklist'));
  const actionChecklist = checklistRaw.map(classifyChecklistItem);

  let signalAttribution: ParsedSignalAttribution | null = null;
  if (attr) {
    const weightsRawVal = getNestedValue(attr, 'attributionWeights', 'attribution_weights', 'weights');
    const weightsMap = isRecord(weightsRawVal) ? weightsRawVal : attr;
    const candidateWeights: Array<{ key: 'technical' | 'news' | 'fundamentals' | 'market'; value: number }> = [];

    const specs: Array<{ key: 'technical' | 'news' | 'fundamentals' | 'market'; names: string[] }> = [
      { key: 'technical', names: ['technicalIndicators', 'technical_indicators', 'technical'] },
      { key: 'news', names: ['newsSentiment', 'news_sentiment', 'news'] },
      { key: 'fundamentals', names: ['fundamentals', 'fundamental'] },
      { key: 'market', names: ['marketConditions', 'market_conditions', 'market'] },
    ];
    for (const spec of specs) {
      const val = parseWeightValue(getNestedValue(weightsMap, ...spec.names));
      if (val !== undefined && val > 0) {
        candidateWeights.push({ key: spec.key, value: val });
      }
    }

    const strongestBullish = asTrimmedString(
      getNestedValue(attr, 'strongestBullishSignal', 'strongest_bullish_signal'),
    );
    const strongestBearish = asTrimmedString(
      getNestedValue(attr, 'strongestBearishSignal', 'strongest_bearish_signal'),
    );

    if (candidateWeights.length > 0 || strongestBullish || strongestBearish) {
      signalAttribution = {
        weights: candidateWeights,
        strongestBullish,
        strongestBearish,
      };
    }
  }

  const strategySynthesis = parseStrategySynthesis(details);

  const hasContent = Boolean(
    riskAlerts.length > 0
    || positiveCatalysts.length > 0
    || positionAdvice.noPosition
    || positionAdvice.hasPosition
    || positionStrategy.suggestedPosition
    || positionStrategy.entryPlan
    || positionStrategy.riskControl
    || actionChecklist.length > 0
    || signalAttribution
    || strategySynthesis
    || earningsOutlook
    || sentimentSummary,
  );

  if (!hasContent) {
    return null;
  }

  return {
    oneSentence,
    timeSensitivity,
    positionAdvice,
    positionStrategy,
    riskAlerts,
    positiveCatalysts,
    sentimentSummary,
    earningsOutlook,
    actionChecklist,
    signalAttribution,
    strategySynthesis,
  };
};

const isCompatiblePriceScale = (price: number, reference?: number): boolean => {
  if (!Number.isFinite(price) || price <= 0) return false;
  if (!reference || !Number.isFinite(reference) || reference <= 0) return true;
  const ratio = Math.max(price / reference, reference / price);
  return ratio <= 5;
};

const computeDeltaPct = (level: number | undefined, currentPrice?: number): number | undefined => {
  if (level === undefined || !currentPrice || !Number.isFinite(currentPrice) || currentPrice <= 0) {
    return undefined;
  }
  if (!isCompatiblePriceScale(level, currentPrice)) {
    return undefined;
  }
  return ((level - currentPrice) / currentPrice) * 100;
};

/**
 * Derive strategy distance %, risk/reward ratio, and normalized range-bar positions.
 */
export const computeStrategyPriceMetrics = (
  strategy?: ReportStrategy,
  currentPrice?: number,
  action?: string,
): StrategyPriceMetrics => {
  if (!strategy) {
    return {};
  }

  const idealBuyNum = parseStrategyPriceLevel(strategy.idealBuy) ?? undefined;
  const secondaryBuyNum = parseStrategyPriceLevel(strategy.secondaryBuy) ?? undefined;
  const stopLossNum = parseStrategyPriceLevel(strategy.stopLoss) ?? undefined;
  const takeProfitNum = parseStrategyPriceLevel(strategy.takeProfit) ?? undefined;

  const idealBuyDeltaPct = computeDeltaPct(idealBuyNum, currentPrice);
  const secondaryBuyDeltaPct = computeDeltaPct(secondaryBuyNum, currentPrice);
  const stopLossDeltaPct = computeDeltaPct(stopLossNum, currentPrice);
  const takeProfitDeltaPct = computeDeltaPct(takeProfitNum, currentPrice);

  const normalizedAction = typeof action === 'string' ? action.trim().toLowerCase() : '';
  const suppressBullishRr = normalizedAction === 'sell' || normalizedAction === 'reduce';

  const validCurrent = currentPrice !== undefined && Number.isFinite(currentPrice) && currentPrice > 0
    ? currentPrice
    : undefined;
  let refBasis: StrategyPriceMetrics['refBasis'];
  let refPrice: number | undefined;
  if (idealBuyNum && isCompatiblePriceScale(idealBuyNum, validCurrent)) {
    refPrice = idealBuyNum;
    refBasis = 'idealBuy';
  } else if (validCurrent) {
    refPrice = validCurrent;
    refBasis = 'current';
  }

  let priceZone: StrategyPriceMetrics['priceZone'];
  if (
    stopLossNum
    && takeProfitNum
    && stopLossNum < takeProfitNum
    && validCurrent !== undefined
    && isCompatiblePriceScale(stopLossNum, takeProfitNum)
    && isCompatiblePriceScale(validCurrent, stopLossNum)
    && isCompatiblePriceScale(validCurrent, takeProfitNum)
  ) {
    if (validCurrent < stopLossNum) {
      priceZone = 'belowStop';
    } else if (validCurrent > takeProfitNum) {
      priceZone = 'aboveTarget';
    } else {
      priceZone = 'inRange';
    }
  }

  let riskRewardRatio: number | undefined;
  let upsidePct: number | undefined;
  let downsidePct: number | undefined;
  let range: StrategyPriceMetrics['range'];

  if (
    !suppressBullishRr
    && refPrice
    && stopLossNum
    && takeProfitNum
    && isCompatiblePriceScale(stopLossNum, refPrice)
    && isCompatiblePriceScale(takeProfitNum, refPrice)
    && isCompatiblePriceScale(stopLossNum, takeProfitNum)
    && stopLossNum < refPrice
    && refPrice < takeProfitNum
  ) {
    const risk = refPrice - stopLossNum;
    const reward = takeProfitNum - refPrice;
    const span = takeProfitNum - stopLossNum;
    if (risk > 0 && reward > 0 && span > 0) {
      riskRewardRatio = Math.round((reward / risk) * 100) / 100;
      upsidePct = Math.round(((reward / refPrice) * 100) * 10) / 10;
      downsidePct = Math.round(((risk / refPrice) * 100) * 10) / 10;

      const pct = (v: number) => Math.max(0, Math.min(100, ((v - stopLossNum) / span) * 100));
      let currentPct: number | undefined;
      if (priceZone === 'belowStop') {
        currentPct = 0;
      } else if (priceZone === 'aboveTarget') {
        currentPct = 100;
      } else if (validCurrent !== undefined && priceZone === 'inRange') {
        currentPct = pct(validCurrent);
      }
      range = {
        stopLoss: stopLossNum,
        idealBuy: idealBuyNum,
        secondaryBuy: secondaryBuyNum,
        currentPrice: validCurrent,
        takeProfit: takeProfitNum,
        refPrice,
        idealBuyPct: idealBuyNum !== undefined ? pct(idealBuyNum) : pct(refPrice),
        currentPct,
      };
    }
  }

  return {
    idealBuyNum,
    secondaryBuyNum,
    stopLossNum,
    takeProfitNum,
    idealBuyDeltaPct,
    secondaryBuyDeltaPct,
    stopLossDeltaPct,
    takeProfitDeltaPct,
    riskRewardRatio,
    upsidePct,
    downsidePct,
    refBasis,
    priceZone,
    range,
  };
};

export interface ParsedMarketSnapshot {
  open?: number;
  high?: number;
  low?: number;
  amplitude?: number;
  volumeRatio?: number;
  turnoverRate?: number;
  peRatio?: number;
  pbRatio?: number;
}

const pickSnapshotNumber = (
  sources: Array<Record<string, unknown> | undefined>,
  keys: string[],
  predicate: (n: number) => boolean,
): number | undefined => {
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      if (!(key in source)) continue;
      const num = parseWeightValue(source[key]);
      if (num !== undefined && Number.isFinite(num) && predicate(num)) {
        return num;
      }
    }
  }
  return undefined;
};

/**
 * Extract market quote and valuation snapshot metrics from ReportDetails.
 */
export const parseReportMarketSnapshot = (details?: ReportDetails): ParsedMarketSnapshot | null => {
  if (!details) return null;

  const ctx = isRecord(details.contextSnapshot) ? details.contextSnapshot : undefined;
  const enhanced = isRecord(getNestedValue(ctx, 'enhancedContext', 'enhanced_context'))
    ? (getNestedValue(ctx, 'enhancedContext', 'enhanced_context') as Record<string, unknown>)
    : undefined;
  const raw = isRecord(details.rawResult) ? details.rawResult : undefined;

  const sources: Array<Record<string, unknown> | undefined> = [
    isRecord(ctx?.realtime) ? (ctx.realtime as Record<string, unknown>) : undefined,
    isRecord(enhanced?.realtime) ? (enhanced.realtime as Record<string, unknown>) : undefined,
    isRecord(ctx?.today) ? (ctx.today as Record<string, unknown>) : undefined,
    isRecord(enhanced?.today) ? (enhanced.today as Record<string, unknown>) : undefined,
    ctx,
    isRecord(raw?.realtime) ? (raw.realtime as Record<string, unknown>) : undefined,
    raw,
  ];

  const open = pickSnapshotNumber(sources, ['open', 'openPrice', 'open_price'], (n) => n > 0);
  const high = pickSnapshotNumber(sources, ['high', 'highPrice', 'high_price'], (n) => n > 0);
  const low = pickSnapshotNumber(sources, ['low', 'lowPrice', 'low_price'], (n) => n > 0);
  const amplitude = pickSnapshotNumber(sources, ['amplitude'], (n) => n >= 0);
  const volumeRatio = pickSnapshotNumber(sources, ['volumeRatio', 'volume_ratio'], (n) => n >= 0);
  const turnoverRate = pickSnapshotNumber(sources, ['turnoverRate', 'turnover_rate'], (n) => n >= 0);
  const peRatio = pickSnapshotNumber(sources, ['peRatio', 'pe_ratio', 'pe'], (n) => n !== 0);
  const pbRatio = pickSnapshotNumber(sources, ['pbRatio', 'pb_ratio', 'pb'], (n) => n !== 0);

  if (
    open === undefined
    && high === undefined
    && low === undefined
    && amplitude === undefined
    && volumeRatio === undefined
    && turnoverRate === undefined
    && peRatio === undefined
    && pbRatio === undefined
  ) {
    return null;
  }

  return {
    open,
    high,
    low,
    amplitude,
    volumeRatio,
    turnoverRate,
    peRatio,
    pbRatio,
  };
};

/**
 * Build concise plain-text decision brief for one-click clipboard sharing.
 */
export const buildDecisionBriefCopyText = ({
  meta,
  summary,
  strategy,
  details,
  language,
}: {
  meta: ReportMeta;
  summary: ReportSummary;
  strategy?: ReportStrategy;
  details?: ReportDetails;
  language?: ReportLanguage;
}): string => {
  const lang = normalizeReportLanguage(language ?? meta.reportLanguage);
  const text = getReportText(lang);
  const titleName = meta.stockName ? `${meta.stockName} (${meta.stockCode})` : meta.stockCode;
  const pricePart = meta.currentPrice != null
    ? ` · ${meta.currentPrice.toFixed(2)}${
      meta.changePct != null
        ? ` (${meta.changePct > 0 ? '+' : ''}${meta.changePct.toFixed(2)}%)`
        : ''
    }`
    : '';
  const advice = summary.actionLabel || summary.operationAdvice || text.noAdvice;
  const lines: string[] = [
    `${titleName}${pricePart}`,
    `${text.actionAdvice}: ${advice} | ${text.marketSentiment}: ${summary.sentimentScore}/100${
      summary.trendPrediction ? ` | ${summary.trendPrediction}` : ''
    }`,
  ];

  if (summary.analysisSummary) {
    lines.push(`${text.keyInsights}: ${summary.analysisSummary}`);
  }

  const levelParts: string[] = [];
  if (strategy?.idealBuy) levelParts.push(`${text.idealBuy}: ${strategy.idealBuy}`);
  if (strategy?.secondaryBuy) levelParts.push(`${text.secondaryBuy}: ${strategy.secondaryBuy}`);
  if (strategy?.stopLoss) levelParts.push(`${text.stopLoss}: ${strategy.stopLoss}`);
  if (strategy?.takeProfit) levelParts.push(`${text.takeProfit}: ${strategy.takeProfit}`);
  if (levelParts.length > 0) {
    lines.push(`${text.sniperLevels}: ${levelParts.join(' | ')}`);
  }

  const brief = parseReportDashboard(details);
  if (brief && brief.riskAlerts.length > 0) {
    lines.push(`${text.riskAlertsTitle}: ${brief.riskAlerts.slice(0, 2).join('; ')}`);
  }

  if (brief?.strategySynthesis) {
    const syn = brief.strategySynthesis;
    const summaryLine = formatStrategySynthesisSummary(syn, lang);
    const sev = localizeConflictSeverity(syn.conflictSeverity, lang);
    const sig = localizeStrategySignal(syn.finalSignal, lang);
    const cons = localizeConsensusLevel(syn.consensusLevel, lang);
    const conf = syn.confidence !== undefined ? ` | ${text.strategyConfidence}: ${Math.round(syn.confidence * 100)}%` : '';
    lines.push(
      `${text.strategySynthesisTitle}: ${sig} | ${text.strategyConsensus}: ${cons} | ${text.strategyConflict}: ${sev} (${syn.conflictCount})${conf} — ${summaryLine}`,
    );
  }

  const snap = parseReportMarketSnapshot(details);
  if (snap) {
    const snapParts: string[] = [];
    if (snap.open !== undefined) snapParts.push(`${text.openPrice} ${snap.open.toFixed(2)}`);
    if (snap.high !== undefined && snap.low !== undefined) {
      snapParts.push(`${text.highLowRange} ${snap.high.toFixed(2)}/${snap.low.toFixed(2)}`);
    }
    if (snap.amplitude !== undefined) snapParts.push(`${text.amplitude} ${snap.amplitude.toFixed(2)}%`);
    if (snap.volumeRatio !== undefined) snapParts.push(`${text.volumeRatio} ${snap.volumeRatio.toFixed(2)}`);
    if (snap.turnoverRate !== undefined) snapParts.push(`${text.turnoverRate} ${snap.turnoverRate.toFixed(2)}%`);
    if (snap.peRatio !== undefined) snapParts.push(`${text.peRatio} ${snap.peRatio.toFixed(1)}`);
    if (snap.pbRatio !== undefined) snapParts.push(`${text.pbRatio} ${snap.pbRatio.toFixed(2)}`);
    if (snapParts.length > 0) {
      lines.push(`${text.marketSnapshotLabel}: ${snapParts.join(' · ')}`);
    }
  }

  return lines.join('\n');
};
