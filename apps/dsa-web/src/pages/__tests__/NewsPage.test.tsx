import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { personalNewsApi } from '../../api/personalNews';
import NewsPage from '../NewsPage';

vi.mock('../../api/personalNews', () => ({
  personalNewsApi: {
    list: vi.fn(),
    providers: vi.fn(),
    watchlist: vi.fn(),
    refresh: vi.fn(),
    refreshStatus: vi.fn(),
    addWatchlist: vi.fn(),
    deleteWatchlist: vi.fn(),
  },
}));

describe('NewsPage page-open refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.mocked(personalNewsApi.list).mockResolvedValue([]);
    vi.mocked(personalNewsApi.providers).mockResolvedValue([]);
    vi.mocked(personalNewsApi.watchlist).mockResolvedValue([{ symbol: '00700.HK', name: '腾讯控股' }]);
    vi.mocked(personalNewsApi.refresh).mockResolvedValue({
      status: 'completed', lastRefreshAt: null, nextAllowedRefreshAt: null, newArticleIds: [],
    });
    vi.mocked(personalNewsApi.refreshStatus).mockResolvedValue({
      status: 'completed', lastRefreshAt: null, nextAllowedRefreshAt: null, newArticleIds: [],
    });
  });

  it('requests one asynchronous refresh per browser session and keeps history usable', async () => {
    const first = render(<MemoryRouter><NewsPage /></MemoryRouter>);

    expect(await screen.findByText('腾讯控股')).toBeInTheDocument();
    await waitFor(() => expect(personalNewsApi.refresh).toHaveBeenCalledWith('page_open'));
    expect(personalNewsApi.refresh).toHaveBeenCalledTimes(1);

    first.unmount();
    render(<MemoryRouter><NewsPage /></MemoryRouter>);
    await screen.findByText('腾讯控股');
    await waitFor(() => expect(personalNewsApi.refreshStatus).toHaveBeenCalled());
    expect(personalNewsApi.refresh).toHaveBeenCalledTimes(1);
  });
});
