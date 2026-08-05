import { describe, expect, test } from 'vitest';
import {
  isObviouslyInvalidStockQuery,
  looksLikeStockCode,
  validateStockCode,
} from '../validation';

describe('stock code validation', () => {
  test.each([
    ['7203.T', '7203.T'],
    ['6758.t', '6758.T'],
    ['005930.KS', '005930.KS'],
    ['035720.kq', '035720.KQ'],
  ])('accepts JP/KR Yahoo suffix code %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each(['005930.K', '035720.KRX'])(
    'does not treat ambiguous JP/KR-like query %s as a valid suffix code',
    (input) => {
      const result = validateStockCode(input);
      expect(result.valid).toBe(false);
    }
  );

  test('bare 4-digit 7203 is a valid HK code, not a JP suffix code', () => {
    expect(looksLikeStockCode('7203')).toBe(true);
    expect(validateStockCode('7203').valid).toBe(true);
  });

  test.each(['0001', '0941', '1810'])(
    'accepts bare 4-digit HK code %s',
    (input) => {
      expect(looksLikeStockCode(input)).toBe(true);
      expect(validateStockCode(input)).toEqual({
        valid: true,
        normalized: input,
      });
      expect(isObviouslyInvalidStockQuery(input)).toBe(false);
    }
  );
});
