import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { MarketReviewRegionSelector } from '../MarketReviewRegionSelector';
import { serializeMarketReviewRegions } from '../../../utils/marketReviewRegion';

describe('MarketReviewRegionSelector', () => {
  beforeEach(() => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  });

  it('serializes canonical UI selections at the HTTP boundary', () => {
    expect(serializeMarketReviewRegions(['kr', 'jp'])).toBe('jp,kr');
    expect(serializeMarketReviewRegions(['cn', 'hk', 'us', 'jp', 'kr'])).toBe('both');
  });

  it('keeps the runtime-resolved server default opaque and emits a canonical override', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector onChange={onChange} />
      </UiLanguageProvider>,
    );

    expect(screen.getByRole('button', { name: '选择大盘复盘市场' })).toHaveTextContent(
      '服务器默认',
    );
    expect(screen.getByRole('button', { name: '选择大盘复盘市场' })).not.toHaveTextContent('A 股');
    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    expect(screen.getByText('由服务器在提交时决定')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /A 股/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /美股/ })).not.toBeChecked();

    fireEvent.click(screen.getByRole('checkbox', { name: /日股/ }));
    expect(onChange).toHaveBeenLastCalledWith(['jp']);
  });

  it('supports all markets and restoring the server default', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector
          value={['us']}
          onChange={onChange}
        />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    fireEvent.click(screen.getByRole('button', { name: '全部市场' }));
    expect(onChange).toHaveBeenLastCalledWith(['cn', 'hk', 'us', 'jp', 'kr']);

    fireEvent.click(screen.getByRole('button', { name: /服务器默认/ }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('keeps at least one market selected in override mode', () => {
    const onChange = vi.fn();
    render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector value={['us']} onChange={onChange} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /美股/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('closes an open menu and blocks every option when disabled', () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <UiLanguageProvider>
        <MarketReviewRegionSelector value={['us']} onChange={onChange} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '选择大盘复盘市场' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    const cnCheckbox = screen.getByRole('checkbox', { name: /A 股/ });

    rerender(
      <UiLanguageProvider>
        <MarketReviewRegionSelector value={['us']} disabled onChange={onChange} />
      </UiLanguageProvider>,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '选择大盘复盘市场' })).toBeDisabled();
    fireEvent.click(cnCheckbox);
    expect(onChange).not.toHaveBeenCalled();
  });
});
