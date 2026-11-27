import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BUILTIN_STRATEGY_TEXT } from '../../../locales/strategyText';
import { StrategyPickerMenu, type StrategyOptionItem } from '../StrategyPickerMenu';

const SAMPLE_OPTIONS: StrategyOptionItem[] = [
  {
    id: 'bull_trend',
    name: BUILTIN_STRATEGY_TEXT.bull_trend.zh.name,
    description: BUILTIN_STRATEGY_TEXT.bull_trend.zh.description,
  },
  {
    id: 'vcp_breakout',
    name: BUILTIN_STRATEGY_TEXT.vcp_breakout.zh.name,
    description: BUILTIN_STRATEGY_TEXT.vcp_breakout.zh.description,
  },
  {
    id: 'turtle_donchian',
    name: BUILTIN_STRATEGY_TEXT.turtle_donchian.zh.name,
    description: BUILTIN_STRATEGY_TEXT.turtle_donchian.zh.description,
  },
  {
    id: 'bottom_volume',
    name: BUILTIN_STRATEGY_TEXT.bottom_volume.zh.name,
    description: BUILTIN_STRATEGY_TEXT.bottom_volume.zh.description,
  },
  {
    id: 'chan_theory',
    name: BUILTIN_STRATEGY_TEXT.chan_theory.zh.name,
    description: BUILTIN_STRATEGY_TEXT.chan_theory.zh.description,
  },
];

