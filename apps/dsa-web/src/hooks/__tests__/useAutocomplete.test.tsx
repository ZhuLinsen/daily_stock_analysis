/**
 * useAutocomplete hook tests.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAutocomplete } from '../useAutocomplete';
import type { StockIndexItem } from '../../types/stockIndex';

const searchStocksMock = vi.fn();

vi.mock('../../utils/searchStocks', () => ({
  searchStocks: (...args: unknown[]) => searchStocksMock(...args),
}));

const mockIndex: StockIndexItem[] = [
  {
    canonicalCode: '600519.SH',
    displayCode: '600519',
    nameZh: '贵州茅台',
    pinyinFull: 'guizhoumaotai',
    pinyinAbbr: 'gzmt',
    aliases: ['茅台'],
    market: 'CN',
    assetType: 'stock',
    active: true,
    popularity: 100,
  },
];

describe('useAutocomplete', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('activates runtime fallback when search throws', () => {
    searchStocksMock.mockImplementation(() => {
      throw new Error('Search exploded');
    });

    const { result } = renderHook(() => useAutocomplete(mockIndex, { debounceMs: 10 }));

    act(() => {
      result.current.setQuery('600519');
    });

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(result.current.runtimeFallback).toBe(true);
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.isOpen).toBe(false);
    expect(result.current.suggestions).toEqual([]);
  });

  it('keeps suggestions open without auto-highlighting the first result', () => {
    searchStocksMock.mockReturnValue([
      {
        canonicalCode: '600519.SH',
        displayCode: '600519',
        nameZh: '贵州茅台',
        market: 'CN',
        matchType: 'exact',
        matchField: 'code',
        score: 100,
      },
    ]);

    const { result } = renderHook(() => useAutocomplete(mockIndex, { debounceMs: 10 }));

    act(() => {
      result.current.setQuery('600519');
    });

    act(() => {
      vi.advanceTimersByTime(10);
    });

    expect(result.current.isOpen).toBe(true);
    expect(result.current.suggestions).toHaveLength(1);
    expect(result.current.highlightedIndex).toBe(-1);
  });

  it('cancels pending debounced search when close, handleSelect, or reset is called', () => {
    searchStocksMock.mockReturnValue([
      {
        canonicalCode: '600519.SH',
        displayCode: '600519',
        nameZh: '贵州茅台',
        market: 'CN',
        matchType: 'exact',
        matchField: 'code',
        score: 100,
      },
    ]);

    const { result } = renderHook(() => useAutocomplete(mockIndex, { debounceMs: 50 }));

    act(() => {
      result.current.setQuery('6005');
      result.current.close();
      vi.advanceTimersByTime(100);
    });

    expect(searchStocksMock).not.toHaveBeenCalled();
    expect(result.current.isOpen).toBe(false);

    act(() => {
      result.current.setQuery('6005');
      result.current.handleSelect({
        canonicalCode: '600519.SH',
        displayCode: '600519',
        nameZh: '贵州茅台',
        market: 'CN',
        matchType: 'exact',
        matchField: 'code',
        score: 100,
      });
      vi.advanceTimersByTime(100);
    });

    expect(searchStocksMock).not.toHaveBeenCalled();
    expect(result.current.query).toBe('600519');
    expect(result.current.isOpen).toBe(false);

    act(() => {
      result.current.setQuery('00700');
      result.current.reset();
      vi.advanceTimersByTime(100);
    });

    expect(searchStocksMock).not.toHaveBeenCalled();
    expect(result.current.query).toBe('');
    expect(result.current.isOpen).toBe(false);
  });

  it('keeps highlightedIndex at -1 when navigating empty suggestions', () => {
    const { result } = renderHook(() => useAutocomplete(mockIndex, { debounceMs: 10 }));

    act(() => {
      result.current.highlightNext();
      result.current.highlightPrevious();
    });

    expect(result.current.highlightedIndex).toBe(-1);
  });

  it('preserves pending debounced search when close({ cancelPendingSearch: false }) is used', () => {
    searchStocksMock.mockReturnValue([
      {
        canonicalCode: '000660.KS',
        displayCode: '000660.KS',
        nameZh: 'SK Hynix',
        market: 'KR',
        matchType: 'contains',
        matchField: 'code',
        score: 60,
      },
    ]);

    const { result } = renderHook(() => useAutocomplete(mockIndex, { debounceMs: 50 }));

    act(() => {
      result.current.setQuery('000660.K');
      result.current.close({ cancelPendingSearch: false });
    });

    expect(result.current.isOpen).toBe(false);

    act(() => {
      vi.advanceTimersByTime(60);
    });

    expect(searchStocksMock).toHaveBeenCalledWith('000660.K', mockIndex, { limit: 10 });
    expect(result.current.isOpen).toBe(true);
    expect(result.current.suggestions[0]?.canonicalCode).toBe('000660.KS');
  });
});
