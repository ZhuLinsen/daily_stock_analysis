/**
 * StockAutocomplete component tests.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { StockAutocomplete } from '../StockAutocomplete';
import type { UseAutocompleteResult } from '../../../hooks/useAutocomplete';
import type { StockIndexItem, StockSuggestion } from '../../../types/stockIndex';

let stockIndexHookImpl: () => {
  index: StockIndexItem[];
  loading: boolean;
  fallback: boolean;
  error: Error | null;
  loaded: boolean;
};

let useRealAutocomplete = false;
let autocompleteHookImpl: () => UseAutocompleteResult;

// Mock the hooks
vi.mock('../../../hooks/useStockIndex', () => ({
  useStockIndex: () => stockIndexHookImpl(),
}));

vi.mock('../../../hooks/useAutocomplete', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/useAutocomplete')>();
  return {
    useAutocomplete: (index: StockIndexItem[]) =>
      (useRealAutocomplete ? actual.useAutocomplete(index) : autocompleteHookImpl()),
  };
});

const mockIndex: StockIndexItem[] = [
  {
    canonicalCode: "600519.SH",
    displayCode: "600519",
    nameZh: "贵州茅台",
    pinyinFull: "guizhoumaotai",
    pinyinAbbr: "gzmt",
    aliases: ["茅台"],
    market: "CN",
    assetType: "stock",
    active: true,
    popularity: 100,
  },
];

const mockSuggestions: StockSuggestion[] = [
  {
    canonicalCode: "600519.SH",
    displayCode: "600519",
    nameZh: "贵州茅台",
    market: "CN",
    matchType: "exact" as const,
    matchField: "code" as const,
    score: 100,
  },
];

const hkSuggestion = {
  canonicalCode: "00700.HK",
  displayCode: "00700",
  nameZh: "腾讯控股",
  market: "HK" as const,
  matchType: "exact" as const,
  matchField: "code" as const,
  score: 100,
};

const bseSuggestion = {
  canonicalCode: "920493.BJ",
  displayCode: "920493",
  nameZh: "示例北交所股票",
  market: "BSE" as const,
  matchType: "exact" as const,
  matchField: "code" as const,
  score: 100,
};

const krSuggestion = {
  canonicalCode: "000660.KS",
  displayCode: "000660.KS",
  nameZh: "SK Hynix",
  market: "KR" as const,
  matchType: "contains" as const,
  matchField: "code" as const,
  score: 60,
};

const jpSuggestion = {
  canonicalCode: "7203.T",
  displayCode: "7203.T",
  nameZh: "ソニーグループ",
  market: "JP" as const,
  matchType: "contains" as const,
  matchField: "code" as const,
  score: 60,
};

describe('StockAutocomplete', () => {
  const mockOnChange = vi.fn();
  const mockOnSubmit = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useRealAutocomplete = false;
    stockIndexHookImpl = () => ({
      index: mockIndex,
      loading: false,
      fallback: false,
      error: null,
      loaded: true,
    });
    autocompleteHookImpl = () => ({
      query: '',
      setQuery: vi.fn(),
      suggestions: mockSuggestions,
      isOpen: false,
      highlightedIndex: -1,
      setHighlightedIndex: vi.fn(),
      highlightPrevious: vi.fn(),
      highlightNext: vi.fn(),
      handleSelect: vi.fn(),
      close: vi.fn(),
      reset: vi.fn(),
      isComposing: false,
      setIsComposing: vi.fn(),
      runtimeFallback: false,
      error: null,
    });
  });

  it('renders the input element', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByPlaceholderText(/输入股票代码或名称/);
    expect(input).toBeInTheDocument();
  });

  it('renders a custom placeholder', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        placeholder="请输入代码"
      />
    );

    const input = screen.getByPlaceholderText(/请输入代码/);
    expect(input).toBeInTheDocument();
  });

  it('renders the current value', () => {
    render(
      <StockAutocomplete
        value="600519"
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByDisplayValue('600519');
    expect(input).toBeInTheDocument();
  });

  it('supports the disabled state', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        disabled={true}
      />
    );

    const input = screen.getByRole('combobox');
    expect(input).toBeDisabled();
  });

  it('calls onChange when the input changes', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: '600519' } });

    expect(mockOnChange).toHaveBeenCalledWith('600519');
  });

  it('applies a custom class name', () => {
    const { container } = render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        className="custom-class"
      />
    );

    const input = container.querySelector('.custom-class');
    expect(input).toBeInTheDocument();
  });

  it('exposes the expected accessibility attributes', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
      />
    );

    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('aria-autocomplete', 'none');
    expect(input).toHaveAttribute('role', 'combobox');
  });

  it('applies an accessible label to the autocomplete input', () => {
    render(
      <StockAutocomplete
        value=""
        onChange={mockOnChange}
        onSubmit={mockOnSubmit}
        ariaLabel="当前股票"
      />
    );

    expect(screen.getByLabelText('当前股票')).toBeInTheDocument();
  });

  describe('fallback mode', () => {
    it('renders a plain input when index loading fallback is active', () => {
      stockIndexHookImpl = () => ({
        index: [],
        loading: false,
        fallback: true,
        error: new Error('Index load failed'),
        loaded: false,
      });

      render(
        <StockAutocomplete
          value=""
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByPlaceholderText(/输入股票代码或名称/);
      expect(input).toHaveAttribute('data-autocomplete-mode', 'fallback');
    });

    it('renders a plain input when autocomplete runtime fallback is active', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [],
        isOpen: false,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: true,
        error: new Error('Search crashed'),
      });

      render(
        <StockAutocomplete
          value=""
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByPlaceholderText(/输入股票代码或名称/);
      expect(input).toHaveAttribute('data-autocomplete-mode', 'fallback');
    });

    it('submits manually when fallback input receives Enter', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [],
        isOpen: false,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: true,
        error: new Error('Search crashed'),
      });

      render(
        <StockAutocomplete
          value="600519"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('600519');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnSubmit).toHaveBeenCalledWith('600519');
    });

    it('applies an accessible label to the fallback input', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [],
        isOpen: false,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: true,
        error: new Error('Search crashed'),
      });

      render(
        <StockAutocomplete
          value=""
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
          ariaLabel="当前股票"
        />
      );

      expect(screen.getByLabelText('当前股票')).toHaveAttribute('data-autocomplete-mode', 'fallback');
    });

    it('prevents duplicate form submission when fallback input receives Enter', () => {
      const formSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [],
        isOpen: false,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: true,
        error: new Error('Search crashed'),
      });

      render(
        <form onSubmit={formSubmit}>
          <StockAutocomplete
            value="600519"
            onChange={mockOnChange}
            onSubmit={mockOnSubmit}
          />
        </form>
      );

      fireEvent.keyDown(screen.getByDisplayValue('600519'), { key: 'Enter' });

      expect(mockOnSubmit).toHaveBeenCalledTimes(1);
      expect(formSubmit).not.toHaveBeenCalled();
    });
  });

  describe('IME support', () => {
    it('handles composition start and end events', () => {
      render(
        <StockAutocomplete
          value=""
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByRole('combobox');

      fireEvent.compositionStart(input);
      fireEvent.compositionEnd(input);

      // The events should be handled without throwing.
      expect(input).toBeInTheDocument();
    });
  });

  describe('keyboard submission', () => {
    it('submits the raw input when suggestions are open but nothing is highlighted', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: mockSuggestions,
        isOpen: true,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('6005');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnSubmit).toHaveBeenCalledWith('6005');
    });

    it('submits the highlighted suggestion when one is explicitly selected', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: mockSuggestions,
        isOpen: true,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('6005');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('600519');
      expect(mockOnSubmit).toHaveBeenCalledWith('600519.SH', '贵州茅台', 'autocomplete', {
        market: 'CN',
        displayCode: '600519',
      });
    });

    it('submits the highlighted HK suggestion using the canonical .HK code', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [hkSuggestion],
        isOpen: true,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="00700"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('00700');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('00700');
      expect(mockOnSubmit).toHaveBeenCalledWith('00700.HK', '腾讯控股', 'autocomplete', {
        market: 'HK',
        displayCode: '00700',
      });
    });

    it('submits the highlighted BSE suggestion using the canonical .BJ code', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [bseSuggestion],
        isOpen: true,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="920493"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('920493');
      fireEvent.keyDown(input, { key: 'Enter' });

      expect(mockOnChange).toHaveBeenCalledWith('920493');
      expect(mockOnSubmit).toHaveBeenCalledWith('920493.BJ', '示例北交所股票', 'autocomplete', {
        market: 'BSE',
        displayCode: '920493',
      });
    });
  });

  describe('runtime boundary', () => {
    it('renders KR suggestions without falling back to plain input', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [krSuggestion],
        isOpen: true,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="000660"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('000660');
      fireEvent.focus(input);

      expect(input).not.toHaveAttribute('data-autocomplete-mode', 'fallback');
      expect(screen.getByText('000660.KS')).toBeInTheDocument();
    });

    it('renders KR and JP market badges in the suggestion list', () => {
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [krSuggestion, jpSuggestion],
        isOpen: true,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="000660"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('000660');
      fireEvent.focus(input);

      expect(screen.getByText('韩股')).toBeInTheDocument();
      expect(screen.getByText('日股')).toBeInTheDocument();
      expect(screen.getByText('000660.KS')).toBeInTheDocument();
      expect(screen.getByText('7203.T')).toBeInTheDocument();
    });

    it('falls back to the plain input when the autocomplete tree throws during render', () => {
      autocompleteHookImpl = () => {
        throw new Error('Autocomplete render failed');
      };

      render(
        <StockAutocomplete
          value="META"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('META');
      expect(input).toHaveAttribute('data-autocomplete-mode', 'fallback');
    });

    it('falls back to the plain input when a suggestion contains an unsupported market', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      autocompleteHookImpl = () => ({
        query: '',
        setQuery: vi.fn(),
        suggestions: [
          {
            canonicalCode: 'TEST.OTC',
            displayCode: 'TEST',
            nameZh: '测试市场',
            market: 'OTC' as never,
            matchType: 'exact' as const,
            matchField: 'code' as const,
            score: 100,
          },
        ],
        isOpen: true,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: vi.fn(),
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="TEST"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('TEST');
      fireEvent.focus(input);

      const fallbackInput = screen.getByDisplayValue('TEST');
      expect(fallbackInput).toHaveAttribute('data-autocomplete-mode', 'fallback');
      expect(consoleErrorSpy).toHaveBeenCalled();
      consoleErrorSpy.mockRestore();
    });
  });

  describe('selection and timer lifecycle', () => {
    it('syncs prevValueRef on click selection so parent value update does not re-trigger search', async () => {
      const setQueryMock = vi.fn();
      const handleSelectMock = vi.fn();
      const closeMock = vi.fn();
      autocompleteHookImpl = () => ({
        query: '茅台',
        setQuery: setQueryMock,
        suggestions: mockSuggestions,
        isOpen: true,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: handleSelectMock,
        close: closeMock,
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      const { rerender } = render(
        <StockAutocomplete
          value="茅台"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      fireEvent.click(await screen.findByText('贵州茅台'));

      expect(handleSelectMock).toHaveBeenCalledWith(mockSuggestions[0]);
      expect(closeMock).toHaveBeenCalledTimes(1);
      expect(mockOnChange).toHaveBeenCalledWith('600519');
      expect(mockOnSubmit).toHaveBeenCalledWith('600519.SH', '贵州茅台', 'autocomplete', {
        market: 'CN',
        displayCode: '600519',
      });
      expect(setQueryMock).not.toHaveBeenCalled();

      rerender(
        <StockAutocomplete
          value="600519"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );
      expect(setQueryMock).not.toHaveBeenCalled();

      rerender(
        <StockAutocomplete
          value="00700"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );
      expect(setQueryMock).toHaveBeenCalledWith('00700');
    });

    it('does not prematurely close the dropdown when submitting raw input on Enter without highlight', () => {
      const closeMock = vi.fn();
      autocompleteHookImpl = () => ({
        query: '6005',
        setQuery: vi.fn(),
        suggestions: mockSuggestions,
        isOpen: true,
        highlightedIndex: -1,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: vi.fn(),
        highlightNext: vi.fn(),
        handleSelect: vi.fn(),
        close: closeMock,
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      fireEvent.keyDown(screen.getByDisplayValue('6005'), { key: 'Enter' });

      expect(closeMock).not.toHaveBeenCalled();
      expect(mockOnSubmit).toHaveBeenCalledWith('6005');
    });

    it('cancels pending blur close timer on refocus, typing, and unmount', () => {
      vi.useFakeTimers();
      try {
        const closeMock = vi.fn();
        autocompleteHookImpl = () => ({
          query: '6005',
          setQuery: vi.fn(),
          suggestions: mockSuggestions,
          isOpen: true,
          highlightedIndex: -1,
          setHighlightedIndex: vi.fn(),
          highlightPrevious: vi.fn(),
          highlightNext: vi.fn(),
          handleSelect: vi.fn(),
          close: closeMock,
          reset: vi.fn(),
          isComposing: false,
          setIsComposing: vi.fn(),
          runtimeFallback: false,
          error: null,
        });

        const { unmount } = render(
          <StockAutocomplete
            value="6005"
            onChange={mockOnChange}
            onSubmit={mockOnSubmit}
          />
        );

        const input = screen.getByDisplayValue('6005');

        fireEvent.blur(input);
        act(() => {
          vi.advanceTimersByTime(100);
        });
        fireEvent.focus(input);
        act(() => {
          vi.advanceTimersByTime(250);
        });
        expect(closeMock).not.toHaveBeenCalled();

        fireEvent.blur(input);
        act(() => {
          vi.advanceTimersByTime(100);
        });
        fireEvent.change(input, { target: { value: '60051' } });
        act(() => {
          vi.advanceTimersByTime(250);
        });
        expect(closeMock).not.toHaveBeenCalled();

        fireEvent.blur(input);
        unmount();
        act(() => {
          vi.advanceTimersByTime(250);
        });
        expect(closeMock).not.toHaveBeenCalled();
      } finally {
        useRealAutocomplete = false;
        vi.useRealTimers();
      }
    });

    it('ignores ArrowDown/ArrowUp and submits raw value on Enter when dropdown is closed', () => {
      const highlightNextMock = vi.fn();
      const highlightPreviousMock = vi.fn();
      const closeMock = vi.fn();
      const handleSelectMock = vi.fn();
      autocompleteHookImpl = () => ({
        query: '6005',
        setQuery: vi.fn(),
        suggestions: mockSuggestions,
        isOpen: false,
        highlightedIndex: 0,
        setHighlightedIndex: vi.fn(),
        highlightPrevious: highlightPreviousMock,
        highlightNext: highlightNextMock,
        handleSelect: handleSelectMock,
        close: closeMock,
        reset: vi.fn(),
        isComposing: false,
        setIsComposing: vi.fn(),
        runtimeFallback: false,
        error: null,
      });

      render(
        <StockAutocomplete
          value="6005"
          onChange={mockOnChange}
          onSubmit={mockOnSubmit}
        />
      );

      const input = screen.getByDisplayValue('6005');
      fireEvent.keyDown(input, { key: 'ArrowDown' });
      fireEvent.keyDown(input, { key: 'ArrowUp' });
      expect(highlightNextMock).not.toHaveBeenCalled();
      expect(highlightPreviousMock).not.toHaveBeenCalled();

      fireEvent.keyDown(input, { key: 'Enter' });
      expect(handleSelectMock).not.toHaveBeenCalled();
      expect(closeMock).not.toHaveBeenCalled();
      expect(mockOnSubmit).toHaveBeenCalledWith('6005');
    });

    it('keeps debounced suggestions alive when Enter submits an incomplete input within the debounce window', () => {
      vi.useFakeTimers();
      try {
        stockIndexHookImpl = () => ({
          index: [
            ...mockIndex,
            {
              canonicalCode: '000660.KS',
              displayCode: '000660.KS',
              nameZh: 'SK Hynix',
              pinyinFull: 'skhynix',
              pinyinAbbr: 'skhl',
              aliases: ['海力士'],
              market: 'KR',
              assetType: 'stock',
              active: true,
              popularity: 80,
            },
            {
              canonicalCode: 'AAPL',
              displayCode: 'AAPL',
              nameZh: '苹果',
              pinyinFull: 'pingguo',
              pinyinAbbr: 'pg',
              aliases: ['Apple'],
              market: 'US',
              assetType: 'stock',
              active: true,
              popularity: 95,
            },
          ],
          loading: false,
          fallback: false,
          error: null,
          loaded: true,
        });
        useRealAutocomplete = true;

        const rejectedSubmit = vi.fn();
        function ControlledHarness() {
          const [val, setVal] = useState('');
          return (
            <StockAutocomplete
              value={val}
              onChange={setVal}
              onSubmit={(...args) => {
                rejectedSubmit(...args);
                if (args[1] || args[2] === 'autocomplete') {
                  mockOnSubmit(...args);
                }
              }}
            />
          );
        }

        render(<ControlledHarness />);

        const input = screen.getByRole('combobox');
        fireEvent.change(input, { target: { value: '000660.K' } });

        act(() => {
          vi.advanceTimersByTime(50);
        });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(rejectedSubmit).toHaveBeenCalledWith('000660.K');

        act(() => {
          vi.advanceTimersByTime(250);
        });
        act(() => {
          vi.advanceTimersByTime(20);
        });

        const matchItem = screen.getByText('SK Hynix');
        expect(matchItem).toBeInTheDocument();

        fireEvent.click(matchItem);
        expect(mockOnSubmit).toHaveBeenCalledWith('000660.KS', 'SK Hynix', 'autocomplete', {
          market: 'KR',
          displayCode: '000660.KS',
        });
      } finally {
        useRealAutocomplete = false;
        vi.useRealTimers();
      }
    });

    it('keeps already-open suggestions visible when Enter submits an unhighlighted rejected input and closes on cleared value', () => {
      vi.useFakeTimers();
      try {
        stockIndexHookImpl = () => ({
          index: [
            ...mockIndex,
            {
              canonicalCode: '000660.KS',
              displayCode: '000660.KS',
              nameZh: 'SK Hynix',
              pinyinFull: 'skhynix',
              pinyinAbbr: 'skhl',
              aliases: ['海力士'],
              market: 'KR',
              assetType: 'stock',
              active: true,
              popularity: 80,
            },
            {
              canonicalCode: 'AAPL',
              displayCode: 'AAPL',
              nameZh: '苹果',
              pinyinFull: 'pingguo',
              pinyinAbbr: 'pg',
              aliases: ['Apple'],
              market: 'US',
              assetType: 'stock',
              active: true,
              popularity: 95,
            },
          ],
          loading: false,
          fallback: false,
          error: null,
          loaded: true,
        });
        useRealAutocomplete = true;

        const rejectedSubmit = vi.fn();
        function ControlledHarness() {
          const [val, setVal] = useState('');
          return (
            <StockAutocomplete
              value={val}
              onChange={setVal}
              onSubmit={(code, name, source, extra) => {
                rejectedSubmit(code);
                if (name || source === 'autocomplete') {
                  mockOnSubmit(code, name, source, extra);
                } else if (code === 'RESET_ME') {
                  setVal('');
                }
              }}
            />
          );
        }

        render(<ControlledHarness />);

        const input = screen.getByRole('combobox');
        fireEvent.change(input, { target: { value: '000660.K' } });

        act(() => {
          vi.advanceTimersByTime(250);
        });
        act(() => {
          vi.advanceTimersByTime(20);
        });

        expect(screen.getByText('SK Hynix')).toBeInTheDocument();

        fireEvent.keyDown(input, { key: 'Enter' });
        expect(rejectedSubmit).toHaveBeenCalledWith('000660.K');
        expect(screen.getByText('SK Hynix')).toBeInTheDocument();

        fireEvent.click(screen.getByText('SK Hynix'));
        expect(mockOnSubmit).toHaveBeenCalledWith('000660.KS', 'SK Hynix', 'autocomplete', {
          market: 'KR',
          displayCode: '000660.KS',
        });

        fireEvent.change(input, { target: { value: 'RESET_ME' } });
        act(() => {
          vi.advanceTimersByTime(250);
        });
        act(() => {
          vi.advanceTimersByTime(20);
        });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(input).toHaveValue('');
        expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

        // Regression test for OR-COR-0a29a1a7: clearing an open dropdown and pasting another
        // ticker within the debounce window must reopen and position the listbox when results arrive.
        fireEvent.change(input, { target: { value: '000660.K' } });
        act(() => {
          vi.advanceTimersByTime(250);
        });
        act(() => {
          vi.advanceTimersByTime(20);
        });
        expect(screen.getByRole('listbox')).toBeInTheDocument();
        expect(screen.getByText('SK Hynix')).toBeInTheDocument();

        fireEvent.change(input, { target: { value: '' } });
        act(() => {
          vi.advanceTimersByTime(50);
        });
        fireEvent.change(input, { target: { value: 'AAPL' } });
        act(() => {
          vi.advanceTimersByTime(250);
        });
        act(() => {
          vi.advanceTimersByTime(20);
        });

        expect(input).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByRole('listbox')).toBeInTheDocument();
        const aaplOption = screen.getByText('苹果');
        fireEvent.click(aaplOption);
        expect(mockOnSubmit).toHaveBeenCalledWith('AAPL', '苹果', 'autocomplete', {
          market: 'US',
          displayCode: 'AAPL',
        });
      } finally {
        useRealAutocomplete = false;
        vi.useRealTimers();
      }
    });
  });

  describe('localization', () => {
    afterEach(() => {
      window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
      document.documentElement.lang = '';
    });

    it('renders English default placeholder in both standard and fallback modes when UI language is en', () => {
      window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

      const { unmount } = render(
        <UiLanguageProvider>
          <StockAutocomplete value="" onChange={mockOnChange} onSubmit={mockOnSubmit} />
        </UiLanguageProvider>
      );

      expect(screen.getByPlaceholderText('Enter stock code or name')).toBeInTheDocument();
      unmount();

      stockIndexHookImpl = () => ({
        index: [],
        loading: false,
        fallback: true,
        error: new Error('Index load failed'),
        loaded: false,
      });

      render(
        <UiLanguageProvider>
          <StockAutocomplete value="" onChange={mockOnChange} onSubmit={mockOnSubmit} />
        </UiLanguageProvider>
      );

      expect(screen.getByPlaceholderText('Enter stock code or name')).toBeInTheDocument();
    });
  });
});
