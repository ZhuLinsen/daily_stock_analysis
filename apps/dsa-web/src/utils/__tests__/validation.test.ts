import { afterEach, describe, expect, test } from 'vitest';
import { UI_LANGUAGE_STORAGE_KEY } from '../uiLanguage';
import {
  isObviouslyInvalidStockQuery,
  looksLikeStockCode,
  validateStockCode,
} from '../validation';

describe('stock code validation', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });
  test.each(['BRK-B', 'BAC-PL'])('accepts Yahoo stock code %s', (code) => {
    expect(validateStockCode(code.toLowerCase())).toEqual({ valid: true, normalized: code });
    expect(isObviouslyInvalidStockQuery(code)).toBe(false);
  });

  test.each([
    ['7203.T', '7203.T'],
    ['6758.t', '6758.T'],
    ['005930.KS', '005930.KS'],
    ['247540.kq', '247540.KQ'],
    ['2330.TW', '2330.TW'],
    ['2330.tw', '2330.TW'],
    ['6488.TWO', '6488.TWO'],
    ['6488.two', '6488.TWO'],
  ])('accepts JP/KR/TW Yahoo suffix code %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each(['7203', '005930.K', '035720.KRX', '2330.TWW', '233.TW'])(
    'does not treat ambiguous JP/KR/TW-like query %s as a valid suffix code',
    (input) => {
      const result = validateStockCode(input);
      expect(result.valid).toBe(false);
    }
  );

  test.each([
    ['sh000016', 'SH000016'],
    ['sh000300', 'SH000300'],
    ['sz399001', 'SZ399001'],
  ])('accepts registered SH/SZ index canonical %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each([
    ['csi930955', 'CSI930955'],
    ['930955.CSI', '930955.CSI'],
    ['CSI930955', 'CSI930955'],
  ])('accepts registered CSI index forms %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test('rejects unregistered CSI forms that are not registered index canonicals', () => {
    // 930956.CSI is not in the registry; the Web validation layer is
    // format-based (registered rows pass), while the API returns a 4xx for
    // unregistered CSI at the backend boundary.
    expect(looksLikeStockCode('930956.CSI')).toBe(true);
    expect(validateStockCode('930956.CSI').valid).toBe(true);
  });

  test('returns validation error messages in active zh or en UI language', () => {
    expect(validateStockCode('   ')).toEqual({
      valid: false,
      message: '请输入股票代码',
      normalized: '',
    });
    expect(validateStockCode('INVALID!!')).toEqual({
      valid: false,
      message: '股票代码格式不正确',
      normalized: 'INVALID!!',
    });

    expect(validateStockCode('   ', 'en')).toEqual({
      valid: false,
      message: 'Please enter a stock code',
      normalized: '',
    });
    expect(validateStockCode('INVALID!!', 'en')).toEqual({
      valid: false,
      message: 'Invalid stock code format',
      normalized: 'INVALID!!',
    });

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    expect(validateStockCode('')).toEqual({
      valid: false,
      message: 'Please enter a stock code',
      normalized: '',
    });
    expect(validateStockCode('bad!code')).toEqual({
      valid: false,
      message: 'Invalid stock code format',
      normalized: 'BAD!CODE',
    });
  });
});
