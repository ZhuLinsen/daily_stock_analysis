const TIMEZONE_OFFSET_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_TIME_WITHOUT_TIMEZONE_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

export function parseDecisionSignalDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const trimmedValue = value.trim();
  if (!trimmedValue) return null;
  const normalizedValue = DATE_TIME_WITHOUT_TIMEZONE_PATTERN.test(trimmedValue) && !TIMEZONE_OFFSET_PATTERN.test(trimmedValue)
    ? `${trimmedValue}Z`
    : trimmedValue;
  const date = new Date(normalizedValue);
  return Number.isNaN(date.getTime()) ? null : date;
}
