import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetSharedDesktopUpdateState } from '../../../desktop/updateStore';
import { DesktopUpdateIndicator } from '../DesktopUpdateIndicator';

const {
  desktopCheckForUpdates,
  desktopGetUpdateState,
  desktopInstallDownloadedUpdate,
  desktopOnUpdateStateChange,
  desktopOpenReleasePage,
} = vi.hoisted(() => ({
  desktopCheckForUpdates: vi.fn(),
  desktopGetUpdateState: vi.fn(),
  desktopInstallDownloadedUpdate: vi.fn(),
  desktopOnUpdateStateChange: vi.fn(),
  desktopOpenReleasePage: vi.fn(),
}));

function createDesktopRuntime(overrides: Record<string, unknown> = {}) {
  return {
    version: '3.30.0',
    getUpdateState: desktopGetUpdateState,
    checkForUpdates: desktopCheckForUpdates,
    installDownloadedUpdate: desktopInstallDownloadedUpdate,
    openReleasePage: desktopOpenReleasePage,
    onUpdateStateChange: desktopOnUpdateStateChange,
    ...overrides,
  };
}

function renderIndicator() {
  return render(
    <MemoryRouter>
      <DesktopUpdateIndicator />
    </MemoryRouter>,
  );
}

describe('DesktopUpdateIndicator', () => {
  beforeEach(() => {
    desktopGetUpdateState.mockReset();
    desktopCheckForUpdates.mockReset();
    desktopInstallDownloadedUpdate.mockReset();
    desktopOpenReleasePage.mockReset();
    desktopOnUpdateStateChange.mockReset();
    desktopGetUpdateState.mockResolvedValue({
      status: 'idle',
      currentVersion: '3.30.0',
    });
    desktopCheckForUpdates.mockResolvedValue({
      status: 'up-to-date',
      currentVersion: '3.30.0',
      latestVersion: '3.30.0',
    });
    desktopInstallDownloadedUpdate.mockResolvedValue(true);
    desktopOpenReleasePage.mockResolvedValue(true);
    desktopOnUpdateStateChange.mockImplementation(() => () => undefined);
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
    resetSharedDesktopUpdateState();
  });

  afterEach(() => {
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
    resetSharedDesktopUpdateState();
  });

  it('does not render in ordinary browser WebUI', () => {
    renderIndicator();
    expect(screen.queryByRole('button', { name: '桌面端更新' })).not.toBeInTheDocument();
    expect(desktopGetUpdateState).not.toHaveBeenCalled();
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
  });

  it('does not render when only a desktop version is present', () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.30.0' };
    renderIndicator();
    expect(screen.queryByRole('button', { name: '桌面端更新' })).not.toBeInTheDocument();
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
  });

  it('subscribes to update state without triggering a background check', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();
    renderIndicator();

    expect(await screen.findByRole('button', { name: '桌面端更新' })).toBeInTheDocument();
    await waitFor(() => expect(desktopGetUpdateState).toHaveBeenCalledTimes(1));
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
    expect(desktopOnUpdateStateChange).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('desktop-update-badge')).not.toBeInTheDocument();
  });

  it('shows an available update badge and opens the release page from the popover', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'update-available',
      updateMode: 'manual',
      currentVersion: '3.30.0',
      latestVersion: '3.31.0',
      releaseUrl: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.31.0',
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();
    renderIndicator();

    fireEvent.click(await screen.findByRole('button', { name: '桌面端更新' }));
    expect(await screen.findByText('发现新版本')).toBeInTheDocument();
    expect(screen.getByTestId('desktop-update-badge')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '前往下载' }));
    await waitFor(() => {
      expect(desktopOpenReleasePage).toHaveBeenCalledWith(
        'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.31.0',
      );
    });
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
  });

  it('installs a downloaded update from the popover', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'update-downloaded',
      updateMode: 'auto',
      currentVersion: '3.30.0',
      latestVersion: '3.31.0',
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();
    renderIndicator();

    fireEvent.click(await screen.findByRole('button', { name: '桌面端更新' }));
    fireEvent.click(await screen.findByRole('button', { name: '重启安装' }));
    await waitFor(() => expect(desktopInstallDownloadedUpdate).toHaveBeenCalledTimes(1));
  });

  it('rechecks after an error without calling checkForUpdates on mount', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'error',
      message: 'GitHub API timeout',
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();
    renderIndicator();

    fireEvent.click(await screen.findByRole('button', { name: '桌面端更新' }));
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: '重新检查' }));
    await waitFor(() => expect(desktopCheckForUpdates).toHaveBeenCalledTimes(1));
  });

  it('surfaces download percent in the entry tooltip', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'downloading',
      currentVersion: '3.30.0',
      latestVersion: '3.31.0',
      downloadPercent: 42,
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();
    renderIndicator();

    const entry = await screen.findByRole('button', { name: '桌面端更新' });
    expect(entry).toHaveAttribute('title', expect.stringContaining('42%'));
    expect(desktopCheckForUpdates).not.toHaveBeenCalled();
  });
});
