import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthSettingsCard } from '../AuthSettingsCard';

const { refreshStatus, updateSettings, useAuthMock } = vi.hoisted(() => ({
  refreshStatus: vi.fn(),
  updateSettings: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('../../../hooks', () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock('../../../api/auth', () => ({
  authApi: {
    updateSettings,
  },
}));

describe('AuthSettingsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthMock.mockReturnValue({
      authEnabled: false,
      setupState: 'no_password',
      refreshStatus,
    });
  });

  it('enables auth with a new password and refreshes status', async () => {
    updateSettings.mockResolvedValue(undefined);
    refreshStatus.mockResolvedValue(undefined);

    render(<AuthSettingsCard />);

    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('设置管理员密码'), { target: { value: 'passwd6' } });
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'passwd6' } });
    fireEvent.click(screen.getByRole('button', { name: '开启认证' }));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith(true, 'passwd6', 'passwd6', undefined);
    });
    expect(refreshStatus).toHaveBeenCalled();
    expect(await screen.findByText('认证设置已更新')).toBeInTheDocument();
  });

  it('allows disabling auth without current password when the session is still valid', async () => {
    useAuthMock.mockReturnValue({
      authEnabled: true,
      setupState: 'enabled',
      refreshStatus,
    });
    updateSettings.mockResolvedValue(undefined);
    refreshStatus.mockResolvedValue(undefined);

    render(<AuthSettingsCard />);

    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '关闭认证' }));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith(false, undefined, undefined, undefined);
    });
    expect(refreshStatus).toHaveBeenCalled();
    expect(await screen.findByText('认证已关闭')).toBeInTheDocument();
  });

  it('shows only current password when re-enabling with a retained password', () => {
    useAuthMock.mockReturnValue({
      authEnabled: false,
      setupState: 'password_retained',
      refreshStatus,
    });

    render(<AuthSettingsCard />);

    fireEvent.click(screen.getByRole('checkbox'));

    expect(screen.getByLabelText('当前管理员密码')).toBeInTheDocument();
    expect(screen.queryByLabelText('设置管理员密码')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('确认新密码')).not.toBeInTheDocument();
  });

  it('does not show new password fields while auth is already enabled', () => {
    useAuthMock.mockReturnValue({
      authEnabled: true,
      setupState: 'enabled',
      refreshStatus,
    });

    render(<AuthSettingsCard />);

    expect(screen.queryByLabelText('设置管理员密码')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('确认新密码')).not.toBeInTheDocument();
  });

  it('blocks initial enable when the new password is missing', async () => {
    render(<AuthSettingsCard />);

    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '开启认证' }));

    expect(await screen.findByText('设置新密码是必填项')).toBeInTheDocument();
    expect(updateSettings).not.toHaveBeenCalled();
  });
});
