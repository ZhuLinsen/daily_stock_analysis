import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWatchlist } from '../useWatchlist';
import { resolveRegisteredIndexCanonical, toAssetAwareCodeKey } from '../../utils/stockCode';

const {
  mockGetWatchlist,
  mockAddToWatchlist,
  mockRemoveFromWatchlist,
} = vi.hoisted(() => ({
  mockGetWatchlist: vi.fn(),
  mockAddToWatchlist: vi.fn(),
  mockRemoveFromWatchlist: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getWatchlist: mockGetWatchlist,
    addToWatchlist: mockAddToWatchlist,
    removeFromWatchlist: mockRemoveFromWatchlist,
  },
}));

describe('useWatchlist', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetWatchlist.mockResolvedValue([]);
    mockAddToWatchlist.mockResolvedValue([]);
    mockRemoveFromWatchlist.mockResolvedValue([]);
  });

  it('matches raw HK watchlist entries against prefixed and suffixed variants', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('00700')).toBe(true);
    expect(result.current.isInWatchlist('HK00700')).toBe(true);
    expect(result.current.isInWatchlist('00700.HK')).toBe(true);
    expect(result.current.isInWatchlist('HK01810')).toBe(false);
  });

  it('requests removal using the selected code and lets the API resolve variants', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.toggleWatchlist('HK00700');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('HK00700');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.watchlistCodes).toEqual([]);
    });
  });

  it('compares submitted and stored US tickers case-insensitively', async () => {
    mockGetWatchlist.mockResolvedValue(['aapl']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('AAPL')).toBe(true);

    await act(async () => {
      await result.current.toggleWatchlist('AAPL');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('AAPL');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
  });

  it('adds and removes the stock while preserving a same-code index', async () => {
    const registry = [{ canonicalCode: 'sh000001', displayCode: 'sh000001', assetType: 'index' }];
    const codeKey = (code: string) => resolveRegisteredIndexCanonical(registry, code) ?? toAssetAwareCodeKey(code);
    mockGetWatchlist.mockResolvedValue(['sh000001']);
    mockAddToWatchlist.mockResolvedValue(['sh000001', '000001']);
    mockRemoveFromWatchlist.mockResolvedValue(['sh000001']);

    const { result } = renderHook(() => useWatchlist(codeKey));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isInWatchlist('000001')).toBe(false);

    await act(async () => {
      await result.current.toggleWatchlist('000001');
    });
    expect(mockAddToWatchlist).toHaveBeenCalledWith('000001');
    expect(result.current.isInWatchlist('000001')).toBe(true);

    await act(async () => {
      await result.current.toggleWatchlist('000001');
    });
    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('000001');
    expect(result.current.watchlistCodes).toEqual(['sh000001']);
  });

  it('matches a legacy Yahoo class-share code when toggling the canonical code', async () => {
    mockGetWatchlist.mockResolvedValue(['BRK-B']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.isInWatchlist('BRK.B')).toBe(true));

    await act(async () => {
      await result.current.toggleWatchlist('BRK.B');
    });
    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('BRK.B');
  });
});
