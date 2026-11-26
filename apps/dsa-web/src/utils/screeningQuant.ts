import type { ScreeningCandidate } from '../api/screening';
import type { UiLanguage } from '../i18n/uiText';
import { SCREENING_TEXT, type ScreeningTextKey } from '../locales/screening';
import { SCREENING_QUANT_TEXT } from '../locales/screeningQuantText';

export type CandidateSortKey =
  | 'default'
  | 'score_desc'
  | 'llm_desc'
  | 'change_desc'
  | 'momentum_desc'
  | 'value_desc'
  | 'stability_desc'
  | 'liquidity_desc';

export type CandidateRiskFilter = 'all' | 'low' | 'medium' | 'high';

export const QUANT_FACTOR_LABEL_KEYS: Record<string, ScreeningTextKey> = {
  value: 'valuation',
  liquidity: 'liquidity',
  momentum: 'momentum',
  reversal: 'reversal',
  activity: 'activity',
  stability: 'stability',
  size: 'size',
  themeHeat: 'themeHeat',
  theme_heat: 'themeHeat',
  topicAlignment: 'topicAlignment',
  topic_alignment: 'topicAlignment',
};

const CANONICAL_FACTOR_KEY_MAP: Record<string, string> = {
  theme_heat: 'themeHeat',
  topic_alignment: 'topicAlignment',
};

export function lookupOwnString(
  record: object,
  key: string,
): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(record, key)) {
    return undefined;
  }
  const value = (record as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : undefined;
}

export function normalizeFactorKey(rawKey: string): string {
  return lookupOwnString(CANONICAL_FACTOR_KEY_MAP, rawKey) ?? rawKey;
}

export function getFactorLabel(language: UiLanguage, key: string): string {
  const labelKey = lookupOwnString(QUANT_FACTOR_LABEL_KEYS, key);
  if (!labelKey) return key;
  return lookupOwnString(SCREENING_TEXT[language], labelKey) ?? key;
}

export function getCandidateExplicitFactorScore(candidate: ScreeningCandidate): number | null {
  if (typeof candidate.screenScore === 'number' && Number.isFinite(candidate.screenScore)) {
    return candidate.screenScore;
  }
  return null;
}

export function compareNullableDesc(
  a: number | null | undefined,
  b: number | null | undefined,
): number {
  const aValid = typeof a === 'number' && Number.isFinite(a);
  const bValid = typeof b === 'number' && Number.isFinite(b);
  if (aValid && bValid) return b - a;
  if (aValid) return -1;
  if (bValid) return 1;
  return 0;
}

export function getCandidateFactorValue(
  candidate: ScreeningCandidate,
  canonicalKey: string,
): number | null {
  const scores = candidate.factorScores;
  if (!scores || typeof scores !== 'object') return null;
  for (const [k, v] of Object.entries(scores)) {
    if (normalizeFactorKey(k) === canonicalKey && typeof v === 'number' && Number.isFinite(v)) {
      return v;
    }
  }
  return null;
}

export function factorBarColorClass(score: number): string {
  if (score >= 75) return 'bg-success';
  if (score >= 55) return 'bg-cyan';
  return 'bg-warning';
}

export function sanitizeFilenameSegment(value: string): string {
  const sanitized = String(value || '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return sanitized || 'custom';
}

export function escapeCsvCell(value: unknown): string {
  const raw = value == null ? '' : String(value);
  const isPlainSignedNumber = /^[+-]?\d+(?:\.\d+)?$/.test(raw);
  const safe =
    !isPlainSignedNumber && (/^[\t\r\n]/.test(raw) || /^\s*[=+\-@]/.test(raw))
      ? `'${raw}`
      : raw;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function exportCandidatesCsv(
  candidates: ScreeningCandidate[],
  strategyId: string,
  language: UiLanguage,
): void {
  if (candidates.length === 0 || typeof window === 'undefined') return;
  const qcopy = SCREENING_QUANT_TEXT[language];
  const copy = SCREENING_TEXT[language];
  const factorKeys = Array.from(
    new Set(
      candidates.flatMap((item) =>
        Object.entries(item.factorScores || {})
          .filter(([, val]) => typeof val === 'number' && Number.isFinite(val))
          .map(([k]) => normalizeFactorKey(k)),
      ),
    ),
  );

  const headers = [
    '#',
    copy.code,
    copy.name,
    copy.industry,
    copy.price,
    copy.change,
    copy.score,
    qcopy.compareFactorScore,
    qcopy.compareLlmScore,
    copy.risk,
    ...factorKeys.map((k) => getFactorLabel(language, k)),
    copy.summary,
  ];

  const rows = candidates.map((item) => {
    const factorComposite = getCandidateExplicitFactorScore(item);
    return [
      item.rank,
      item.code,
      item.name,
      item.industry || '',
      item.price != null ? item.price.toFixed(2) : '',
      item.changePct != null ? item.changePct.toFixed(2) : '',
      item.score != null ? item.score.toFixed(2) : '',
      factorComposite != null ? factorComposite.toFixed(2) : '',
      item.llmScore != null ? item.llmScore.toFixed(2) : '',
      item.riskLevel || '',
      ...factorKeys.map((k) => {
        const v = getCandidateFactorValue(item, k);
        return v != null ? v.toFixed(2) : '';
      }),
      item.reason || '',
    ];
  });

  const csvBody =
    '\uFEFF' +
    [headers, ...rows].map((row) => row.map(escapeCsvCell).join(',')).join('\r\n');
  const blob = new Blob([csvBody], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `screening-${sanitizeFilenameSegment(strategyId)}-${candidates.length}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
