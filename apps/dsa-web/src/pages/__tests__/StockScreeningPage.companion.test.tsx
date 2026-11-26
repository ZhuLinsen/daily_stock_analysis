import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UiLanguageToggle } from '../../components/i18n/UiLanguageToggle';
import StockScreeningPage from '../StockScreeningPage';

const {
  getScreeningStatus,
  getStrategies,
  getHotspots,
  getHistory,
} = vi.hoisted(() => ({
  getScreeningStatus: vi.fn(),
  getStrategies: vi.fn(),
  getHotspots: vi.fn(),
  getHistory: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock('../../api/screening', () => ({
  screeningApi: {
    enable: vi.fn(),
    getStatus: () => getScreeningStatus(),
    getHotspotDetail: vi.fn(),
    getHotspots: () => getHotspots(),
    getHistory: () => getHistory(),
    getRun: vi.fn(),
    getStrategies: () => getStrategies(),
    getScreenTask: vi.fn(),
    screen: vi.fn(),
    startScreen: vi.fn(),
  },
}));

describe('StockScreeningPage AlphaSift companion entry', () => {
  beforeEach(() => {
    window.localStorage.clear();
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
      defaultMarket: 'cn',
      markets: ['cn'],
    });
    getStrategies.mockResolvedValue({ enabled: true, strategies: [] });
    getHotspots.mockResolvedValue({ enabled: true, hotspots: [], sourceErrors: [] });
    getHistory.mockResolvedValue({ enabled: true, items: [], total: 0 });
  });

  it('renders a localized external AlphaSift pill with tooltip in the header for zh and en', async () => {
    window.localStorage.setItem('dsa.uiLanguage', 'zh');
    render(
      <UiLanguageProvider>
        <UiLanguageToggle />
        <StockScreeningPage />
      </UiLanguageProvider>,
    );

    const zhLink = await screen.findByRole('link', {
      name: '访问 AlphaSift 每日选股与公开 T+N 纸面跟踪榜单（新窗口打开）',
    });
    expect(zhLink).toHaveAttribute('href', 'https://alphasift.zhulinsen.tech/?lang=zh&utm_source=dsa_web_screening');
    expect(zhLink).toHaveAttribute('target', '_blank');
    expect(zhLink).toHaveAttribute('rel', 'noopener noreferrer');
    expect(zhLink).toHaveTextContent('AlphaSift 今日榜单');

    fireEvent.mouseEnter(zhLink.parentElement!);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('AlphaSift：多市场每日自动选股与公开 T+N 纸面跟踪');
    fireEvent.mouseLeave(zhLink.parentElement!);

    fireEvent.click(screen.getByRole('button', { name: /切换界面语言|Switch UI language/ }));
    const enLink = await screen.findByRole('link', {
      name: 'Open AlphaSift daily stock screener (opens in a new tab)',
    });
    expect(enLink).toHaveAttribute('href', 'https://alphasift.zhulinsen.tech/?lang=en&utm_source=dsa_web_screening');
    expect(enLink).toHaveTextContent('AlphaSift Daily Picks');

    fireEvent.mouseEnter(enLink.parentElement!);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('AlphaSift: multi-market daily screening & public T+N paper track record');
  });
});
