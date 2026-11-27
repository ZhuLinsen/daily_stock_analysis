import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { getParsedApiError } from '../../../api/error';
import { UiLanguageProvider, useUiLanguage } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { ApiErrorAlert } from '../ApiErrorAlert';

const AlertHarness = ({ error }: { error: ReturnType<typeof getParsedApiError> }) => {
  const { setLanguage } = useUiLanguage();
  return (
    <div>
      <button type="button" onClick={() => setLanguage('en')}>
        switch-en
      </button>
      <button type="button" onClick={() => setLanguage('zh')}>
        switch-zh
      </button>
      <ApiErrorAlert error={error} />
    </div>
  );
};

describe('ApiErrorAlert', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
  });

  it('re-localizes settled ParsedApiError when UI language switches', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    const error = getParsedApiError({ code: 'ERR_NETWORK', message: 'Network Error' });

    render(
      <UiLanguageProvider>
        <AlertHarness error={error} />
      </UiLanguageProvider>,
    );

    expect(screen.getByText('无法连接到本地服务')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'switch-en' }));

    const alert = screen.getByRole('alert');
    expect(screen.getByText('Cannot Connect to Local Service')).toBeInTheDocument();
    expect(alert.textContent).not.toMatch(/[\u4e00-\u9fff]/);

    fireEvent.click(screen.getByRole('button', { name: 'switch-zh' }));

    expect(screen.getByText('无法连接到本地服务')).toBeInTheDocument();
  });
});
