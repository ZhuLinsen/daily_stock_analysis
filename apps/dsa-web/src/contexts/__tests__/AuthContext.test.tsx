import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createApiError, createParsedApiError } from '../../api/error';
import { AuthProvider, useAuth } from '../AuthContext';

const { getStatus, login, changePassword, logout, resetDashboardState } = vi.hoisted(() => ({
  getStatus: vi.fn(),
  login: vi.fn(),
  changePassword: vi.fn(),
  logout: vi.fn(),
  resetDashboardState: vi.fn(),
}));

vi.mock('../../api/auth', () => ({
  authApi: {
    getStatus,
    login,
    changePassword,
    logout,
  },
}));

vi.mock('../../stores', () => ({
  useStockPoolStore: {
    getState: () => ({
      resetDashboardState,
    }),
  },
}));

const Probe = () => {
  const auth = useAuth();

  return (
    <div>
      <span data-testid="status">{auth.loggedIn ? 'logged-in' : 'logged-out'}</span>
      <span data-testid="password-set">{auth.passwordSet ? 'set' : 'unset'}</span>
      <button type="button" onClick={() => void auth.login('passwd6', 'passwd6')}>
        trigger-login
      </button>
      <button type="button" onClick={() => void auth.logout()}>
        trigger-logout
      </button>
    </div>
  );
};

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('refreshes auth state after a successful login', async () => {
    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: false,
        passwordChangeable: true,
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
      });
    login.mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await screen.findByTestId('status');
    fireEvent.click(screen.getByRole('button', { name: 'trigger-login' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('logged-in'));
    expect(screen.getByTestId('password-set')).toHaveTextContent('set');
  });

  it('refreshes auth state after logout', async () => {
    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });
    logout.mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await screen.findByTestId('status');
    fireEvent.click(screen.getByRole('button', { name: 'trigger-logout' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('logged-out'));
    expect(resetDashboardState).toHaveBeenCalled();
  });

  it('does not reset dashboard state when auth is disabled', async () => {
    getStatus.mockResolvedValueOnce({
      authEnabled: false,
      loggedIn: false,
      passwordSet: false,
      passwordChangeable: false,
      setupState: 'no_password',
    });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await screen.findByTestId('status');
    expect(resetDashboardState).not.toHaveBeenCalled();
  });

  it('treats a 401 logout as already signed out after status refresh', async () => {
    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });
    logout.mockRejectedValue(
      createApiError(
        createParsedApiError({
          title: '未登录',
          message: 'Login required',
          rawMessage: 'Login required',
          status: 401,
          category: 'http_error',
        }),
        { response: { status: 401, data: { error: 'unauthorized' } } }
      )
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await screen.findByTestId('status');
    fireEvent.click(screen.getByRole('button', { name: 'trigger-logout' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('logged-out'));
    expect(resetDashboardState).toHaveBeenCalled();
  });

  it('ignores stale initial getStatus response resolving after login refresh', async () => {
    let resolveInitialStatus!: (value: unknown) => void;
    const initialStatusPending = new Promise((resolve) => {
      resolveInitialStatus = resolve;
    });

    getStatus
      .mockReturnValueOnce(initialStatusPending)
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });
    login.mockResolvedValueOnce(undefined);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    expect(getStatus).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'trigger-login' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('logged-in'));
    expect(resetDashboardState).not.toHaveBeenCalled();

    await act(async () => {
      resolveInitialStatus({
        authEnabled: true,
        loggedIn: false,
        passwordSet: false,
        passwordChangeable: true,
        setupState: 'enabled',
      });
      await Promise.resolve();
    });

    expect(screen.getByTestId('status')).toHaveTextContent('logged-in');
    expect(resetDashboardState).not.toHaveBeenCalled();
  });

  it('deduplicates concurrent login and logout calls and skips post-unmount status refresh', async () => {
    let resolveLogin!: () => void;
    let resolveLogout!: () => void;
    login.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveLogin = resolve;
    }));
    logout.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveLogout = resolve;
    }));

    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const { unmount } = render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      );

      await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));

      const loginBtn = screen.getByRole('button', { name: 'trigger-login' });
      fireEvent.click(loginBtn);
      fireEvent.click(loginBtn);
      expect(login).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolveLogin();
        await Promise.resolve();
      });

      await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('logged-in'));

      const logoutBtn = screen.getByRole('button', { name: 'trigger-logout' });
      fireEvent.click(logoutBtn);
      fireEvent.click(logoutBtn);
      expect(logout).toHaveBeenCalledTimes(1);

      unmount();

      await act(async () => {
        resolveLogout();
        await Promise.resolve();
      });

      expect(getStatus).toHaveBeenCalledTimes(2);
      expect(consoleErrorSpy).not.toHaveBeenCalled();
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('submits updated credentials without reusing an in-flight login attempt for different passwords', async () => {
    let rejectFirstLogin!: (reason?: unknown) => void;
    let resolveSecondLogin!: () => void;
    login
      .mockImplementationOnce(() => new Promise<void>((_resolve, reject) => {
        rejectFirstLogin = reject;
      }))
      .mockImplementationOnce(() => new Promise<void>((resolve) => {
        resolveSecondLogin = resolve;
      }));

    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });

    let firstPromise!: Promise<{ success: boolean; error?: unknown }>;
    let secondPromise!: Promise<{ success: boolean; error?: unknown }>;

    const RetryProbe = () => {
      const auth = useAuth();
      return (
        <div>
          <span data-testid="retry-status">{auth.loggedIn ? 'logged-in' : 'logged-out'}</span>
          <button
            type="button"
            onClick={() => {
              firstPromise = auth.login('wrong-pass');
            }}
          >
            login-wrong
          </button>
          <button
            type="button"
            onClick={() => {
              secondPromise = auth.login('right-pass');
            }}
          >
            login-right
          </button>
        </div>
      );
    };

    render(
      <AuthProvider>
        <RetryProbe />
      </AuthProvider>
    );

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'login-wrong' }));
    fireEvent.click(screen.getByRole('button', { name: 'login-right' }));

    expect(login).toHaveBeenCalledTimes(2);
    expect(login).toHaveBeenNthCalledWith(1, 'wrong-pass', undefined);
    expect(login).toHaveBeenNthCalledWith(2, 'right-pass', undefined);

    await act(async () => {
      resolveSecondLogin();
      const secondResult = await secondPromise;
      expect(secondResult.success).toBe(true);
    });

    await waitFor(() => expect(screen.getByTestId('retry-status')).toHaveTextContent('logged-in'));

    await act(async () => {
      rejectFirstLogin(
        createApiError(
          createParsedApiError({
            title: '登录失败',
            message: 'Invalid password',
            rawMessage: 'Invalid password',
            status: 401,
            category: 'http_error',
          }),
          { response: { status: 401, data: { error: 'invalid_password' } } }
        )
      );
      const firstResult = await firstPromise;
      expect(firstResult.success).toBe(false);
    });

    expect(screen.getByTestId('retry-status')).toHaveTextContent('logged-in');
  });

  it('refreshes auth status when an earlier login succeeds after a newer login fails', async () => {
    let resolveFirstLogin!: () => void;
    let rejectSecondLogin!: (reason?: unknown) => void;
    login
      .mockImplementationOnce(() => new Promise<void>((resolve) => {
        resolveFirstLogin = resolve;
      }))
      .mockImplementationOnce(() => new Promise<void>((_resolve, reject) => {
        rejectSecondLogin = reject;
      }));

    getStatus
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: false,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      })
      .mockResolvedValueOnce({
        authEnabled: true,
        loggedIn: true,
        passwordSet: true,
        passwordChangeable: true,
        setupState: 'enabled',
      });

    let firstPromise!: Promise<{ success: boolean; error?: unknown }>;
    let secondPromise!: Promise<{ success: boolean; error?: unknown }>;

    const OverlapProbe = () => {
      const auth = useAuth();
      return (
        <div>
          <span data-testid="overlap-status">{auth.loggedIn ? 'logged-in' : 'logged-out'}</span>
          <button
            type="button"
            onClick={() => {
              firstPromise = auth.login('right-pass');
            }}
          >
            login-first-right
          </button>
          <button
            type="button"
            onClick={() => {
              secondPromise = auth.login('wrong-pass');
            }}
          >
            login-second-wrong
          </button>
        </div>
      );
    };

    render(
      <AuthProvider>
        <OverlapProbe />
      </AuthProvider>
    );

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'login-first-right' }));
    fireEvent.click(screen.getByRole('button', { name: 'login-second-wrong' }));

    expect(login).toHaveBeenCalledTimes(2);

    await act(async () => {
      rejectSecondLogin(
        createApiError(
          createParsedApiError({
            title: '登录失败',
            message: 'Invalid password',
            rawMessage: 'Invalid password',
            status: 401,
            category: 'http_error',
          }),
          { response: { status: 401, data: { error: 'invalid_password' } } }
        )
      );
      const secondResult = await secondPromise;
      expect(secondResult.success).toBe(false);
    });

    expect(screen.getByTestId('overlap-status')).toHaveTextContent('logged-out');
    expect(getStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstLogin();
      const firstResult = await firstPromise;
      expect(firstResult.success).toBe(true);
    });

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId('overlap-status')).toHaveTextContent('logged-in'));
  });
});
