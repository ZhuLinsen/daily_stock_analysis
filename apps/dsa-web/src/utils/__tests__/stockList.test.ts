import { describe, expect, it } from 'vitest';
import { parseStockListValue, serializeStockListValue } from '../stockList';

describe('stockList utils', () => {
  it('parses common copy/paste separators', () => {
    expect(parseStockListValue('600519，300750  hk00700;AAPL、7203.T\n005930.KS')).toEqual([
      '600519',
      '300750',
      'hk00700',
      'AAPL',
      '7203.T',
      '005930.KS',
    ]);
  });

  it('serializes to canonical commas', () => {
    expect(serializeStockListValue('600519，300750\nAAPL')).toBe('600519,300750,AAPL');
  });
});