describe('StrategyPickerMenu', () => {
  it('renders category tabs with accurate counts and filters by quant category', () => {
    const onSelect = vi.fn();
    render(
      <StrategyPickerMenu
        options={SAMPLE_OPTIONS}
        selectedId="bull_trend"
        language="zh"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole('button', { name: '全部 (5)' })).toHaveAttribute('aria-pressed', 'true');
    const quantTab = screen.getByRole('button', { name: '量化因子 (2)' });
    fireEvent.click(quantTab);

    expect(quantTab).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('menuitemradio', { name: /VCP 波动收敛突破/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: /海龟唐奇安趋势/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitemradio', { name: /默认多头趋势/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('menuitemradio', { name: /VCP 波动收敛突破/ }));
    expect(onSelect).toHaveBeenCalledWith('vcp_breakout');
  });

  it('filters by keyword and supports clear/reset and Escape closing', () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    const enOptions: StrategyOptionItem[] = [
      {
        id: 'bollinger_squeeze',
        name: BUILTIN_STRATEGY_TEXT.bollinger_squeeze.en.name,
        description: BUILTIN_STRATEGY_TEXT.bollinger_squeeze.en.description,
      },
      {
        id: 'chan_theory',
        name: BUILTIN_STRATEGY_TEXT.chan_theory.en.name,
        description: BUILTIN_STRATEGY_TEXT.chan_theory.en.description,
      },
    ];

    render(
      <StrategyPickerMenu
        options={enOptions}
        selectedId="bollinger_squeeze"
        language="en"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );

    const searchInput = screen.getByRole('textbox', { name: 'Search analysis strategies' });
    fireEvent.change(searchInput, { target: { value: 'Bollinger' } });

    expect(screen.getByRole('menuitemradio', { name: /Bollinger Squeeze/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitemradio', { name: /Chan Theory/ })).not.toBeInTheDocument();

    // First Escape with query clears search; second Escape closes menu
    fireEvent.keyDown(searchInput, { key: 'Escape' });
    expect(searchInput).toHaveValue('');
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(searchInput, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    // Non-matching query displays empty state with reset action
    fireEvent.change(searchInput, { target: { value: 'no-such-strategy' } });
    expect(screen.getByText('No matching strategies found')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByRole('menuitemradio', { name: /Chan Theory/ })).toBeInTheDocument();
  });

  it('supports ArrowDown/ArrowUp keyboard navigation from search to menu items', () => {
    const onSelect = vi.fn();
    render(
      <StrategyPickerMenu
        options={SAMPLE_OPTIONS}
        selectedId="vcp_breakout"
        language="zh"
        onSelect={onSelect}
      />,
    );

    const searchInput = screen.getByRole('textbox', { name: '搜索分析策略' });
    fireEvent.keyDown(searchInput, { key: 'ArrowDown' });
    const items = screen.getAllByRole('menuitemradio');
    expect(document.activeElement).toBe(items[0]);

    const menu = screen.getByRole('menu');
    fireEvent.keyDown(menu, { key: 'End' });
    expect(document.activeElement).toBe(items[items.length - 1]);

    fireEvent.keyDown(menu, { key: 'Home' });
    expect(document.activeElement).toBe(items[0]);
  });

  it('excludes empty default id from category counts/badges, honors apiCategory, focuses initialFocusTarget, and triggers onTabClose', async () => {
    const onSelect = vi.fn();
    const onTabClose = vi.fn();
    const mixedOptions: StrategyOptionItem[] = [
      { id: '', name: 'Default Strategy', description: 'Use default behavior' },
      { id: 'vcp_breakout', name: 'VCP Breakout', description: 'Quant VCP' },
      { id: 'custom_alpha', name: 'Custom Alpha', description: 'User strategy', category: 'quant' },
      { id: 'custom_pattern', name: 'Custom Pattern', description: 'User pattern', category: 'reversal' },
    ];

    render(
      <StrategyPickerMenu
        options={mixedOptions}
        selectedId=""
        language="en"
        onSelect={onSelect}
        onTabClose={onTabClose}
        initialFocusTarget="first"
      />,
    );

    expect(screen.getByRole('button', { name: 'All (4)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Quant (2)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pattern & Reversal (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Framework (0)' })).toBeInTheDocument();

    const defaultItem = screen.getByRole('menuitemradio', { name: /Default Strategy/ });
    await vi.waitFor(() => {
      expect(document.activeElement).toBe(defaultItem);
    });
    expect(defaultItem.textContent).not.toContain('Framework');

    fireEvent.click(screen.getByRole('button', { name: 'Quant (2)' }));
    expect(screen.queryByRole('menuitemradio', { name: /Default Strategy/ })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitemradio', { name: /Custom Alpha/ })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Tab' });
    expect(onTabClose).toHaveBeenCalledTimes(1);
  });

  it('keeps panel open when Tab moves through search/categories and closes only when Tab/Shift+Tab exits panel', () => {
    const onSelect = vi.fn();
    const onTabClose = vi.fn();
    render(
      <StrategyPickerMenu
        options={SAMPLE_OPTIONS}
        selectedId="vcp_breakout"
        language="en"
        onSelect={onSelect}
        onTabClose={onTabClose}
      />,
    );

    const searchInput = screen.getByRole('textbox', { name: 'Search analysis strategies' });
    const allCategoryBtn = screen.getByRole('button', { name: 'All (5)' });
    const rovingItem = screen.getByRole('menuitemradio', { name: /VCP 波动收敛突破/ });
    const firstItem = screen.getByRole('menuitemradio', { name: /默认多头趋势/ });

    expect(rovingItem).toHaveAttribute('tabindex', '0');
    expect(firstItem).toHaveAttribute('tabindex', '-1');

    // Tab forward from search input -> internal category buttons, so do NOT close menu.
    searchInput.focus();
    fireEvent.keyDown(searchInput, { key: 'Tab' });
    expect(onTabClose).not.toHaveBeenCalled();

    // Tab across category buttons stays inside panel.
    allCategoryBtn.focus();
    fireEvent.keyDown(allCategoryBtn, { key: 'Tab' });
    fireEvent.keyDown(allCategoryBtn, { key: 'Tab', shiftKey: true });
    expect(onTabClose).not.toHaveBeenCalled();

    // Shift+Tab from first control (searchInput) exits panel -> closes menu.
    searchInput.focus();
    fireEvent.keyDown(searchInput, { key: 'Tab', shiftKey: true });
    expect(onTabClose).toHaveBeenCalledTimes(1);

    // Tab forward from roving menuitem exits panel -> closes menu.
    rovingItem.focus();
    fireEvent.keyDown(rovingItem, { key: 'Tab' });
    expect(onTabClose).toHaveBeenCalledTimes(2);

    // ArrowUp moves roving tabIndex="0" to the newly focused non-selected item, and Shift+Tab keeps menu open.
    rovingItem.focus();
    fireEvent.keyDown(rovingItem, { key: 'ArrowUp' });
    const movedItem = document.activeElement as HTMLElement;
    expect(movedItem).not.toBe(rovingItem);
    expect(movedItem).toHaveAttribute('role', 'menuitemradio');
    expect(movedItem).toHaveAttribute('tabindex', '0');

    fireEvent.keyDown(movedItem, { key: 'Tab', shiftKey: true });
    expect(onTabClose).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(movedItem, { key: 'Tab' });
    expect(onTabClose).toHaveBeenCalledTimes(3);
  });
});
