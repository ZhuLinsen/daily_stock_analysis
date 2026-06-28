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

  test.each(['7203', '005930.K', '035720.KRX'])(
    'does not treat ambiguous JP/KR-like query %s as a valid suffix code',
    (input) => {
      const result = validateStockCode(input);
      expect(result.valid).toBe(false);
    }
  );

  test.each([
    ['TD.TO', 'TD.TO'],
    ['shop.to', 'SHOP.TO'],
    ['ABC.V', 'ABC.V'],
    ['BAM-A.TO', 'BAM-A.TO'], // hyphenated class share
    ['rei-un.to', 'REI-UN.TO'], // hyphenated trust unit
  ])('accepts Canadian TSX/TSX-V suffix code %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({ valid: true, normalized });
    // Documented Canadian codes must not be rejected before reaching the backend.
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each(['TD.TX', 'TD.', '.TO', 'TOOLONGSYMBOLX.TO'])(
    'does not treat invalid Canada-like query %s as a valid suffix code',
    (input) => {
      expect(validateStockCode(input).valid).toBe(false);
    }
  );
});
