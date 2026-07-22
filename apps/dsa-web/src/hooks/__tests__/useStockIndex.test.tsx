import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStockIndex } from '../useStockIndex';
import { loadStockIndex } from '../../utils/stockIndexLoader';

vi.mock('../../utils/stockIndexLoader', () => ({
  loadStockIndex: vi.fn(),
}));

describe('useStockIndex', () => {
  beforeEach(() => {
    vi.mocked(loadStockIndex).mockReset();
    vi.mocked(loadStockIndex).mockResolvedValue({
      data: [],
      fallback: false,
      loaded: true,
    });
  });

  it('does not load the index until enabled', async () => {
    const { rerender } = renderHook(
      ({ enabled }) => useStockIndex(enabled),
      { initialProps: { enabled: false } },
    );

    expect(loadStockIndex).not.toHaveBeenCalled();

    rerender({ enabled: true });

    await waitFor(() => expect(loadStockIndex).toHaveBeenCalledOnce());
  });
});
