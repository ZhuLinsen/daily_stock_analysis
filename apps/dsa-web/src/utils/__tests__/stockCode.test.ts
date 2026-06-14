import { describe, expect, it } from 'vitest';
import { areStockCodesEquivalent, findMatchingStockCode, includesStockCode, normalizeStockCode } from '../stockCode';

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
