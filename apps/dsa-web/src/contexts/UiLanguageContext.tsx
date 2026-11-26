import type React from 'react';
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { formatUiText, UI_TEXT, type UiLanguage, type UiTextKey, type UiTextParams } from '../i18n/uiText';
import { registerActiveTabUiLanguage, unregisterActiveTabUiLanguage } from '../utils/format';
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
  const providerIdRef = useRef<symbol | null>(null);
  if (!providerIdRef.current) {
    providerIdRef.current = Symbol('UiLanguageProvider');
  }

  const setLanguage = useCallback((nextLanguage: UiLanguage) => {
    setLanguageState(nextLanguage);
    persistUiLanguage(getUiLanguageStorage(), nextLanguage);
  }, []);

  useLayoutEffect(() => {
    const id = providerIdRef.current!;
    registerActiveTabUiLanguage(id, language);
    if (typeof document === 'undefined') {
      return () => {
        unregisterActiveTabUiLanguage(id);
      };
    }
    const previousLang = document.documentElement.lang;
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    return () => {
      unregisterActiveTabUiLanguage(id);
      document.documentElement.lang = previousLang;
    };
  }, [language]);

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
