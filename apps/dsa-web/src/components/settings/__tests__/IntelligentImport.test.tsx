import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntelligentImport } from '../IntelligentImport';
import { SystemConfigConflictError } from '../../../api/systemConfig';

const { parseImport, extractFromImage, update, onMerged } = vi.hoisted(() => ({
  parseImport: vi.fn(),
  extractFromImage: vi.fn(),
  update: vi.fn(),
  onMerged: vi.fn(),
}));

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    parseImport,
    extractFromImage,
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
      expect(onMerged).toHaveBeenCalledWith('SH600000,SZ000001', { committed: false });
    });
    expect(await screen.findByText('配置已更新，请再次点击「合并到自选股」')).toBeInTheDocument();
  });

  it('normalizes existing mixed separators when merging into watchlist', async () => {
    parseImport.mockResolvedValue({
      items: [{ code: 'HK00700', name: 'Tencent', confidence: 'high' }],
      codes: [],
    });
    update.mockResolvedValue({ success: true });

    render(
      <IntelligentImport
        stockListValue="SH600000，SH600519 AAPL"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText('或粘贴 CSV/Excel 复制的文本...'), {
      target: { value: 'HK00700' },
    });
    fireEvent.click(screen.getByRole('button', { name: '解析' }));

    await screen.findByText('HK00700');

    fireEvent.click(screen.getByRole('button', { name: '合并到自选股' }));

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({
        configVersion: 'v1',
        maskToken: '******',
        reloadNow: true,
        items: [{ key: 'STOCK_LIST', value: 'SH600000,SH600519,AAPL,HK00700' }],
      });
    });
    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith('SH600000,SH600519,AAPL,HK00700');
    });
  });

  it('passes committed=false to onMerged on 409 conflict and still displays conflict error if refresh fails', async () => {
    parseImport.mockResolvedValue({
      items: [{ code: 'AAPL', name: 'Apple', confidence: 'high' }],
      codes: [],
    });
    update.mockRejectedValueOnce(new SystemConfigConflictError('version mismatch'));
    onMerged.mockRejectedValueOnce(new Error('500 refresh failed'));

    render(
      <IntelligentImport
        stockListValue="SH600519"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText('或粘贴 CSV/Excel 复制的文本...'), {
      target: { value: 'AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: '解析' }));
    await screen.findByText('AAPL');

    fireEvent.click(screen.getByRole('button', { name: '合并到自选股' }));

    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith('SH600519,AAPL', { committed: false });
    });
    expect(await screen.findByText('配置已更新，请再次点击「合并到自选股」')).toBeInTheDocument();
  });

  it('preserves edited paste text if user modifies textarea while parse is in flight', async () => {
    let resolveParse!: (value: unknown) => void;
    parseImport.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveParse = resolve;
      }),
    );

    render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    const textarea = screen.getByPlaceholderText('或粘贴 CSV/Excel 复制的文本...');
    fireEvent.change(textarea, { target: { value: '000001' } });
    fireEvent.click(screen.getByRole('button', { name: '解析' }));

    fireEvent.change(textarea, { target: { value: '600519' } });
    resolveParse({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });

    await screen.findByText('SZ000001');
    expect(textarea).toHaveValue('600519');
  });

  it('clears paste text when input was unchanged while parse ran', async () => {
    parseImport.mockResolvedValueOnce({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });

    render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    const textarea = screen.getByPlaceholderText('或粘贴 CSV/Excel 复制的文本...');
    fireEvent.change(textarea, { target: { value: '000001' } });
    fireEvent.click(screen.getByRole('button', { name: '解析' }));

    await screen.findByText('SZ000001');
    expect(textarea).toHaveValue('');
  });

  it('ignores late extractFromImage resolution after unmount', async () => {
    let resolveExtract!: (value: unknown) => void;
    extractFromImage.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveExtract = resolve;
      }),
    );

    const { container, unmount } = render(
      <IntelligentImport
        stockListValue="SH600000"
        configVersion="v1"
        maskToken="******"
        onMerged={onMerged}
      />,
    );

    const imageInput = container.querySelectorAll('input[type="file"]')[0] as HTMLInputElement;
    const file = new File(['img'], 'watchlist.png', { type: 'image/png' });
    fireEvent.change(imageInput, { target: { files: [file] } });

    expect(extractFromImage).toHaveBeenCalledTimes(1);
    unmount();

    resolveExtract({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });
    await Promise.resolve();
  });

  it('ignores in-flight second upload when clearAll is clicked before it resolves', async () => {
    let resolveSecondExtract!: (value: unknown) => void;
    parseImport.mockResolvedValueOnce({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });
    extractFromImage.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveSecondExtract = resolve;
      }),
    );

    const { container } = render(
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

    const imageInput = container.querySelectorAll('input[type="file"]')[0] as HTMLInputElement;
    const file = new File(['img'], 'second.png', { type: 'image/png' });
    fireEvent.change(imageInput, { target: { files: [file] } });

    expect(extractFromImage).toHaveBeenCalledTimes(1);
    expect(screen.getByText('处理中...')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '清空' }));

    expect(screen.queryByText('SZ000001')).not.toBeInTheDocument();
    expect(screen.queryByText('处理中...')).not.toBeInTheDocument();

    resolveSecondExtract({
      items: [{ code: 'SH600519', name: 'Moutai', confidence: 'high' }],
      codes: [],
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText('SH600519')).not.toBeInTheDocument();
  });

  it('still calls onMerged when unmounted while config update is in flight', async () => {
    let resolveUpdate!: (value: unknown) => void;
    parseImport.mockResolvedValue({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });
    update.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );

    const { unmount } = render(
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
    expect(update).toHaveBeenCalledTimes(1);

    unmount();
    resolveUpdate({ success: true });

    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith('SH600000,SZ000001');
    });
  });

  it('still calls onMerged on version conflict when unmounted while update is in flight', async () => {
    let rejectUpdate!: (reason?: unknown) => void;
    parseImport.mockResolvedValue({
      items: [{ code: 'SZ000001', name: 'Ping An Bank', confidence: 'high' }],
      codes: [],
    });
    update.mockImplementationOnce(
      () => new Promise((_, reject) => {
        rejectUpdate = reject;
      }),
    );

    const { unmount } = render(
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
    expect(update).toHaveBeenCalledTimes(1);

    unmount();
    rejectUpdate(new SystemConfigConflictError('配置版本冲突', 'v2'));

    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith('SH600000,SZ000001', { committed: false });
    });
  });
});
