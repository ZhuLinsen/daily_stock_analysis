import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { marketStatusApi } from '../../../api/marketStatus';
import { CurrentMarketStatusBar } from '../CurrentMarketStatusBar';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

vi.mock('../../../api/marketStatus', () => ({
  marketStatusApi: { getStatus: vi.fn() },
}));

const getStatus = vi.mocked(marketStatusApi.getStatus);

describe('CurrentMarketStatusBar', () => {
  beforeEach(() => {
    getStatus.mockReset();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  });

  it('shows open, premarket, and closed states without blocking the dashboard', async () => {
    getStatus.mockResolvedValue({
      generatedAt: '2026-08-14T12:00:00+00:00',
      markets: [
        {
          market: 'cn', phase: 'postmarket', marketLocalTime: '2026-08-14T20:00:00+08:00',
          isTradingDay: true, isMarketOpenNow: false, minutesToOpen: null, minutesToClose: null,
          nextSessionOpen: '2026-08-17T09:30:00+08:00', warnings: [],
        },
        {
          market: 'us', phase: 'premarket', marketLocalTime: '2026-08-14T08:00:00-04:00',
          isTradingDay: true, isMarketOpenNow: false, minutesToOpen: 90, minutesToClose: null,
          nextSessionOpen: '2026-08-14T09:30:00-04:00', warnings: [],
        },
        {
          market: 'hk', phase: 'intraday', marketLocalTime: '2026-08-14T10:00:00+08:00',
          isTradingDay: true, isMarketOpenNow: true, minutesToOpen: null, minutesToClose: 300,
          nextSessionOpen: null, warnings: [],
        },
      ],
    });

    render(<UiLanguageProvider><CurrentMarketStatusBar /></UiLanguageProvider>);

    await waitFor(() => expect(screen.getByText('全球市场')).toBeInTheDocument());
    expect(screen.getByText('A 股')).toBeInTheDocument();
    expect(screen.getByText('已收盘')).toBeInTheDocument();
    expect(screen.getByText('待开盘')).toBeInTheDocument();
    expect(screen.getByText('交易中')).toBeInTheDocument();
  });

  it('stays out of the way when status loading fails', async () => {
    getStatus.mockRejectedValue(new Error('offline'));
    const { container } = render(<UiLanguageProvider><CurrentMarketStatusBar /></UiLanguageProvider>);
    await waitFor(() => expect(getStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
