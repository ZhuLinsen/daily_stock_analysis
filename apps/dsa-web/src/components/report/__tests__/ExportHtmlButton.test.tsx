import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExportHtmlButton } from '../ExportHtmlButton';
import { historyApi } from '../../../api/history';

describe('ExportHtmlButton', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('is hidden when recordId is undefined', () => {
    const { container } = render(
      <ExportHtmlButton reportTitle="贵州茅台-600519" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('downloads standalone HTML blob on click and shows exported state', async () => {
    const blob = new Blob(['<html></html>'], { type: 'text/html' });
    const exportSpy = vi.spyOn(historyApi, 'exportHtml').mockResolvedValue(blob);
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:html-1');
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    const setTimeoutSpy = vi.spyOn(window, 'setTimeout');

    render(<ExportHtmlButton recordId={12} reportTitle="贵州茅台-600519" reportLanguage="zh" />);

    fireEvent.click(screen.getByRole('button', { name: '导出 HTML' }));

    await waitFor(() => {
      expect(exportSpy).toHaveBeenCalledWith(12);
    });
    expect(createObjectUrlSpy).toHaveBeenCalledWith(blob);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(setTimeoutSpy).toHaveBeenCalledWith(expect.any(Function), 1000);
    expect(screen.getByRole('button', { name: '已导出' })).toBeInTheDocument();
    revokeObjectUrlSpy.mockRestore();
  });

  it('surfaces retry label when export fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(historyApi, 'exportHtml').mockRejectedValue(new Error('network error'));

    render(<ExportHtmlButton recordId={15} reportTitle="Apple-AAPL" reportLanguage="en" />);
    fireEvent.click(screen.getByRole('button', { name: 'Export HTML' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    });
  });
});
