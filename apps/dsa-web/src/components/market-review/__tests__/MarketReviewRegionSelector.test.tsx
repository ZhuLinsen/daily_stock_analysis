import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { MarketReviewRegionSelector } from '../MarketReviewRegionSelector';
import {
  parseMarketReviewRegion,
  serializeMarketReviewRegions,
} from '../marketReviewRegion';

describe('MarketReviewRegionSelector', () => {
  beforeEach(() => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  });

  it('parses known config values without accepting mixed invalid tokens', () => {
    expect(parseMarketReviewRegion(' US, cn,US ')).toEqual(['cn', 'us']);
    expect(parseMarketReviewRegion('both')).toEqual(['cn', 'hk', 'us', 'jp', 'kr']);
    expect(parseMarketReviewRegion('cn,unknown')).toBeNull();
    expect(serializeMarketReviewRegions(['kr', 'jp'])).toBe('jp,kr');
    expect(serializeMarketReviewRegions(['cn', 'hk', 'us', 'jp', 'kr'])).toBe('both');
  });

  it('shows the server default and emits a canonical one-time override', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector
          serverDefaultRegion="cn,us"
          onChange={onChange}
        />
      </UiLanguageProvider>,
    );

    expect(screen.getByRole('button', { name: '选择大盘复盘市场' })).toHaveTextContent(
      '服务器默认 · A 股 + 美股',
    );
    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    expect(screen.getByRole('checkbox', { name: /A 股/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /美股/ })).toBeChecked();

    fireEvent.click(screen.getByRole('checkbox', { name: /日股/ }));
    expect(onChange).toHaveBeenLastCalledWith('cn,us,jp');
  });

  it('supports all markets and restoring the server default', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector
          value="us"
          serverDefaultRegion="cn"
          onChange={onChange}
        />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    fireEvent.click(screen.getByRole('button', { name: '全部市场' }));
    expect(onChange).toHaveBeenLastCalledWith('both');

    fireEvent.click(screen.getByRole('button', { name: /服务器默认/ }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('keeps at least one market selected in override mode', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector value="us" onChange={onChange} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /美股/ }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
