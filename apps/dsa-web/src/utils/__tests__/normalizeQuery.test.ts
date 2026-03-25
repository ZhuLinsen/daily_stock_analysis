/**
 * normalizeQuery Unit Tests
 *
 * Test various edge cases for query string normalization functions
 */

import {
  normalizeQuery,
  isChineseChar,
  containsChinese,
  extractMarketSuffix,
  removeMarketSuffix,
  normalizeStockCode,
  isStockCodeLike,
  isStockNameLike,
  isPinyinLike,
} from '../normalizeQuery';
import { describe, expect, test } from 'vitest';

describe('normalizeQuery', () => {
  describe('normalizeQuery - Query normalization', () => {
    test('removes leading and trailing spaces', () => {
      expect(normalizeQuery('  600519  ')).toBe('600519');
      expect(normalizeQuery('  茅台  ')).toBe('茅台');
    });

    test('converts to lowercase', () => {
      expect(normalizeQuery('AAPL')).toBe('aapl');
      expect(normalizeQuery('GZMT')).toBe('gzmt');
    });

    test('removes internal extra spaces', () => {
      expect(normalizeQuery('600 519')).toBe('600519');
      expect(normalizeQuery('gui  zhou  mao  tai')).toBe('guizhoumaotai');
    });

    test('combines space and case operations', () => {
      expect(normalizeQuery('  AAPL  US  ')).toBe('aaplus');
    });

    test('normalizes full-width latin characters to ASCII', () => {
      expect(normalizeQuery('万科Ａ')).toBe('万科a');
      expect(normalizeQuery('wkＡ')).toBe('wka');
    });

    test('handles empty strings', () => {
      expect(normalizeQuery('')).toBe('');
      expect(normalizeQuery('   ')).toBe('');
    });

    test('preserves special characters', () => {
      expect(normalizeQuery('600519.SH')).toBe('600519.sh');
      expect(normalizeQuery('00700.HK')).toBe('00700.hk');
    });
  });

  describe('isChineseChar - Chinese character detection', () => {
    test('identifies Chinese characters', () => {
      expect(isChineseChar('茅')).toBe(true);
      expect(isChineseChar('台')).toBe(true);
      expect(isChineseChar('股')).toBe(true);
    });

    test('rejects non-Chinese characters', () => {
      expect(isChineseChar('A')).toBe(false);
      expect(isChineseChar('1')).toBe(false);
      expect(isChineseChar('.')).toBe(false);
      expect(isChineseChar(' ')).toBe(false);
    });

    test('boundary characters: CJK range', () => {
      // 一  (\u4e00)
      expect(isChineseChar('\u4e00')).toBe(true);
      // 龥  (\u9fa5)
      expect(isChineseChar('\u9fa5')).toBe(true);
      // Out of range
      expect(isChineseChar('\u9fa6')).toBe(false);
    });
  });

  describe('containsChinese - Contains Chinese detection', () => {
    test('pure Chinese strings', () => {
      expect(containsChinese('贵州茅台')).toBe(true);
      expect(containsChinese('腾讯')).toBe(true);
    });

    test('mixed Chinese-English strings', () => {
      expect(containsChinese('600519贵州茅台')).toBe(true);
      expect(containsChinese('AAPL苹果')).toBe(true);
    });

    test('pure English strings', () => {
      expect(containsChinese('AAPL')).toBe(false);
      expect(containsChinese('guizhoumaotai')).toBe(false);
    });

    test('pure numeric strings', () => {
      expect(containsChinese('600519')).toBe(false);
      expect(containsChinese('00700')).toBe(false);
    });

    test('empty strings', () => {
      expect(containsChinese('')).toBe(false);
    });
  });

  describe('extractMarketSuffix - Extract market suffix', () => {
    test('extracts A-share market suffix', () => {
      expect(extractMarketSuffix('600519.SH')).toBe('SH');
      expect(extractMarketSuffix('000001.SZ')).toBe('SZ');
    });

    test('extracts HK stock market suffix', () => {
      expect(extractMarketSuffix('00700.HK')).toBe('HK');
    });

    test('extracts US stock market suffix', () => {
      expect(extractMarketSuffix('AAPL.US')).toBe('US');
    });

    test('returns null for no market suffix', () => {
      expect(extractMarketSuffix('600519')).toBeNull();
      expect(extractMarketSuffix('AAPL')).toBeNull();
      expect(extractMarketSuffix('')).toBeNull();
    });

    test('handles multiple dots', () => {
      expect(extractMarketSuffix('600519.SH.TEST')).toBe('TEST');
    });
  });

  describe('removeMarketSuffix - Remove market suffix', () => {
    test('removes A-share market suffix', () => {
      expect(removeMarketSuffix('600519.SH')).toBe('600519');
      expect(removeMarketSuffix('000001.SZ')).toBe('000001');
    });

    test('removes HK stock market suffix', () => {
      expect(removeMarketSuffix('00700.HK')).toBe('00700');
    });

    test('removes US stock market suffix', () => {
      expect(removeMarketSuffix('AAPL.US')).toBe('AAPL');
    });

    test('keeps unchanged without market suffix', () => {
      expect(removeMarketSuffix('600519')).toBe('600519');
      expect(removeMarketSuffix('AAPL')).toBe('AAPL');
    });

    test('handles empty strings', () => {
      expect(removeMarketSuffix('')).toBe('');
    });
  });

  describe('normalizeStockCode - Stock code normalization', () => {
    test('converts to uppercase', () => {
      expect(normalizeStockCode('aapl')).toBe('AAPL');
      expect(normalizeStockCode('gzmt')).toBe('GZMT');
    });

    test('removes spaces', () => {
      expect(normalizeStockCode('600 519')).toBe('600519');
      expect(normalizeStockCode('AAPL US')).toBe('AAPLUS');
    });

    test('preserves market suffix', () => {
      expect(normalizeStockCode('600519.SH')).toBe('600519.SH');
      expect(normalizeStockCode('AAPL.US')).toBe('AAPL.US');
    });

    test('removes leading and trailing spaces', () => {
      expect(normalizeStockCode('  600519.SH  ')).toBe('600519.SH');
    });

    test('combines operations', () => {
      expect(normalizeStockCode('  aapl.us  ')).toBe('AAPL.US');
    });
  });

  describe('isStockCodeLike - Check if looks like stock code', () => {
    test('identifies A-share codes', () => {
      expect(isStockCodeLike('600519')).toBe(true);
      expect(isStockCodeLike('000001')).toBe(true);
      expect(isStockCodeLike('300001')).toBe(true);
    });

    test('identifies codes with market suffix', () => {
      expect(isStockCodeLike('600519.SH')).toBe(true);
      expect(isStockCodeLike('00700.HK')).toBe(true);
      // US stock codes without numbers return false for isStockCodeLike
      expect(isStockCodeLike('AAPL.US')).toBe(false);
    });

    test('handles US stock codes', () => {
      // US stock codes without numbers, isStockCodeLike designed for A-share numeric codes
      expect(isStockCodeLike('AAPL')).toBe(false);
      expect(isStockCodeLike('TSLA')).toBe(false);
      // But pure letters should be identified as pinyin
      expect(isPinyinLike('AAPL')).toBe(true);
      expect(isPinyinLike('TSLA')).toBe(true);
    });

    test('rejects Chinese names', () => {
      expect(isStockCodeLike('贵州茅台')).toBe(false);
      expect(isStockCodeLike('腾讯')).toBe(false);
    });

    test('rejects pinyin', () => {
      expect(isStockCodeLike('gzmt')).toBe(false);
      expect(isStockCodeLike('maotai')).toBe(false);
    });

    test('identifies pure numbers', () => {
      expect(isStockCodeLike('12345')).toBe(true);
    });

    test('handles empty strings', () => {
      expect(isStockCodeLike('')).toBe(false);
    });
  });

  describe('isStockNameLike - Check if looks like stock name', () => {
    test('identifies Chinese names', () => {
      expect(isStockNameLike('贵州茅台')).toBe(true);
      expect(isStockNameLike('腾讯控股')).toBe(true);
      expect(isStockNameLike('平安银行')).toBe(true);
    });

    test('rejects English codes', () => {
      expect(isStockNameLike('AAPL')).toBe(false);
      expect(isStockNameLike('600519')).toBe(false);
    });

    test('rejects pinyin', () => {
      expect(isStockNameLike('guizhoumaotai')).toBe(false);
      expect(isStockNameLike('tengxun')).toBe(false);
    });

    test('identifies mixed Chinese-English', () => {
      expect(isStockNameLike('贵州茅台600519')).toBe(true);
      expect(isStockNameLike('AAPL苹果')).toBe(true);
    });

    test('handles empty strings', () => {
      expect(isStockNameLike('')).toBe(false);
    });
  });

  describe('isPinyinLike - Check if looks like pinyin', () => {
    test('identifies pure pinyin', () => {
      expect(isPinyinLike('guizhoumaotai')).toBe(true);
      expect(isPinyinLike('tengxunkonggu')).toBe(true);
      expect(isPinyinLike('pinganyinxing')).toBe(true);
    });

    test('identifies pinyin abbreviations', () => {
      expect(isPinyinLike('gzmt')).toBe(true);
      expect(isPinyinLike('txkg')).toBe(true);
      expect(isPinyinLike('payh')).toBe(true);
    });

    test('identifies uppercase pinyin', () => {
      expect(isPinyinLike('GZMT')).toBe(true);
      expect(isPinyinLike('MAOTAI')).toBe(true);
    });

    test('rejects numbers', () => {
      expect(isPinyinLike('guizhou123')).toBe(false);
      expect(isPinyinLike('600519')).toBe(false);
    });

    test('rejects Chinese characters', () => {
      expect(isPinyinLike('茅台maotai')).toBe(false);
      expect(isPinyinLike('贵州')).toBe(false);
    });

    test('handles empty strings', () => {
      expect(isPinyinLike('')).toBe(false);
    });

    test('rejects special characters', () => {
      expect(isPinyinLike('maotai-sh')).toBe(false);
      expect(isPinyinLike('ping.an')).toBe(false);
    });
  });

  describe('Edge case comprehensive tests', () => {
    test('null and undefined', () => {
      // TypeScript should catch these at compile time, but runtime needs handling
      expect(() => normalizeQuery(null as unknown as string)).toThrow();
      expect(() => normalizeQuery(undefined as unknown as string)).toThrow();
    });

    test('extra long strings', () => {
      const longString = 'a'.repeat(10000);
      expect(() => normalizeQuery(longString)).not.toThrow();
    });

    test('special Unicode characters', () => {
      expect(normalizeQuery('股票🚀')).toBe('股票🚀');
      expect(normalizeQuery('©2023')).toBe('©2023');
    });
  });
});
