import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import NotFoundPage from '../NotFoundPage';

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('NotFoundPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  it('renders Chinese copy by default and navigates home on click', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );

    expect(document.title).toBe('页面未找到 - DSA');
    expect(screen.getByRole('heading', { name: '页面未找到' })).toBeInTheDocument();
    expect(screen.getByText('抱歉，您访问的页面不存在或已被移动')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '返回首页' }));
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });

  it('renders English copy when UI language is en', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    render(
      <UiLanguageProvider>
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    expect(document.title).toBe('Page not found - DSA');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getByText('The page you requested does not exist or has moved.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Back home' }));
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});
