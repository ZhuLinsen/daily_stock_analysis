import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { StockSuggestion } from '../../../types/stockIndex';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { SuggestionsList } from '../SuggestionsList';

const buildSuggestions = (): StockSuggestion[] => [
  { canonicalCode: '600519.SH', displayCode: '600519', nameZh: '贵州茅台', market: 'CN', matchType: 'exact', matchField: 'code', score: 100 },
  { canonicalCode: '00700.HK', displayCode: '00700', nameZh: '腾讯控股', market: 'HK', matchType: 'prefix', matchField: 'code', score: 90 },
  { canonicalCode: 'AAPL', displayCode: 'AAPL', nameZh: 'Apple', market: 'US', matchType: 'contains', matchField: 'name', score: 80 },
  { canonicalCode: '7203.T', displayCode: '7203.T', nameZh: 'Toyota', market: 'JP', matchType: 'fuzzy', matchField: 'alias', score: 70 },
  { canonicalCode: '005930.KS', displayCode: '005930.KS', nameZh: 'Samsung', market: 'KR', matchType: 'exact', matchField: 'code', score: 95 },
  { canonicalCode: 'sh000001', displayCode: 'sh000001', nameZh: '上证指数', market: 'INDEX', matchType: 'exact', matchField: 'code', score: 99 },
  { canonicalCode: '510300.SH', displayCode: '510300', nameZh: '沪深300ETF', market: 'ETF', matchType: 'exact', matchField: 'code', score: 98 },
  { canonicalCode: '920493.BJ', displayCode: '920493', nameZh: '北交所示例', market: 'BSE', matchType: 'exact', matchField: 'code', score: 97 },
];

describe('SuggestionsList localization', () => {
  beforeEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  it('renders Chinese market and match-type badges by default', () => {
    render(
      <SuggestionsList
        suggestions={buildSuggestions()}
        highlightedIndex={0}
        onSelect={vi.fn()}
        onMouseEnter={vi.fn()}
      />,
    );

    expect(screen.getByText('A股')).toBeInTheDocument();
    expect(screen.getByText('港股')).toBeInTheDocument();
    expect(screen.getByText('美股')).toBeInTheDocument();
    expect(screen.getByText('北交所')).toBeInTheDocument();
    expect(screen.getAllByText('精确').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('模糊')).toBeInTheDocument();
  });

  it('renders English market and match-type badges when UI language is en', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    render(
      <UiLanguageProvider>
        <SuggestionsList
          suggestions={buildSuggestions()}
          highlightedIndex={0}
          onSelect={vi.fn()}
          onMouseEnter={vi.fn()}
        />
      </UiLanguageProvider>,
    );

    for (const label of ['CN', 'HK', 'US', 'JP', 'KR', 'Index', 'ETF', 'BSE', 'Prefix', 'Contains', 'Fuzzy']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText('Exact').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('A股')).not.toBeInTheDocument();
    expect(screen.queryByText('北交所')).not.toBeInTheDocument();
    expect(screen.queryByText('模糊')).not.toBeInTheDocument();
  });

  it('throws on unsupported or prototype-named markets', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const badBase: StockSuggestion = buildSuggestions()[0];

    expect(() =>
      render(
        <SuggestionsList
          suggestions={[{ ...badBase, market: 'OTC' as never }]}
          highlightedIndex={0}
          onSelect={vi.fn()}
          onMouseEnter={vi.fn()}
        />,
      ),
    ).toThrow('Unsupported market in stock suggestion: OTC');

    expect(() =>
      render(
        <SuggestionsList
          suggestions={[{ ...badBase, market: 'constructor' as never }]}
          highlightedIndex={0}
          onSelect={vi.fn()}
          onMouseEnter={vi.fn()}
        />,
      ),
    ).toThrow('Unsupported market in stock suggestion: constructor');
  });
});
