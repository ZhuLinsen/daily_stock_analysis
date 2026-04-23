import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntelligentImport } from '../IntelligentImport';
import { SystemConfigConflictError } from '../../../api/systemConfig';

const { parseImport, update, onMerged } = vi.hoisted(() => ({
  parseImport: vi.fn(),
  update: vi.fn(),
  onMerged: vi.fn(),
}));

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    parseImport,
    extractFromImage: vi.fn(),
  },
}));

vi.mock('../../../api/systemConfig', async () => {
  const actual = await vi.importActual<typeof import('../../../api/systemConfig')>('../../../api/systemConfig');
  return {
    ...actual,
    systemConfigApi: {
      ...actual.systemConfigApi,
      update,
    },
  };
});

describe('IntelligentImport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('opens the matching hidden file input when the picker buttons are clicked', () => {
    const { container } = render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    const inputs = container.querySelectorAll('input[type="file"]');
    expect(inputs).toHaveLength(2);

    const imageClick = vi.fn();
    const dataClick = vi.fn();

    Object.defineProperty(inputs[0], 'click', {
      value: imageClick,
      configurable: true,
    });
    Object.defineProperty(inputs[1], 'click', {
      value: dataClick,
      configurable: true,
    });

    fireEvent.click(screen.getByRole('button', { name: '选择图片' }));
    fireEvent.click(screen.getByRole('button', { name: '选择文件' }));

    expect(imageClick).toHaveBeenCalledTimes(1);
    expect(dataClick).toHaveBeenCalledTimes(1);
  });

  it('does not open hidden file inputs when the import actions are disabled', () => {
    const { container } = render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
        disabled
      />,
    );

    const inputs = container.querySelectorAll('input[type="file"]');
    expect(inputs).toHaveLength(2);

    const imageClick = vi.fn();
    const dataClick = vi.fn();

    Object.defineProperty(inputs[0], 'click', {
      value: imageClick,
      configurable: true,
    });
    Object.defineProperty(inputs[1], 'click', {
      value: dataClick,
      configurable: true,
    });

    fireEvent.click(screen.getByRole('button', { name: '选择图片' }));
    fireEvent.click(screen.getByRole('button', { name: '选择文件' }));

    expect(imageClick).not.toHaveBeenCalled();
    expect(dataClick).not.toHaveBeenCalled();
  });

  it('refreshes config state after a config version conflict', async () => {
    parseImport.mockResolvedValue({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });
    update.mockRejectedValue(
      new SystemConfigConflictError('配置版本冲突', 'v2'),
    );

    render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText('或粘贴 CSV/Excel 复制的文本...'), {
      target: { value: '000001' },
    });
    fireEvent.click(screen.getByRole('button', { name: '解析' }));

    await screen.findByText('SZ000001');

    fireEvent.click(screen.getByRole('button', { name: '合并到自选股' }));

    await waitFor(() => {
      expect(update).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith('SH600000,SZ000001');
    });
    expect(await screen.findByText('配置已更新，请再次点击「合并到自选股」')).toBeInTheDocument();
  });
});
