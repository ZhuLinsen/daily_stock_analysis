/**
 * stockIndexLoader Unit Tests
 *
 * Test stock index loading, parsing, compression, and other functions
 */

import {
  loadStockIndex,
  compressIndex,
  findStockInIndex,
  getPopularStocks,
  groupStocksByMarket,
} from '../stockIndexLoader';
import type { StockIndexItem } from '../../types/stockIndex';
import { beforeEach, describe, expect, test, vi } from 'vitest';

// Mock fetch
const mockFetch = vi.fn();
globalThis.fetch = mockFetch as unknown as typeof fetch;

describe('stockIndexLoader', () => {
  const mockIndexData: StockIndexItem[] = [
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
    {
      canonicalCode: '000001.SZ',
      displayCode: '000001',
      nameZh: '平安银行',
      pinyinFull: 'pinganyinxing',
      pinyinAbbr: 'payh',
      aliases: ['平银'],
      market: 'CN',
      assetType: 'stock',
      active: true,
      popularity: 90,
    },
    {
      canonicalCode: '00700.HK',
      displayCode: '00700',
      nameZh: '腾讯控股',
      pinyinFull: 'tengxunkonggu',
      pinyinAbbr: 'txkg',
      aliases: ['腾讯'],
      market: 'HK',
      assetType: 'stock',
      active: true,
      popularity: 95,
    },
    {
      canonicalCode: 'AAPL.US',
      displayCode: 'AAPL',
      nameZh: '苹果',
      pinyinFull: 'pingguo',
      pinyinAbbr: 'pg',
      aliases: [],
      market: 'US',
      assetType: 'stock',
      active: true,
      popularity: 98,
    },
    {
      canonicalCode: '600000.SH',
      displayCode: '600000',
      nameZh: '浦发银行',
      pinyinFull: 'pufayinxing',
      pinyinAbbr: 'pfyh',
      aliases: ['浦发'],
      market: 'CN',
      assetType: 'stock',
      active: false,
      popularity: 80,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('loadStockIndex - Load stock index', () => {
    test('successfully loads object format index', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockIndexData,
      } as unknown as Response);

      const result = await loadStockIndex();

      expect(result.loaded).toBe(true);
      expect(result.fallback).toBe(false);
      expect(result.data).toEqual(mockIndexData);
      expect(result.error).toBeUndefined();
    });

    test('successfully loads compressed format index (tuple format)', async () => {
      const compressedData = [
        ['600519.SH', '600519', '贵州茅台', 'guizhoumaotai', 'gzmt', ['茅台'], 'CN', 'stock', true, 100],
        ['000001.SZ', '000001', '平安银行', 'pinganyinxing', 'payh', ['平银'], 'CN', 'stock', true, 90],
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => compressedData,
      } as unknown as Response);

      const result = await loadStockIndex();

      expect(result.loaded).toBe(true);
      expect(result.fallback).toBe(false);
      expect(result.data).toHaveLength(2);
      expect(result.data[0].canonicalCode).toBe('600519.SH');
      expect(result.data[0].nameZh).toBe('贵州茅台');
    });

    test('returns fallback mode on network error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const result = await loadStockIndex();

      expect(result.loaded).toBe(false);
      expect(result.fallback).toBe(true);
      expect(result.data).toEqual([]);
      expect(result.error).toBeInstanceOf(Error);
    });

    test('returns fallback mode on HTTP error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      } as unknown as Response);

      const result = await loadStockIndex();

      expect(result.loaded).toBe(false);
      expect(result.fallback).toBe(true);
      expect(result.data).toEqual([]);
      expect(result.error).toBeDefined();
    });

    test('returns fallback mode on JSON parse error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      } as unknown as Response);

      const result = await loadStockIndex();

      expect(result.loaded).toBe(false);
      expect(result.fallback).toBe(true);
      expect(result.data).toEqual([]);
      expect(result.error).toBeDefined();
    });

    test('handles empty array', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      } as unknown as Response);

      const result = await loadStockIndex();

      expect(result.loaded).toBe(true);
      expect(result.fallback).toBe(false);
      expect(result.data).toEqual([]);
    });

    test('fetch call includes cache-busting parameter', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockIndexData,
      } as unknown as Response);

      await loadStockIndex();

      const fetchCallArgs = mockFetch.mock.calls[0][0];
      expect(fetchCallArgs).toContain('?_t=');
    });
  });

  describe('compressIndex - Compress index', () => {
    test('converts object format to tuple format', () => {
      const compressed = compressIndex(mockIndexData);

      expect(compressed).toHaveLength(mockIndexData.length);
      expect(compressed[0]).toEqual([
        '600519.SH',
        '600519',
        '贵州茅台',
        'guizhoumaotai',
        'gzmt',
        ['茅台'],
        'CN',
        'stock',
        true,
        100,
      ]);
    });

    test('handles empty aliases array', () => {
      const itemWithoutAliases: StockIndexItem[] = [
        {
          canonicalCode: 'TEST.US',
          displayCode: 'TEST',
          nameZh: '测试',
          pinyinFull: 'test',
          pinyinAbbr: 'test',
          aliases: [],
          market: 'US',
          assetType: 'stock',
          active: true,
          popularity: 50,
        },
      ];

      const compressed = compressIndex(itemWithoutAliases);

      expect(compressed[0][5]).toEqual([]);
    });

    test('handles undefined aliases', () => {
      const itemWithUndefinedAliases: StockIndexItem[] = [
        {
          canonicalCode: 'TEST.US',
          displayCode: 'TEST',
          nameZh: '测试',
          pinyinFull: 'test',
          pinyinAbbr: 'test',
          aliases: undefined as unknown as string[],
          market: 'US',
          assetType: 'stock',
          active: true,
          popularity: 50,
        },
      ];

      const compressed = compressIndex(itemWithUndefinedAliases);

      expect(compressed[0][5]).toEqual([]);
    });

    test('handles empty array', () => {
      const compressed = compressIndex([]);
      expect(compressed).toEqual([]);
    });
  });

  describe('findStockInIndex - Find stock', () => {
    test('finds existing stock', () => {
      const result = findStockInIndex('600519.SH', mockIndexData);
      expect(result).not.toBeNull();
      expect(result?.canonicalCode).toBe('600519.SH');
      expect(result?.nameZh).toBe('贵州茅台');
    });

    test('returns null for non-existent stock', () => {
      const result = findStockInIndex('NOTFOUND.US', mockIndexData);
      expect(result).toBeNull();
    });

    test('finds inactive stock', () => {
      const result = findStockInIndex('600000.SH', mockIndexData);
      expect(result).not.toBeNull();
      expect(result?.active).toBe(false);
    });

    test('handles empty index', () => {
      const result = findStockInIndex('600519.SH', []);
      expect(result).toBeNull();
    });

    test('case-sensitive search', () => {
      const result = findStockInIndex('600519.sh', mockIndexData);
      expect(result).toBeNull();
    });
  });

  describe('getPopularStocks - Get popular stocks', () => {
    test('sorts by popularity descending', () => {
      const result = getPopularStocks(mockIndexData, 3);

      expect(result).toHaveLength(3);
      expect(result[0].canonicalCode).toBe('600519.SH'); // popularity: 100
      expect(result[1].canonicalCode).toBe('AAPL.US');   // popularity: 98
      expect(result[2].canonicalCode).toBe('00700.HK'); // popularity: 95
    });

    test('filters out inactive stocks', () => {
      const result = getPopularStocks(mockIndexData, 10);

      // 600000.SH is inactive, should not appear
      const hasInactive = result.some(item => !item.active);
      expect(hasInactive).toBe(false);
    });

    test('limits return count', () => {
      const result = getPopularStocks(mockIndexData, 2);
      expect(result.length).toBeLessThanOrEqual(2);
    });

    test('defaults to limit of 20', () => {
      const result = getPopularStocks(mockIndexData);
      expect(result.length).toBeLessThanOrEqual(20);
    });

    test('handles empty index', () => {
      const result = getPopularStocks([]);
      expect(result).toEqual([]);
    });

    test('handles all inactive stocks', () => {
      const inactiveOnly: StockIndexItem[] = [
        {
          canonicalCode: 'TEST.US',
          displayCode: 'TEST',
          nameZh: '测试',
          pinyinFull: 'test',
          pinyinAbbr: 'test',
          aliases: [],
          market: 'US',
          assetType: 'stock',
          active: false,
          popularity: 100,
        },
      ];

      const result = getPopularStocks(inactiveOnly);
      expect(result).toEqual([]);
    });

    test('maintains stable sorting for same popularity', () => {
      const samePopularity: StockIndexItem[] = [
        {
          canonicalCode: 'A.US',
          displayCode: 'A',
          nameZh: 'A',
          pinyinFull: 'a',
          pinyinAbbr: 'a',
          aliases: [],
          market: 'US',
          assetType: 'stock',
          active: true,
          popularity: 100,
        },
        {
          canonicalCode: 'B.US',
          displayCode: 'B',
          nameZh: 'B',
          pinyinFull: 'b',
          pinyinAbbr: 'b',
          aliases: [],
          market: 'US',
          assetType: 'stock',
          active: true,
          popularity: 100,
        },
      ];

      const result = getPopularStocks(samePopularity, 2);
      expect(result).toHaveLength(2);
      expect(result[0].popularity).toBe(100);
      expect(result[1].popularity).toBe(100);
    });
  });

  describe('groupStocksByMarket - Group stocks by market', () => {
    test('groups different markets correctly', () => {
      const result = groupStocksByMarket(mockIndexData);

      expect(result.size).toBe(3); // CN, HK, US
      expect(result.get('CN')).toHaveLength(2);
      expect(result.get('HK')).toHaveLength(1);
      expect(result.get('US')).toHaveLength(1);
    });

    test('filters out inactive stocks', () => {
      const result = groupStocksByMarket(mockIndexData);

      const cnStocks = result.get('CN')!;
      const allActive = cnStocks.every(item => item.active);
      expect(allActive).toBe(true);
    });

    test('handles empty index', () => {
      const result = groupStocksByMarket([]);
      expect(result.size).toBe(0);
    });

    test('handles all inactive stocks', () => {
      const inactiveOnly: StockIndexItem[] = [
        {
          canonicalCode: 'A.US',
          displayCode: 'A',
          nameZh: 'A',
          pinyinFull: 'a',
          pinyinAbbr: 'a',
          aliases: [],
          market: 'US',
          assetType: 'stock',
          active: false,
          popularity: 100,
        },
      ];

      const result = groupStocksByMarket(inactiveOnly);
      expect(result.size).toBe(0);
    });

    test('returns independent arrays for groups', () => {
      const result = groupStocksByMarket(mockIndexData);

      const cnStocks = result.get('CN')!;
      const originalLength = cnStocks.length;

      // Modifying returned array should not affect original data
      cnStocks.pop();

      const result2 = groupStocksByMarket(mockIndexData);
      const cnStocks2 = result2.get('CN')!;

      expect(cnStocks2.length).toBe(originalLength);
    });

    test('maintains order within groups', () => {
      const result = groupStocksByMarket(mockIndexData);

      const cnStocks = result.get('CN')!;
      expect(cnStocks[0].canonicalCode).toBe('600519.SH');
      expect(cnStocks[1].canonicalCode).toBe('000001.SZ');
    });
  });

  describe('Edge case comprehensive tests', () => {
    test('handles very large datasets', () => {
      const largeIndex: StockIndexItem[] = Array.from({ length: 10000 }, (_, i) => ({
        canonicalCode: `TEST${i}.US`,
        displayCode: `TEST${i}`,
        nameZh: `测试${i}`,
        pinyinFull: `test${i}`,
        pinyinAbbr: `t${i}`,
        aliases: [],
        market: 'US',
        assetType: 'stock',
        active: i % 2 === 0,
        popularity: i % 100,
      }));

      expect(() => compressIndex(largeIndex)).not.toThrow();
      expect(() => findStockInIndex('TEST5000.US', largeIndex)).not.toThrow();
      expect(() => getPopularStocks(largeIndex, 10)).not.toThrow();
    });

    test('handles special characters', () => {
      const specialChars: StockIndexItem[] = [
        {
          canonicalCode: 'TEST.US',
          displayCode: 'TEST',
          nameZh: '测试·公司',
          pinyinFull: 'test-gongsi',
          pinyinAbbr: 'test',
          aliases: ['测试(集团)'],
          market: 'US',
          assetType: 'stock',
          active: true,
          popularity: 50,
        },
      ];

      const compressed = compressIndex(specialChars);
      expect(compressed[0][2]).toBe('测试·公司');
      expect(compressed[0][5]).toEqual(['测试(集团)']);
    });
  });
});
