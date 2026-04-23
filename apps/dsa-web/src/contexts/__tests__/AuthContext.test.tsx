import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
});
