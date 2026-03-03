import type React from 'react';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { authApi } from '../api/auth';

type AuthContextValue = {
  authEnabled: boolean;
  loggedIn: boolean;
  passwordSet: boolean;
  passwordChangeable: boolean;
  isLoading: boolean;
  loadError: string | null;
  login: (password: string, passwordConfirm?: string) => Promise<{ success: boolean; error?: string }>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string
  ) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<void>;
  refreshStatus: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function extractLoginError(err: unknown): string {
  const axiosErr =
    err && typeof err === 'object' && 'response' in err
      ? (err as { response?: { status?: number; data?: { message?: string } } })
      : null;
  if (axiosErr) {
    if (axiosErr.response?.status === 429) {
      return '尝试次数过多，请稍后再试';
    }
    const serverMsg = axiosErr.response?.data?.message;
    return serverMsg || '密码错误';
  }
  return '登录失败';
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authEnabled, setAuthEnabled] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [passwordSet, setPasswordSet] = useState(false);
  const [passwordChangeable, setPasswordChangeable] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const status = await authApi.getStatus();
      setAuthEnabled(status.authEnabled);
      setLoggedIn(status.loggedIn);
      setPasswordSet(status.passwordSet ?? false);
      setPasswordChangeable(status.passwordChangeable ?? false);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load auth status');
      setAuthEnabled(false);
      setLoggedIn(false);
      setPasswordSet(false);
      setPasswordChangeable(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const login = useCallback(
    async (
      password: string,
      passwordConfirm?: string
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        await authApi.login(password, passwordConfirm);
        setLoggedIn(true);
        return { success: true };
      } catch (err: unknown) {
        return { success: false, error: extractLoginError(err) };
      }
    },
    []
  );

  const changePassword = useCallback(
    async (
      currentPassword: string,
      newPassword: string,
      newPasswordConfirm: string
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        await authApi.changePassword(currentPassword, newPassword, newPasswordConfirm);
        return { success: true };
      } catch (err: unknown) {
        const axiosErr =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { message?: string } } })
            : null;
        const msg = axiosErr?.response?.data?.message || '修改失败';
        return { success: false, error: msg };
      }
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setLoggedIn(false);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        authEnabled,
        loggedIn,
        passwordSet,
        passwordChangeable,
        isLoading,
        loadError,
        login,
        changePassword,
        logout,
        refreshStatus: fetchStatus,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- useAuth is a hook, co-located for context access
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
