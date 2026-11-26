import type React from 'react';
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { formatUiText, UI_TEXT, type UiLanguage, type UiTextKey, type UiTextParams } from '../i18n/uiText';
import { registerActiveTabUiLanguage, resolveActiveUiLanguage, unregisterActiveTabUiLanguage } from '../utils/format';
import { getRuntimeInitialLanguage, getUiLanguageStorage, persistUiLanguage } from '../utils/uiLanguage';

type UiLanguageContextValue = {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: UiTextKey, params?: UiTextParams) => string;
};

const fallbackContext: UiLanguageContextValue = {
  language: 'zh',
  setLanguage: () => undefined,
  t: (key, params) => formatUiText(UI_TEXT.zh[key], params),
};

const UiLanguageContext = createContext<UiLanguageContextValue | null>(null);

export const UiLanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<UiLanguage>(getRuntimeInitialLanguage);
  const [providerId] = useState(() => Symbol('UiLanguageProvider'));
  const previousDocumentLangRef = useRef<string | null>(null);

  registerActiveTabUiLanguage(providerId, language);

  const setLanguage = useCallback((nextLanguage: UiLanguage) => {
    registerActiveTabUiLanguage(providerId, nextLanguage);
    setLanguageState(nextLanguage);
    persistUiLanguage(getUiLanguageStorage(), nextLanguage);
  }, [providerId]);

  useLayoutEffect(() => {
    if (typeof document === 'undefined') {
      return () => {
        unregisterActiveTabUiLanguage(providerId);
      };
    }
    previousDocumentLangRef.current = document.documentElement.lang;
    return () => {
      unregisterActiveTabUiLanguage(providerId);
      if (previousDocumentLangRef.current !== null) {
        document.documentElement.lang = previousDocumentLangRef.current;
      }
    };
  }, [providerId]);

  useLayoutEffect(() => {
    registerActiveTabUiLanguage(providerId, language);
    if (typeof document !== 'undefined') {
      document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    }
  }, [language, providerId]);

  const value = useMemo<UiLanguageContextValue>(() => ({
    language,
    setLanguage,
    t: (key, params) => formatUiText(UI_TEXT[language][key], params),
  }), [language, setLanguage]);

  return (
    <UiLanguageContext.Provider value={value}>
      {children}
    </UiLanguageContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components -- useUiLanguage is a hook, co-located for context access
export function useUiLanguage(): UiLanguageContextValue {
  return useContext(UiLanguageContext) ?? fallbackContext;
}

// eslint-disable-next-line react-refresh/only-export-components -- useActiveUiLanguage is a hook, co-located for context access
export function useActiveUiLanguage(): UiLanguage {
  const context = useContext(UiLanguageContext);
  return context ? context.language : resolveActiveUiLanguage();
}
