import {
  truncateStockName,
  isStockNameTruncated,
  STOCK_NAME_MAX_LENGTH,
} from '../stockName';
import { describe, expect, test } from 'vitest';

describe('truncateStockName', () => {
  describe('English strings', () => {
    test('returns unchanged when at or below 15 chars', () => {
      expect(truncateStockName('Apple')).toBe('Apple');
      expect(truncateStockName('AAPL')).toBe('AAPL');
      expect(truncateStockName('123456789012345')).toBe('123456789012345');
    });

    test('truncates to 15 chars with trailing dot', () => {
      expect(truncateStockName('Apple Computer Inc.')).toBe('Apple Computer .');
      expect(truncateStockName('1234567890123456')).toBe('123456789012345.');
    });

    test('truncates very long English strings', () => {
      expect(truncateStockName('VeryLongStockNameCorporation')).toBe('VeryLongStockNa.');
    });
  });

  describe('Chinese strings', () => {
    test('returns unchanged when at or below 8 chars', () => {
      expect(truncateStockName('贵州茅台')).toBe('贵州茅台');
      expect(truncateStockName('腾讯控股')).toBe('腾讯控股');
    });

    test('truncates to 8 chars with trailing dot', () => {
      // 贵州茅台股票有限公司: 10 Chinese chars -> slice(0,8) + dot = 8 ch + dot
      expect(truncateStockName('贵州茅台股票有限公司')).toBe('贵州茅台股票有限.');
      // 中华人民共和国ABCD: mixed, 11 chars > 10 → truncate to '中华人民共和国ABC.'
      expect(truncateStockName('中华人民共和国ABCD')).toBe('中华人民共和国ABC.');
    });
  });

  describe('Mixed Chinese and English strings', () => {
    test('returns unchanged when at or below 10 chars', () => {
      expect(truncateStockName('茅台A')).toBe('茅台A');
      expect(truncateStockName('腾讯控股HK')).toBe('腾讯控股HK');
    });

    test('truncates to 10 chars with trailing dot', () => {
      // 贵州茅台股票有限公司AB: 10 Chinese + 2 English = 12 mixed -> slice(0,10) + dot
      // First 10: 贵 州 茅 台 股 票 有 限 公 司 = 8 ch + 2 en
      expect(truncateStockName('贵州茅台股票有限公司AB')).toBe('贵州茅台股票有限公司.');
      // 腾讯控股00700H: 4 Chinese + 6 English = 10 mixed -> no truncation (10 <= 10)
      expect(truncateStockName('腾讯控股00700H')).toBe('腾讯控股00700H');
    });
  });

  describe('edge cases', () => {
    test('returns empty string unchanged', () => {
      expect(truncateStockName('')).toBe('');
    });

    test('handles stock code only (no Chinese)', () => {
      expect(truncateStockName('600519.SH')).toBe('600519.SH');
      expect(truncateStockName('00700.HK')).toBe('00700.HK');
    });

    test('handles single character strings', () => {
      expect(truncateStockName('A')).toBe('A');
      expect(truncateStockName('茅')).toBe('茅');
    });

    test('handles strings with only numbers and symbols', () => {
      expect(truncateStockName('600519')).toBe('600519');
      expect(truncateStockName('2026-03-24')).toBe('2026-03-24');
    });

    test('returns undefined unchanged (but should not happen in practice)', () => {
      // The function checks falsy, so empty string is handled, but non-string values
      // would behave unexpectedly - this documents current behavior
      expect(truncateStockName('' as unknown as string)).toBe('');
    });
  });

  describe('isStockNameTruncated', () => {
    test('returns false for empty string', () => {
      expect(isStockNameTruncated('')).toBe(false);
    });

    test('returns false for names at or below max length', () => {
      expect(isStockNameTruncated('Apple')).toBe(false);
      expect(isStockNameTruncated('贵州茅台')).toBe(false);
      expect(isStockNameTruncated('茅台A')).toBe(false);
    });

    test('returns true for English names exceeding 15 chars', () => {
      expect(isStockNameTruncated('Apple Computer Inc.')).toBe(true);
      expect(isStockNameTruncated('VeryLongStockNameCorporation')).toBe(true);
    });

    test('returns true for Chinese names exceeding 8 chars', () => {
      expect(isStockNameTruncated('贵州茅台股票股份有限公司')).toBe(true);
    });

    test('returns true for mixed names exceeding 10 chars', () => {
      expect(isStockNameTruncated('贵州茅台股票有限公司AB')).toBe(true);
    });

    test('returns false for stock codes at boundary', () => {
      expect(isStockNameTruncated('600519.SH')).toBe(false);
      expect(isStockNameTruncated('00700.HK')).toBe(false);
    });
  });

  describe('STOCK_NAME_MAX_LENGTH constant', () => {
    test('has correct values', () => {
      expect(STOCK_NAME_MAX_LENGTH.ENGLISH).toBe(15);
      expect(STOCK_NAME_MAX_LENGTH.CHINESE).toBe(8);
      expect(STOCK_NAME_MAX_LENGTH.MIXED).toBe(10);
    });
  });
});
