import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import { ShareImageButton } from '../ShareImageButton';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getShareImage: vi.fn(),
  },
}));

const mockedGetShareImage = vi.mocked(historyApi.getShareImage);

describe('ShareImageButton', () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockedGetShareImage.mockReset();
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:share-image');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    Object.defineProperty(window, 'dsaDesktop', { configurable: true, value: undefined });
    Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: undefined });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('downloads the generated PNG when native file sharing is unavailable', async () => {
    mockedGetShareImage.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));

    render(
      <ShareImageButton
        recordId={17}
        reportTitle="中钨高新-000657"
        reportLanguage="zh"
      />,
    );

    expect(mockedGetShareImage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '分享' }));
    await waitFor(() => expect(mockedGetShareImage).toHaveBeenCalledWith(17));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: '已生成' })).toBeInTheDocument();
  });

  it('prepares the PNG on the first click and invokes native sharing synchronously on the second click', async () => {
    const nativeShare = vi.fn().mockResolvedValue(undefined);
    let resolveImage: ((blob: Blob) => void) | undefined;
    mockedGetShareImage.mockReturnValue(new Promise((resolve) => {
      resolveImage = resolve;
    }));
    Object.defineProperty(navigator, 'share', { configurable: true, value: nativeShare });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true });

    render(
      <ShareImageButton
        recordId={18}
        reportTitle="A股市场复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByRole('button', { name: '分享' })).toBeEnabled();
    expect(mockedGetShareImage).not.toHaveBeenCalled();
    expect(nativeShare).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '分享' }));
    expect(mockedGetShareImage).toHaveBeenCalledWith(18);
    expect(screen.getByRole('button', { name: '生成中...' })).toBeDisabled();
    expect(nativeShare).not.toHaveBeenCalled();

    await act(async () => {
      resolveImage?.(new Blob(['png'], { type: 'image/png' }));
    });

    expect(screen.getByRole('button', { name: '再次点击分享' })).toBeEnabled();
    expect(nativeShare).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '再次点击分享' }));
    expect(nativeShare).toHaveBeenCalledTimes(1);
    const sharePayload = nativeShare.mock.calls[0][0];
    expect(sharePayload.title).toBe('A股市场复盘');
    expect(sharePayload.files[0].name).toBe('A股市场复盘-18.png');
    expect(mockedGetShareImage).toHaveBeenCalledTimes(1);
  });

  it('downloads the PNG when native file sharing rejects', async () => {
    const nativeShare = vi.fn().mockRejectedValue(new Error('activation expired'));
    mockedGetShareImage.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
    Object.defineProperty(navigator, 'share', { configurable: true, value: nativeShare });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true });

    render(
      <ShareImageButton
        recordId={20}
        reportTitle="A股市场复盘"
        reportLanguage="zh"
      />,
    );

    expect(mockedGetShareImage).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: '分享' }));

    expect(await screen.findByRole('button', { name: '再次点击分享' })).toBeEnabled();
    expect(nativeShare).not.toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '再次点击分享' }));
    await waitFor(() => expect(nativeShare).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: '已生成' })).toBeInTheDocument();
  });

  it('shows a retryable error state when image generation fails', async () => {
    mockedGetShareImage.mockRejectedValue(new Error('renderer unavailable'));

    render(
      <ShareImageButton
        recordId={19}
        reportTitle="中钨高新"
        reportLanguage="zh"
      />,
    );

    expect(mockedGetShareImage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '分享' }));
    expect(await screen.findByRole('button', { name: '重试' })).toBeInTheDocument();
    expect(mockedGetShareImage).toHaveBeenCalledWith(19);
  });

  it('keeps the button hidden for an older desktop bridge without image rendering', () => {
    mockedGetShareImage.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
    Object.defineProperty(window, 'dsaDesktop', {
      configurable: true,
      value: { version: '1.0.0' },
    });

    render(
      <ShareImageButton
        recordId={23}
        reportTitle="桌面端报告"
        reportLanguage="zh"
      />,
    );

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(mockedGetShareImage).not.toHaveBeenCalled();
  });

  it('renders and downloads share images through the desktop bridge', async () => {
    const renderShareImage = vi.fn().mockResolvedValue(
      new TextEncoder().encode('png').buffer,
    );
    Object.defineProperty(window, 'dsaDesktop', {
      configurable: true,
      value: { version: '3.30.0', renderShareImage },
    });

    render(
      <ShareImageButton
        recordId={24}
        reportTitle="桌面端报告"
        reportLanguage="zh"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '分享' }));
    await waitFor(() => expect(renderShareImage).toHaveBeenCalledWith(24));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
    expect(mockedGetShareImage).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '已生成' })).toBeInTheDocument();
  });

  it('clears the previous success reset timer when switching to another record', async () => {
    vi.useFakeTimers();
    const nativeShare = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: nativeShare });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true });
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout');
    let resolveSecondImage: ((blob: Blob) => void) | undefined;
    mockedGetShareImage
      .mockResolvedValueOnce(new Blob(['a'], { type: 'image/png' }))
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveSecondImage = resolve;
      }));

    const { rerender } = render(
      <ShareImageButton
        recordId={21}
        reportTitle="报告A"
        reportLanguage="zh"
      />,
    );

    expect(mockedGetShareImage).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '分享' })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '分享' }));
      await Promise.resolve();
    });

    expect(mockedGetShareImage).toHaveBeenCalledWith(21);
    expect(nativeShare).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '再次点击分享' })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '再次点击分享' }));
      await Promise.resolve();
    });

    expect(nativeShare).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '已生成' })).toBeInTheDocument();

    rerender(
      <ShareImageButton
        recordId={22}
        reportTitle="报告B"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByRole('button', { name: '分享' })).toBeEnabled();
    expect(mockedGetShareImage).not.toHaveBeenCalledWith(22);
    fireEvent.click(screen.getByRole('button', { name: '分享' }));
    expect(screen.getByRole('button', { name: '生成中...' })).toBeDisabled();
    await act(async () => {
      resolveSecondImage?.(new Blob(['b'], { type: 'image/png' }));
      await Promise.resolve();
    });

    expect(mockedGetShareImage).toHaveBeenCalledWith(22);
    expect(screen.getByRole('button', { name: '再次点击分享' })).toBeInTheDocument();
    expect(clearTimeoutSpy).toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '再次点击分享' }));
      await Promise.resolve();
    });

    expect(nativeShare).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: '已生成' })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(2300);
    });

    expect(screen.getByRole('button', { name: '分享' })).toBeInTheDocument();
  });
});
