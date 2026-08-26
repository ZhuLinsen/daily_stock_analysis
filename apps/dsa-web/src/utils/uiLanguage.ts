import type { UiLanguage } from '../i18n/uiText';

// Bump the key when changing the product default so existing Chinese/English
// sessions do not silently override the Korean-first deployment preference.
export const UI_LANGUAGE_STORAGE_KEY = 'dsa.uiLanguage.v2';

export function normalizeUiLanguage(value?: string | null): UiLanguage | null {
  if (value === 'ko' || value === 'zh' || value === 'en') {
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

export function resolveInitialUiLanguage({
  storage,
}: {
  storage?: Storage | null;
  // Kept for call-site compatibility. Korean is the product default even
  // when a visitor's browser is configured in another language.
  navigatorLike?: Pick<Navigator, 'language' | 'languages'> | null;
} = {}): UiLanguage {
  const stored = getStoredUiLanguage(storage);
  if (stored) {
    return stored;
  }

  return 'ko';
}

export function getRuntimeInitialLanguage(): UiLanguage {
  if (typeof window === 'undefined') {
    return 'ko';
  }

  return resolveInitialUiLanguage({
    storage: getUiLanguageStorage(),
  });
}
