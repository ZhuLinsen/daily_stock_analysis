// Phase 25.7: four-masters commentary adapter.
// Normalizes AnalysisReport.details.rawResult.fourMastersCommentary (deep camelCase
// from the API layer; snake_case tolerated for raw payload parity) into a strict
// view model. Commentary-only: action-like fields are never carried into the VM,
// enums are coerced, and any malformed payload yields null so the section is omitted.

export type MasterKey = 'buffett' | 'munger' | 'duanYongping' | 'liLu';
export type StanceValue = 'support' | 'challenge' | 'mixed';
export type ConfidenceAdjustment = 'raise' | 'lower' | 'unchanged';

export interface FourMastersDetailVM {
  label: string;
  value: string;
}

export interface FourMastersCardVM {
  key: MasterKey;
  monogram: string;
  title: string;
  subtitle: string;
  stance: StanceValue;
  summary: string;
  details: FourMastersDetailVM[];
  redLines: string[];
}

export interface FourMastersSynthesisVM {
  mainDisagreement: string | null;
  mostUsefulSupplement: string | null;
  confidenceAdjustment: ConfidenceAdjustment;
}

export interface FourMastersCommentaryVM {
  cards: FourMastersCardVM[];
  synthesis: FourMastersSynthesisVM;
}

const MAX_TEXT_LEN = 600;
const MAX_RED_LINES = 5;

const STANCE_VALUES: readonly StanceValue[] = ['support', 'challenge', 'mixed'];
const CONFIDENCE_VALUES: readonly ConfidenceAdjustment[] = ['raise', 'lower', 'unchanged'];

interface MasterSpec {
  key: MasterKey;
  sourceKeys: string[];
  monogram: string;
  title: string;
  subtitle: string;
  detailFields: Array<{ keys: string[]; label: string }>;
}

// Field whitelist per master. Anything outside this list (including any
// action/advice fields an LLM might smuggle in) never reaches the VM.
const MASTER_SPECS: MasterSpec[] = [
  {
    key: 'buffett',
    sourceKeys: ['buffett'],
    monogram: '巴',
    title: '巴菲特視角',
    subtitle: '價值與安全邊際',
    detailFields: [
      { keys: ['keyQuestion', 'key_question'], label: '關鍵問題' },
      { keys: ['blindSpotInOriginalReport', 'blind_spot_in_original_report'], label: '原始報告盲點' },
      { keys: ['marginOfSafetyComment', 'margin_of_safety_comment'], label: '安全邊際' },
      { keys: ['whatWouldChangeThisView', 'what_would_change_this_view'], label: '改變看法的條件' },
    ],
  },
  {
    key: 'munger',
    sourceKeys: ['munger'],
    monogram: '蒙',
    title: '蒙格視角',
    subtitle: '反向思考與誤判檢查',
    detailFields: [
      { keys: ['inversionQuestion', 'inversion_question'], label: '反向問題' },
      { keys: ['biggestFailureMode', 'biggest_failure_mode'], label: '最大失效模式' },
      { keys: ['psychologicalBiasWarning', 'psychological_bias_warning'], label: '心理偏誤警示' },
      { keys: ['whatWouldChangeThisView', 'what_would_change_this_view'], label: '改變看法的條件' },
    ],
  },
  {
    key: 'duanYongping',
    sourceKeys: ['duanYongping', 'duan_yongping'],
    monogram: '段',
    title: '段永平視角',
    subtitle: '生意模式與用戶價值',
    detailFields: [
      { keys: ['businessQualityComment', 'business_quality_comment'], label: '生意品質' },
      { keys: ['productOrCustomerValueComment', 'product_or_customer_value_comment'], label: '產品/用戶價值' },
      { keys: ['longTermHoldingCondition', 'long_term_holding_condition'], label: '長期持有條件' },
      { keys: ['whatWouldChangeThisView', 'what_would_change_this_view'], label: '改變看法的條件' },
    ],
  },
  {
    key: 'liLu',
    sourceKeys: ['liLu', 'li_lu'],
    monogram: '李',
    title: '李錄視角',
    subtitle: '長期確定性與風險紅線',
    detailFields: [
      { keys: ['certaintyComment', 'certainty_comment'], label: '長期確定性' },
      { keys: ['downsideRiskComment', 'downside_risk_comment'], label: '下行風險' },
      { keys: ['whatWouldChangeThisView', 'what_would_change_this_view'], label: '改變看法的條件' },
    ],
  },
];

