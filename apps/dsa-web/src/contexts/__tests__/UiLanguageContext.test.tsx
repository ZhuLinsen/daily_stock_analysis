import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  UiLanguageProvider,
} from '../UiLanguageContext';
import {
  getRuntimeInitialLanguage,
  persistUiLanguage,
  resolveInitialUiLanguage,
  UI_LANGUAGE_STORAGE_KEY,
} from '../../utils/uiLanguage';
import { UiLanguageToggle } from '../../components/i18n/UiLanguageToggle';

function createStorage(value: string | null): Storage {
  const store = new Map<string, string>();
  if (value !== null) {
    store.set(UI_LANGUAGE_STORAGE_KEY, value);
  }

  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, nextValue: string) => {
      store.set(key, nextValue);
    },
  };
}

describe('UiLanguageContext', () => {
  it('resolves explicit storage choice before browser language', () => {
    expect(resolveInitialUiLanguage({
      storage: createStorage('zh'),
      navigatorLike: { language: 'en-US', languages: ['en-US'] },
    })).toBe('zh');

    expect(resolveInitialUiLanguage({
      storage: createStorage('en'),
      navigatorLike: { language: 'zh-CN', languages: ['zh-CN'] },
    })).toBe('en');
  });

  it('falls back from invalid storage to the Korean product default', () => {
    expect(resolveInitialUiLanguage({
      storage: createStorage('fr'),
      navigatorLike: { language: 'en-US', languages: ['en-US'] },
    })).toBe('ko');

    expect(resolveInitialUiLanguage({
      storage: createStorage('fr'),
      navigatorLike: { language: 'zh-CN', languages: ['zh-CN', 'en-US'] },
    })).toBe('ko');

    expect(resolveInitialUiLanguage({
      storage: createStorage(null),
      navigatorLike: { language: 'tr-TR', languages: ['tr-TR'] },
    })).toBe('ko');
  });

  it('falls back to Korean if storage getItem throws', () => {
    const throwingStorage = createStorage('en');
    throwingStorage.getItem = () => {
      throw new Error('Storage getItem disabled');
    };

    expect(resolveInitialUiLanguage({
      storage: throwingStorage,
      navigatorLike: { language: 'en-US', languages: ['en-US'] },
    })).toBe('ko');
  });

  it('persists language preference via storage in a safe, non-throwing path', () => {
    const throwingStorage = createStorage('zh');
    throwingStorage.setItem = () => {
      throw new Error('Storage setItem disabled');
    };

    expect(() => persistUiLanguage(throwingStorage, 'en')).not.toThrow();
  });

  it('falls back safely when the localStorage accessor itself throws', () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get: () => {
        throw new Error('localStorage disabled');
      },
    });

    try {
      expect(getRuntimeInitialLanguage()).toBe('ko');
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(window, 'localStorage', originalDescriptor);
      }
    }
  });

  it('switches UI language immediately and persists the explicit choice', () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');

    render(
      <UiLanguageProvider>
        <UiLanguageToggle />
      </UiLanguageProvider>
    );

    const toggle = screen.getByRole('button', { name: '切换界面语言' });
    expect(screen.getByText('中文')).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(localStorage.getItem(UI_LANGUAGE_STORAGE_KEY)).toBe('ko');
    expect(screen.getByRole('button', { name: '화면 언어 변경' })).toBeInTheDocument();
    expect(screen.getByText('한국어')).toBeInTheDocument();
  });
});
