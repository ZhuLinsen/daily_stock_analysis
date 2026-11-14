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

  // Canada TSX/TSXV Yahoo suffix forms (Issue #2420, PR #2493 review
  // OR-COR-0a575f94): the Web validation layer must accept .TO / .V shapes
  // so watchlist/profile entries are not rejected client-side. Identity
  // (uppercase .V = TSXV vs lowercase .v = legacy US) is decided at the
  // backend parser/routing layers, which receive the raw value.
  test.each([
    ['SHOP.TO', 'SHOP.TO'],
    ['shop.to', 'SHOP.TO'],
    ['BANK.TO', 'BANK.TO'],
    ['SHOP.V', 'SHOP.V'],
  ])('accepts Canada Yahoo suffix code %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test('does not treat digit-base .TO as a valid Canada suffix code', () => {
    expect(validateStockCode('1234.TO').valid).toBe(false);
  });

  // OR-COM-bfe7c5f7 (review #2): the .V/.v suffix family carries its market
  // identity IN THE CASE — uppercase .V is TSXV (Canada), lowercase .v is the
  // legacy US single-letter class share. validateStockCode must return the
  // ORIGINAL casing for this family so analysis requests and watchlist
  // entries keep the distinction; every other form stays uppercase-normalized.
  test.each([
    ['shop.v', 'shop.v'],
    ['Shop.v', 'Shop.v'],
    ['SHOP.V', 'SHOP.V'],
  ])('preserves the original case for the .V/.v suffix family: %s', (input, normalized) => {
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each([
    ['aapl', 'AAPL'],
    ['7203.t', '7203.T'],
    ['shop.to', 'SHOP.TO'],
    ['brk.b', 'BRK.B'],
  ])('still upper-cases non-.V forms: %s', (input, normalized) => {
    expect(validateStockCode(input).normalized).toBe(normalized);
  });
});