export const STANCE_LABELS: Record<StanceValue, string> = {
  support: '支持',
  challenge: '質疑',
  mixed: '混合',
};

export const CONFIDENCE_LABELS: Record<ConfidenceAdjustment, string> = {
  raise: '信心調整：上調',
  lower: '信心調整：下調',
  unchanged: '信心調整：不變',
};

function sanitizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value
    .replace(/<[^>]*>/g, '')
    .replace(/[<>]/g, '')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return null;
  return text.slice(0, MAX_TEXT_LEN);
}

function pick(source: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function coerceStance(value: unknown): StanceValue {
  const text = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return (STANCE_VALUES as readonly string[]).includes(text) ? (text as StanceValue) : 'mixed';
}

function coerceConfidence(value: unknown): ConfidenceAdjustment {
  const text = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return (CONFIDENCE_VALUES as readonly string[]).includes(text)
    ? (text as ConfidenceAdjustment)
    : 'unchanged';
}

function adaptRedLines(value: unknown): string[] {
  if (typeof value === 'string') {
    const single = sanitizeText(value);
    return single ? [single] : [];
  }
  if (!Array.isArray(value)) return [];
  return value
    .slice(0, MAX_RED_LINES)
    .map(sanitizeText)
    .filter((item): item is string => Boolean(item));
}

function adaptMasterCard(spec: MasterSpec, raw: Record<string, unknown>): FourMastersCardVM | null {
  const blockRaw = pick(raw, spec.sourceKeys);
  if (typeof blockRaw !== 'object' || blockRaw === null || Array.isArray(blockRaw)) return null;
  const block = blockRaw as Record<string, unknown>;

  const summary = sanitizeText(pick(block, ['summary']));
  if (!summary) return null;

  const details: FourMastersDetailVM[] = [];
  for (const field of spec.detailFields) {
    const value = sanitizeText(pick(block, field.keys));
    if (value) details.push({ label: field.label, value });
  }

  return {
    key: spec.key,
    monogram: spec.monogram,
    title: spec.title,
    subtitle: spec.subtitle,
    stance: coerceStance(pick(block, ['supportsOriginalView', 'supports_original_view'])),
    summary,
    details,
    redLines: spec.key === 'liLu' ? adaptRedLines(pick(block, ['redLines', 'red_lines'])) : [],
  };
}

/**
 * Adapt a raw fourMastersCommentary payload to the section view model.
 * Returns null (section omitted) when the payload is missing, malformed,
 * or carries no renderable master summary.
 */
export function adaptFourMastersCommentary(rawValue: unknown): FourMastersCommentaryVM | null {
  if (typeof rawValue !== 'object' || rawValue === null || Array.isArray(rawValue)) return null;
  const raw = rawValue as Record<string, unknown>;

  const cards = MASTER_SPECS
    .map((spec) => adaptMasterCard(spec, raw))
    .filter((card): card is FourMastersCardVM => card !== null);
  if (!cards.length) return null;

  const synthesisRaw = pick(raw, ['synthesis']);
  const synthesisBlock =
    typeof synthesisRaw === 'object' && synthesisRaw !== null && !Array.isArray(synthesisRaw)
      ? (synthesisRaw as Record<string, unknown>)
      : {};

  return {
    cards,
    synthesis: {
      mainDisagreement: sanitizeText(pick(synthesisBlock, ['mainDisagreement', 'main_disagreement'])),
      mostUsefulSupplement: sanitizeText(
        pick(synthesisBlock, [
          'mostUsefulSupplementToOriginalReport',
          'most_useful_supplement_to_original_report',
        ])
      ),
      confidenceAdjustment: coerceConfidence(
        pick(synthesisBlock, ['confidenceAdjustment', 'confidence_adjustment'])
      ),
    },
  };
}
