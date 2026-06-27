export function formatNumber(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

export function formatCompactNumber(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${formatNumber(value / 100000000, digits)}亿`;
  if (abs >= 10000) return `${formatNumber(value / 10000, digits)}万`;
  return formatNumber(value, digits);
}

export function formatPercent(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${formatNumber(value, 2)}%`;
}

export function formatAmountYi(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const normalized = Math.abs(value) >= 100000000 ? value / 100000000 : value;
  return `${formatNumber(normalized, Math.abs(normalized) >= 100 ? 0 : 2)}亿`;
}

export function signedClass(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-secondary-text';
  if (value > 0) return 'text-red-500 dark:text-red-300';
  if (value < 0) return 'text-emerald-600 dark:text-emerald-300';
  return 'text-secondary-text';
}

export function clamp(value: number, min = 0, max = 100): number {
  return Math.min(max, Math.max(min, value));
}
