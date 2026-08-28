import type { ParsedApiError } from '../api/error';

export function toParsedError(error: unknown, title: string, fallbackMessage: string): ParsedApiError {
  if (error && typeof error === 'object' && 'parsedError' in error) {
    const parsed = (error as { parsedError?: ParsedApiError }).parsedError;
    if (parsed) {
      return parsed;
    }
  }
  const message = error instanceof Error && error.message ? error.message : fallbackMessage;
  return { title, message, rawMessage: message, category: 'http_error' };
}

export const MARKET_OPTIONS = [
  { value: 'cn', label: 'A股' },
  { value: 'hk', label: '港股' },
  { value: 'us', label: '美股' },
  { value: 'jp', label: '日股' },
  { value: 'kr', label: '韩股' },
  { value: 'tw', label: '台股' },
];

export const EMOTION_OPTIONS = [
  { value: 'excited', labelKey: 'journal.emotion.excited' },
  { value: 'calm', labelKey: 'journal.emotion.calm' },
  { value: 'fearful', labelKey: 'journal.emotion.fearful' },
  { value: 'fomo', labelKey: 'journal.emotion.fomo' },
  { value: 'neutral', labelKey: 'journal.emotion.neutral' },
  { value: 'regretful', labelKey: 'journal.emotion.regretful' },
] as const;
