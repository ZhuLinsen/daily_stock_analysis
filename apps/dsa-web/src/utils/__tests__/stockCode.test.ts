import { describe, expect, it } from 'vitest';
import {
  areAssetAwareCodesEquivalent,
  areStockCodesEquivalent,
  findMatchingStockCode,
  includesStockCode,
  normalizeStockCode,
  resolveRegisteredIndexCanonical,
  toAssetAwareCodeKey,
} from '../stockCode';

describe('normalizeStockCode', () => {
  it('keeps clean A-share codes as-is', () => {
    expect(normalizeStockCode('600519')).toBe('600519');
    expect(normalizeStockCode('000001')).toBe('000001');
    expect(normalizeStockCode('920748')).toBe('920748');
  });

  it('strips SH/SZ prefix', () => {
    expect(normalizeStockCode('SH600519')).toBe('600519');
    expect(normalizeStockCode('SZ000001')).toBe('000001');
    expect(normalizeStockCode('BJ920748')).toBe('920748');
  });

  it('strips dotted SH/SZ/BJ prefix', () => {
    expect(normalizeStockCode('SH.600519')).toBe('600519');
    expect(normalizeStockCode('SZ.000001')).toBe('000001');
    expect(normalizeStockCode('BJ.920748')).toBe('920748');
  });

  it('strips .SH/.SZ/.BJ suffix', () => {
    expect(normalizeStockCode('600519.SH')).toBe('600519');
    expect(normalizeStockCode('000001.SZ')).toBe('000001');
    expect(normalizeStockCode('920748.BJ')).toBe('920748');
  });

  it('normalizes HK prefix to 5-digit form', () => {
    expect(normalizeStockCode('HK00700')).toBe('HK00700');
    expect(normalizeStockCode('HK1810')).toBe('HK01810');
    expect(normalizeStockCode('HK700')).toBe('HK00700');
    expect(normalizeStockCode('hk00700')).toBe('HK00700');
    expect(normalizeStockCode('hk1810')).toBe('HK01810');
  });

  it('normalizes pure 5-digit HK codes to canonical prefix form', () => {
    expect(normalizeStockCode('00700')).toBe('HK00700');
    expect(normalizeStockCode('01810')).toBe('HK01810');
  });

  it('normalizes HK suffix to canonical prefix form', () => {
    expect(normalizeStockCode('00700.HK')).toBe('HK00700');
    expect(normalizeStockCode('1810.HK')).toBe('HK01810');
    expect(normalizeStockCode('700.HK')).toBe('HK00700');
  });

  it('keeps US tickers as-is', () => {
    expect(normalizeStockCode('AAPL')).toBe('AAPL');
    expect(normalizeStockCode('TSLA')).toBe('TSLA');
    expect(normalizeStockCode('GOOGL')).toBe('GOOGL');
    expect(normalizeStockCode('BRK.B')).toBe('BRK.B');
  });

  it('keeps JP/KR Yahoo suffix codes in canonical uppercase suffix form', () => {
    expect(normalizeStockCode('7203.T')).toBe('7203.T');
    expect(normalizeStockCode('6758.t')).toBe('6758.T');
    expect(normalizeStockCode('005930.KS')).toBe('005930.KS');
    expect(normalizeStockCode('035720.kq')).toBe('035720.KQ');
    expect(normalizeStockCode('005930')).toBe('005930');
  });

  it('keeps TW Yahoo suffix codes (.TW / .TWO) in canonical uppercase suffix form', () => {
    expect(normalizeStockCode('2330.tw')).toBe('2330.TW');
    expect(normalizeStockCode('0050.TW')).toBe('0050.TW');
    expect(normalizeStockCode('006208.tw')).toBe('006208.TW');
    expect(normalizeStockCode('6505.two')).toBe('6505.TWO');
    expect(normalizeStockCode('2330')).toBe('2330');
  });

  it('is case-insensitive for prefixes', () => {
    expect(normalizeStockCode('sh600519')).toBe('600519');
    expect(normalizeStockCode('sz000001')).toBe('000001');
  });

  it('handles same-stock variants as equivalent', () => {
    const codes = ['600519', 'SH600519', '600519.SH', 'SH.600519'];
    const normalized = codes.map(normalizeStockCode);
    expect(new Set(normalized).size).toBe(1);
    expect(normalized[0]).toBe('600519');
  });

  it('handles HK variants as equivalent', () => {
    const codes = ['00700', 'HK00700', '00700.HK', 'hk00700'];
    const normalized = codes.map(normalizeStockCode);
    expect(new Set(normalized).size).toBe(1);
    expect(normalized[0]).toBe('HK00700');
  });

  it('compares stock-code variants with both sides normalized', () => {
    expect(areStockCodesEquivalent('00700', 'HK00700')).toBe(true);
    expect(areStockCodesEquivalent('01810', '1810.HK')).toBe(true);
    expect(areStockCodesEquivalent('aapl', 'AAPL')).toBe(true);
    expect(areStockCodesEquivalent('7203.t', '7203.T')).toBe(true);
    expect(areStockCodesEquivalent('005930.ks', '005930.KS')).toBe(true);
    expect(areStockCodesEquivalent('005930', '005930.KS')).toBe(false);
    expect(areStockCodesEquivalent('00700', 'HK01810')).toBe(false);
    expect(areStockCodesEquivalent('', 'HK00700')).toBe(false);
  });

  it('finds raw watchlist entries that match normalized current codes', () => {
    const codes = ['600519', '00700', 'aapl'];

    expect(includesStockCode(codes, '600519.SH')).toBe(true);
    expect(includesStockCode(codes, 'HK00700')).toBe(true);
    expect(includesStockCode(codes, '00700.HK')).toBe(true);
    expect(includesStockCode(codes, 'AAPL')).toBe(true);
    expect(includesStockCode(codes, 'HK01810')).toBe(false);
    expect(findMatchingStockCode(codes, 'HK00700')).toBe('00700');
    expect(findMatchingStockCode(codes, 'AAPL')).toBe('aapl');
  });
});

