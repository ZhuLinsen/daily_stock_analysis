import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChangePasswordCard } from '../ChangePasswordCard';

const { changePasswordMock } = vi.hoisted(() => ({
  changePasswordMock: vi.fn(),
}));

vi.mock('../../../hooks', () => ({
  useAuth: () => ({
    changePassword: changePasswordMock,
  }),
}));

describe('ChangePasswordCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('guards synchronous double-submit while changePassword is pending', async () => {
    let resolveChange!: (value: { success: boolean }) => void;
    changePasswordMock.mockImplementationOnce(
      () => new Promise<{ success: boolean }>((resolve) => {
        resolveChange = resolve;
      }),
    );

    render(<ChangePasswordCard />);

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'oldpass6' } });
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'newpass6' } });
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'newpass6' } });

    const submitButton = screen.getByRole('button', { name: '保存新密码' });
    fireEvent.click(submitButton);
    fireEvent.click(submitButton);

    expect(changePasswordMock).toHaveBeenCalledTimes(1);
    expect(changePasswordMock).toHaveBeenCalledWith('oldpass6', 'newpass6', 'newpass6');

    await act(async () => {
      resolveChange({ success: true });
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByText('管理员密码已更新。')).toBeInTheDocument());
    expect(screen.getByLabelText('当前密码')).toHaveValue('');
    expect(screen.getByLabelText('新密码')).toHaveValue('');
    expect(screen.getByLabelText('确认新密码')).toHaveValue('');
  });

  it('clears the success timer on unmount and skips post-unmount state updates', async () => {
    vi.useFakeTimers();
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      changePasswordMock.mockResolvedValueOnce({ success: true });

      const firstRender = render(<ChangePasswordCard />);
      fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'oldpass6' } });
      fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'newpass6' } });
      fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'newpass6' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: '保存新密码' }));
        await Promise.resolve();
      });

      expect(screen.getByText('管理员密码已更新。')).toBeInTheDocument();
      expect(vi.getTimerCount()).toBe(1);

      firstRender.unmount();
      expect(vi.getTimerCount()).toBe(0);
      vi.advanceTimersByTime(5000);

      let resolvePending!: (value: { success: boolean }) => void;
      changePasswordMock.mockImplementationOnce(
        () => new Promise<{ success: boolean }>((resolve) => {
          resolvePending = resolve;
        }),
      );

      const secondRender = render(<ChangePasswordCard />);
      fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'oldpass6' } });
      fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'newpass7' } });
      fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'newpass7' } });
      fireEvent.click(screen.getByRole('button', { name: '保存新密码' }));

      secondRender.unmount();

      await act(async () => {
        resolvePending({ success: true });
        await Promise.resolve();
      });

      expect(vi.getTimerCount()).toBe(0);
      expect(consoleErrorSpy).not.toHaveBeenCalled();
    } finally {
      consoleErrorSpy.mockRestore();
      vi.useRealTimers();
    }
  });
});
