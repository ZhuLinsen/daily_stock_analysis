import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsCategoryNav } from '../SettingsCategoryNav';
import type { SystemConfigCategorySchema, SystemConfigItem } from '../../../types/systemConfig';

const categories: SystemConfigCategorySchema[] = [
  { category: 'base', title: 'Base', description: '', displayOrder: 1, fields: [] },
  { category: 'ai_model', title: 'AI', description: '', displayOrder: 2, fields: [] },
];

const itemsByCategory = {
  base: [{ key: 'STOCK_LIST' }],
  ai_model: [{ key: 'LLM_CHANNELS' }, { key: 'LITELLM_MODEL' }],
} as unknown as Record<string, SystemConfigItem[]>;

describe('SettingsCategoryNav unsaved markers', () => {
  it('shows an unsaved marker for categories that have unsaved changes', () => {
    render(
      <SettingsCategoryNav
        categories={categories}
        itemsByCategory={itemsByCategory}
        activeCategory="base"
        onSelect={vi.fn()}
        dirtyCountByCategory={{ ai_model: 2 }}
      />,
    );

    const marker = screen.getByLabelText('2 项未保存');
    expect(marker).toBeInTheDocument();
    expect(marker).toHaveTextContent('2');
  });

  it('does not render any unsaved marker when no dirty counts are provided', () => {
    render(
      <SettingsCategoryNav
        categories={categories}
        itemsByCategory={itemsByCategory}
        activeCategory="base"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText(/未保存/)).not.toBeInTheDocument();
  });

  it('only marks categories whose dirty count is greater than zero', () => {
    render(
      <SettingsCategoryNav
        categories={categories}
        itemsByCategory={itemsByCategory}
        activeCategory="base"
        onSelect={vi.fn()}
        dirtyCountByCategory={{ base: 0, ai_model: 1 }}
      />,
    );

    expect(screen.getByLabelText('1 项未保存')).toBeInTheDocument();
    expect(screen.queryByLabelText('0 项未保存')).not.toBeInTheDocument();
  });
});
