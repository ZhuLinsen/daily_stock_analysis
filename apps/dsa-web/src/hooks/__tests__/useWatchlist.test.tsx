import { act, renderHook, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../../contexts/UiLanguageContext';
import { useWatchlist } from '../useWatchlist';
import { resolveRegisteredIndexCanonical, toAssetAwareCodeKey } from '../../utils/stockCode';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';

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
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
    mockGetWatchlist.mockResolvedValue([]);
    mockAddToWatchlist.mockResolvedValue([]);
    mockRemoveFromWatchlist.mockResolvedValue([]);
  });

  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
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

  it('ignores stale getWatchlist response resolving after mutations or newer refreshes', async () => {
    let resolveInitial!: (codes: string[]) => void;
    let resolveRefresh1!: (codes: string[]) => void;
    let resolveRefresh2!: (codes: string[]) => void;
    mockGetWatchlist
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveInitial = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveRefresh1 = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveRefresh2 = resolve;
      }));
    mockAddToWatchlist.mockResolvedValueOnce(['600519']);

    const { result } = renderHook(() => useWatchlist());
    expect(mockGetWatchlist).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.addToWatchlist('600519');
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);

    await act(async () => {
      resolveInitial(['000001']);
      await Promise.resolve();
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);

    await act(async () => {
      void result.current.refresh();
      void result.current.refresh();
      resolveRefresh2(['AAPL']);
      await Promise.resolve();
    });
    expect(result.current.watchlistCodes).toEqual(['AAPL']);

    await act(async () => {
      resolveRefresh1(['STALE']);
      await Promise.resolve();
    });
    expect(result.current.watchlistCodes).toEqual(['AAPL']);
  });

  it('keeps valid initial list and earlier refresh result when concurrent mutation or newer refresh fails', async () => {
    let resolveInitial!: (codes: string[]) => void;
    let resolveRefresh1!: (codes: string[]) => void;
    let rejectRefresh2!: (reason?: unknown) => void;
    mockGetWatchlist
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveInitial = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveRefresh1 = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((_resolve, reject) => {
        rejectRefresh2 = reject;
      }));
    mockAddToWatchlist.mockRejectedValueOnce(new Error('invalid code @@@'));

    const { result } = renderHook(() => useWatchlist());

    await act(async () => {
      await result.current.addToWatchlist('@@@');
    });
    expect(result.current.actionMessage).toBe('操作失败');

    await act(async () => {
      resolveInitial(['600519']);
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.watchlistCodes).toEqual(['600519']);

    let refresh1Promise!: Promise<void>;
    let refresh2Promise!: Promise<void>;
    await act(async () => {
      refresh1Promise = result.current.refresh();
      refresh2Promise = result.current.refresh();
      rejectRefresh2(new Error('temporary network error'));
      await refresh2Promise;
    });

    await act(async () => {
      resolveRefresh1(['600519', '000001']);
      await refresh1Promise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519', '000001']);
  });

  it('ignores stale overlapping refresh after add commits and syncs latest state via follow-up refresh', async () => {
    let resolveAdd!: (codes: string[]) => void;
    let resolveOverlappingRefresh!: (codes: string[]) => void;
    let resolveFollowUpRefresh!: (codes: string[]) => void;
    mockGetWatchlist
      .mockResolvedValueOnce(['600519'])
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveOverlappingRefresh = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveFollowUpRefresh = resolve;
      }));
    mockAddToWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveAdd = resolve;
    }));

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.watchlistCodes).toEqual(['600519']));

    let addPromise!: Promise<void>;
    let overlappingRefreshPromise!: Promise<void>;
    act(() => {
      addPromise = result.current.addToWatchlist('AAPL');
      overlappingRefreshPromise = result.current.refresh();
    });

    await act(async () => {
      resolveAdd(['600519', 'AAPL']);
      await addPromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'AAPL']);
    expect(mockGetWatchlist).toHaveBeenCalledTimes(3);

    // Late pre-write GET snapshot must NOT revert the committed add result.
    await act(async () => {
      resolveOverlappingRefresh(['600519']);
      await overlappingRefreshPromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'AAPL']);

    // Post-commit follow-up refresh still picks up external/cross-tab changes.
    await act(async () => {
      resolveFollowUpRefresh(['600519', 'AAPL', 'MSFT']);
      await Promise.resolve();
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'AAPL', 'MSFT']);
  });

  it('ignores stale overlapping refresh after remove commits and preserves committed state if follow-up fails', async () => {
    let resolveRemove!: (codes: string[]) => void;
    let resolveOverlappingRefresh!: (codes: string[]) => void;
    let rejectFollowUpRefresh!: (reason?: unknown) => void;
    mockGetWatchlist
      .mockResolvedValueOnce(['600519', 'AAPL'])
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveOverlappingRefresh = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((_resolve, reject) => {
        rejectFollowUpRefresh = reject;
      }));
    mockRemoveFromWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveRemove = resolve;
    }));

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.watchlistCodes).toEqual(['600519', 'AAPL']));

    let removePromise!: Promise<void>;
    let overlappingRefreshPromise!: Promise<void>;
    act(() => {
      removePromise = result.current.removeFromWatchlist('AAPL');
      overlappingRefreshPromise = result.current.refresh();
    });

    await act(async () => {
      resolveRemove(['600519']);
      await removePromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);
    expect(result.current.actionMessage).toBe('已从自选移除 AAPL');
    expect(mockGetWatchlist).toHaveBeenCalledTimes(3);

    // Late pre-delete GET snapshot must NOT resurrect the removed code.
    await act(async () => {
      resolveOverlappingRefresh(['600519', 'AAPL']);
      await overlappingRefreshPromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);

    // Follow-up refresh failure keeps committed codes and does not overwrite success message.
    await act(async () => {
      rejectFollowUpRefresh(new Error('network blip'));
      await Promise.resolve();
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);
    expect(result.current.actionMessage).toBe('已从自选移除 AAPL');
  });

  it('does not invalidate an overlapping in-flight refresh when a mutation fails', async () => {
    let rejectAdd!: (reason?: unknown) => void;
    let resolveOverlappingRefresh!: (codes: string[]) => void;
    mockGetWatchlist
      .mockResolvedValueOnce(['600519'])
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveOverlappingRefresh = resolve;
      }));
    mockAddToWatchlist.mockImplementationOnce(() => new Promise<string[]>((_resolve, reject) => {
      rejectAdd = reject;
    }));

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.watchlistCodes).toEqual(['600519']));

    let addPromise!: Promise<void>;
    let overlappingRefreshPromise!: Promise<void>;
    act(() => {
      addPromise = result.current.addToWatchlist('BAD');
      overlappingRefreshPromise = result.current.refresh();
    });

    await act(async () => {
      rejectAdd(new Error('invalid code'));
      await addPromise;
    });
    expect(result.current.actionMessage).toBe('操作失败');
    expect(mockGetWatchlist).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveOverlappingRefresh(['600519', 'MSFT']);
      await overlappingRefreshPromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'MSFT']);
  });

  it('blocks synchronous double mutations and clears message timer on unmount', async () => {
    vi.useFakeTimers();
    try {
      let resolveAdd!: (codes: string[]) => void;
      mockGetWatchlist.mockResolvedValueOnce([]);
      mockAddToWatchlist.mockImplementationOnce(
        () => new Promise<string[]>((resolve) => {
          resolveAdd = resolve;
        }),
      );

      const { result, unmount } = renderHook(() => useWatchlist());
      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        void result.current.addToWatchlist('600519');
        void result.current.toggleWatchlist('600519');
      });

      expect(mockAddToWatchlist).toHaveBeenCalledTimes(1);
      expect(result.current.isActioning).toBe(true);

      await act(async () => {
        resolveAdd(['600519']);
        await Promise.resolve();
      });

      expect(result.current.isActioning).toBe(false);
      expect(result.current.actionMessage).toBe('已加入自选 600519');
      expect(vi.getTimerCount()).toBe(1);

      unmount();
      expect(vi.getTimerCount()).toBe(0);
      vi.advanceTimersByTime(3500);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not let an in-flight pre-write refresh overwrite a subsequent add or remove mutation result', async () => {
    let resolveAdd!: (codes: string[]) => void;
    let resolveRemove!: (codes: string[]) => void;
    let resolveRefresh1!: (codes: string[]) => void;
    let resolveRefresh2!: (codes: string[]) => void;

    mockGetWatchlist
      .mockResolvedValueOnce(['600519'])
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveRefresh1 = resolve;
      }))
      .mockImplementationOnce(() => new Promise<string[]>((resolve) => {
        resolveRefresh2 = resolve;
      }));
    mockAddToWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveAdd = resolve;
    }));
    mockRemoveFromWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveRemove = resolve;
    }));

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.watchlistCodes).toEqual(['600519']));

    let addPromise!: Promise<void>;
    let refreshDuringAdd!: Promise<void>;
    act(() => {
      addPromise = result.current.addToWatchlist('AAPL');
      refreshDuringAdd = result.current.refresh();
    });

    await act(async () => {
      resolveRefresh1(['600519']);
      await refreshDuringAdd;
    });
    await act(async () => {
      resolveAdd(['600519', 'AAPL']);
      await addPromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'AAPL']);

    let removePromise!: Promise<void>;
    let refreshDuringRemove!: Promise<void>;
    act(() => {
      removePromise = result.current.removeFromWatchlist('AAPL');
      refreshDuringRemove = result.current.refresh();
    });

    await act(async () => {
      resolveRefresh2(['600519', 'AAPL']);
      await refreshDuringRemove;
    });
    await act(async () => {
      resolveRemove(['600519']);
      await removePromise;
    });
    expect(result.current.watchlistCodes).toEqual(['600519']);
  });

  it('continues accepting watchlist responses and mutations after React StrictMode remounts', async () => {
    mockGetWatchlist
      .mockResolvedValueOnce(['600519'])
      .mockResolvedValueOnce(['600519'])
      .mockResolvedValueOnce(['600519', 'MSFT']);
    mockAddToWatchlist.mockResolvedValueOnce(['600519', 'MSFT', 'AAPL']);

    const { result } = renderHook(() => useWatchlist(), { wrapper: StrictMode });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.watchlistCodes).toEqual(['600519']);

    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'MSFT']);

    await act(async () => {
      await result.current.addToWatchlist('AAPL');
    });
    expect(result.current.watchlistCodes).toEqual(['600519', 'MSFT', 'AAPL']);
  });

  it('localizes add, remove, and error messages when active UI language is en', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    mockGetWatchlist.mockResolvedValueOnce([]);
    mockAddToWatchlist.mockResolvedValueOnce(['600519']);
    mockRemoveFromWatchlist.mockResolvedValueOnce([]);
    mockAddToWatchlist.mockRejectedValueOnce(new Error('network error'));

    const { result } = renderHook(() => useWatchlist());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.addToWatchlist('600519');
    });
    expect(result.current.actionMessage).toBe('Added 600519 to watchlist');

    await act(async () => {
      await result.current.removeFromWatchlist('600519');
    });
    expect(result.current.actionMessage).toBe('Removed 600519 from watchlist');

    await act(async () => {
      await result.current.addToWatchlist('BAD');
    });
    expect(result.current.actionMessage).toBe('Action failed');
  });

  it('re-localizes watchlist action message when UI language switches mid-mutation and after completion (OR-COR-07f319b1)', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    let resolveAdd!: (codes: string[]) => void;
    let resolveRemove!: (codes: string[]) => void;
    mockGetWatchlist.mockResolvedValueOnce([]);
    mockAddToWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveAdd = resolve;
    }));
    mockRemoveFromWatchlist.mockImplementationOnce(() => new Promise<string[]>((resolve) => {
      resolveRemove = resolve;
    }));

    const { result } = renderHook(
      () => ({ watchlist: useWatchlist(), ui: useUiLanguage() }),
      { wrapper: UiLanguageProvider },
    );
    await waitFor(() => expect(result.current.watchlist.isLoading).toBe(false));

    let addPromise!: Promise<void>;
    act(() => {
      addPromise = result.current.watchlist.addToWatchlist('600519');
    });
    act(() => {
      result.current.ui.setLanguage('en');
    });
    await act(async () => {
      resolveAdd(['600519']);
      await addPromise;
    });
    expect(result.current.watchlist.actionMessage).toBe('Added 600519 to watchlist');

    act(() => {
      result.current.ui.setLanguage('zh');
    });
    expect(result.current.watchlist.actionMessage).toBe('已加入自选 600519');

    let removePromise!: Promise<void>;
    act(() => {
      removePromise = result.current.watchlist.removeFromWatchlist('600519');
    });
    act(() => {
      result.current.ui.setLanguage('en');
    });
    await act(async () => {
      resolveRemove([]);
      await removePromise;
    });
    expect(result.current.watchlist.actionMessage).toBe('Removed 600519 from watchlist');
  });
});
