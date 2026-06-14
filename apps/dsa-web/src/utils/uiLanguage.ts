import type { UiLanguage } from '../i18n/uiText';

export const UI_LANGUAGE_STORAGE_KEY = 'dsa.uiLanguage';

export function normalizeUiLanguage(value?: string | null): UiLanguage | null {
  if (value === 'zh' || value === 'en') {
    return value;
  }
  return null;
}

function getStoredUiLanguage(storage?: Storage | null): UiLanguage | null {
  if (!storage) {
    return null;
  }

  try {
    return normalizeUiLanguage(storage.getItem(UI_LANGUAGE_STORAGE_KEY));
  } catch {
    return null;
  }
}

export function getUiLanguageStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function persistUiLanguage(storage: Storage | null, language: UiLanguage): void {
  if (!storage) {
    return;
  }

  try {
    storage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Ignore storage failures; in-memory language still updates.
  }
}

function getBrowserUiLanguage(navigatorLike?: Pick<Navigator, 'language' | 'languages'> | null): UiLanguage {
  const languageCandidates = [
    ...(Array.isArray(navigatorLike?.languages) ? navigatorLike?.languages ?? [] : []),
    navigatorLike?.language,
  ].filter((language): language is string => Boolean(language));

  for (const candidate of languageCandidates) {
    const normalized = candidate.toLowerCase();
    if (normalized.startsWith('zh')) {
      return 'zh';
    }
    if (normalized.startsWith('en')) {
      return 'en';
    }
  }

  return 'zh';
}

export function resolveInitialUiLanguage({
  storage,
  navigatorLike,
}: {
  storage?: Storage | null;
  navigatorLike?: Pick<Navigator, 'language' | 'languages'> | null;
} = {}): UiLanguage {
  const stored = getStoredUiLanguage(storage);
  if (stored) {
    return stored;
  }

  return getBrowserUiLanguage(navigatorLike);
}

export function getRuntimeInitialLanguage(): UiLanguage {
  if (typeof window === 'undefined') {
    return 'zh';
  }

  return resolveInitialUiLanguage({
    storage: getUiLanguageStorage(),
    navigatorLike: window.navigator,
  });
}