describe('asset-aware identity keys (PR #2312)', () => {
  const indexRows = [
    { canonicalCode: 'sh000016', displayCode: 'sh000016', aliases: ['000016.SH'], assetType: 'index' },
    { canonicalCode: 'csi930955', displayCode: '930955.CSI', aliases: ['930955.CSI'], assetType: 'index' },
    { canonicalCode: 'sh000300', displayCode: 'sh000300', aliases: ['sz399300', '000300.SH', '000300.CSI'], assetType: 'index' },
    { canonicalCode: '600519.SH', displayCode: '600519', aliases: [], assetType: 'stock' },
  ];

  it('buckets registered indices by lowercase canonical without stock folding', () => {
    expect(toAssetAwareCodeKey('sh000016', 'index')).toBe('sh000016');
    expect(toAssetAwareCodeKey('000016', 'stock')).toBe('000016');
    expect(toAssetAwareCodeKey('sh000016', 'index')).not.toBe(toAssetAwareCodeKey('000016', 'stock'));
  });

  it('case-folds legacy uppercase index codes only and never regex-derives a canonical from aliases', () => {
    // Backend guarantees API/task/report codes tagged assetType=index are
    // already the parser canonical. The frontend only case-folds; it must not
    // fabricate a canonical from prefixes/suffixes (000300.CSI -> csi000300 or
    // sz399300 -> sz399300 would violate the registry single source of truth).
    expect(toAssetAwareCodeKey('SH000016', 'index')).toBe('sh000016');
    expect(toAssetAwareCodeKey('CSI930955', 'index')).toBe('csi930955');
    expect(toAssetAwareCodeKey('000016.SH', 'index')).toBe('000016.sh');
    expect(toAssetAwareCodeKey('000016.SH', 'index')).not.toBe('sh000016');
    expect(toAssetAwareCodeKey('930955.CSI', 'index')).toBe('930955.csi');
    expect(toAssetAwareCodeKey('930955.CSI', 'index')).not.toBe('csi930955');
    expect(toAssetAwareCodeKey('sz399300', 'index')).toBe('sz399300');
    expect(toAssetAwareCodeKey('sz399300', 'index')).not.toBe('sh000300');
    expect(toAssetAwareCodeKey('000300.CSI', 'index')).toBe('000300.csi');
    expect(toAssetAwareCodeKey('000300.CSI', 'index')).not.toBe('csi000300');
    expect(toAssetAwareCodeKey('000300.CSI', 'index')).not.toBe('sh000300');
  });

  it('keeps legacy stock normalization for stock/unknown codes', () => {
    expect(toAssetAwareCodeKey('SH600519', 'stock')).toBe('600519');
    expect(toAssetAwareCodeKey('600519.SH', undefined)).toBe('600519');
    expect(toAssetAwareCodeKey('00700.HK', undefined)).toBe('HK00700');
    expect(toAssetAwareCodeKey('sh600519', undefined)).toBe('600519');
  });

  it('resolves raw codes only through exact registry hits', () => {
    expect(resolveRegisteredIndexCanonical(indexRows, 'sh000016')).toBe('sh000016');
    expect(resolveRegisteredIndexCanonical(indexRows, 'SH000016')).toBe('sh000016');
    expect(resolveRegisteredIndexCanonical(indexRows, '000016.SH')).toBe('sh000016');
    expect(resolveRegisteredIndexCanonical(indexRows, 'sz399300')).toBe('sh000300');
    expect(resolveRegisteredIndexCanonical(indexRows, '000300.CSI')).toBe('sh000300');
    expect(resolveRegisteredIndexCanonical(indexRows, '000300.SH')).toBe('sh000300');
    expect(resolveRegisteredIndexCanonical(indexRows, 'csi000300')).toBeNull();
    expect(resolveRegisteredIndexCanonical(indexRows, '000016')).toBeNull();
    expect(resolveRegisteredIndexCanonical(indexRows, '600519')).toBeNull();
    expect(resolveRegisteredIndexCanonical(indexRows, 'sh600519')).toBeNull();
    expect(resolveRegisteredIndexCanonical([], 'sh000016')).toBeNull();
  });

  it('never folds an index with the same-code stock in equivalence', () => {
    expect(areAssetAwareCodesEquivalent('sh000016', 'index', 'sh000016', 'index')).toBe(true);
    expect(areAssetAwareCodesEquivalent('SH000016', 'index', 'sh000016', 'index')).toBe(true);
    // Alias-form index codes are not canonicalized by the frontend — the backend
    // guarantees canonical output — so an alias form never self-equates to the
    // canonical and never folds with the bare stock either.
    expect(areAssetAwareCodesEquivalent('000016.SH', 'index', 'sh000016', 'index')).toBe(false);
    expect(areAssetAwareCodesEquivalent('000016.SH', 'index', '000016', 'stock')).toBe(false);
    expect(areAssetAwareCodesEquivalent('sh000016', 'index', '000016', 'stock')).toBe(false);
    expect(areAssetAwareCodesEquivalent('SH600519', 'stock', '600519', 'stock')).toBe(true);
    expect(areAssetAwareCodesEquivalent('', 'index', 'sh000016', 'index')).toBe(false);
  });

  it('folds case independently of the host locale (Turkish dotless-i safe)', () => {
    // Simulate the Turkish locale where `toLocaleLowerCase()` maps `I` to
    // dotless `ı` — `CSI930955` would become `csı930955` and never match the
    // registry canonical. The asset-aware helpers must use locale-independent
    // `toLowerCase()` (plain ASCII namespace), so they keep working even when
    // `toLocaleLowerCase` is poisoned.
    const original = String.prototype.toLocaleLowerCase;
    String.prototype.toLocaleLowerCase = function (this: string) {
      return this.replace(/I/g, 'ı').replace(/İ/g, 'i');
    };
    try {
      expect(toAssetAwareCodeKey('CSI930955', 'index')).toBe('csi930955');
      expect(toAssetAwareCodeKey('SH000016', 'index')).toBe('sh000016');
      expect(resolveRegisteredIndexCanonical(indexRows, 'CSI930955')).toBe('csi930955');
      expect(resolveRegisteredIndexCanonical(indexRows, '000300.CSI')).toBe('sh000300');
    } finally {
      String.prototype.toLocaleLowerCase = original;
    }
  });
});
