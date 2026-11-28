import type React from 'react';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import {
  createLocalizedParsedApiError,
  createParsedApiError,
  getParsedApiError,
  localizeParsedApiError,
  type ParsedApiError,
} from '../api/error';
import { authApi } from '../api/auth';
import { useStockPoolStore } from '../stores';

type AuthContextValue = {
  authEnabled: boolean;
  loggedIn: boolean;
  passwordSet: boolean;
  passwordChangeable: boolean;
  setupState: 'enabled' | 'password_retained' | 'no_password';
  isLoading: boolean;
  loadError: ParsedApiError | null;
  login: (password: string, passwordConfirm?: string) => Promise<{ success: boolean; error?: ParsedApiError }>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string
  ) => Promise<{ success: boolean; error?: ParsedApiError }>;
  logout: () => Promise<void>;
  refreshStatus: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function extractLoginError(err: unknown): ParsedApiError {
  const parsed = getParsedApiError(err);
  if (parsed.status === 429) {
    return createLocalizedParsedApiError((language) => {
      const localized = localizeParsedApiError(parsed, language);
      const isEnglish = language === 'en';
      return createParsedApiError({
        title: isEnglish ? 'Too many login attempts' : '登录尝试过于频繁',
        message: isEnglish ? 'Too many attempts. Please try again later.' : '尝试次数过多，请稍后再试。',
        rawMessage: localized.rawMessage,
        status: localized.status,
        category: localized.category,
      });
    });
  }
  return parsed;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authEnabled, setAuthEnabled] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [passwordSet, setPasswordSet] = useState(false);
  const [passwordChangeable, setPasswordChangeable] = useState(false);
  const [setupState, setSetupState] = useState<'enabled' | 'password_retained' | 'no_password'>('no_password');
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<ParsedApiError | null>(null);
  const mountedRef = useRef(true);
  const statusRequestIdRef = useRef(0);
  const loginPromiseRef = useRef<Promise<{ success: boolean; error?: ParsedApiError }> | null>(null);
  const loginCredentialsKeyRef = useRef<string | null>(null);
  const loginRequestIdRef = useRef(0);
  const logoutPromiseRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      statusRequestIdRef.current += 1;
      loginRequestIdRef.current += 1;
    };
  }, []);

  const fetchStatus = useCallback(async () => {
    const requestId = statusRequestIdRef.current + 1;
    statusRequestIdRef.current = requestId;
    const isLatestRequest = () => mountedRef.current && statusRequestIdRef.current === requestId;
    setIsLoading(true);
    setLoadError(null);
    try {
      const status = await authApi.getStatus();
      if (!isLatestRequest()) return;
      setAuthEnabled(status.authEnabled);
      setLoggedIn(status.loggedIn);
      setPasswordSet(status.passwordSet ?? false);
      setPasswordChangeable(status.passwordChangeable ?? false);
      setSetupState(status.setupState);
      if (status.authEnabled && !status.loggedIn) {
        useStockPoolStore.getState().resetDashboardState();
      }
    } catch (err) {
      if (!isLatestRequest()) return;
      setLoadError(getParsedApiError(err));
      setAuthEnabled(false);
      setLoggedIn(false);
      setPasswordSet(false);
      setPasswordChangeable(false);
      setSetupState('no_password');
      useStockPoolStore.getState().resetDashboardState();
    } finally {
      if (isLatestRequest()) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const login = useCallback(
    async (
      password: string,
      passwordConfirm?: string
    ): Promise<{ success: boolean; error?: ParsedApiError }> => {
      const credentialsKey = JSON.stringify([password, passwordConfirm ?? null]);
      if (loginPromiseRef.current && loginCredentialsKeyRef.current === credentialsKey) {
        return loginPromiseRef.current;
      }
      const requestId = ++loginRequestIdRef.current;
      const pending = (async () => {
        try {
          await authApi.login(password, passwordConfirm);
          if (mountedRef.current) {
            await fetchStatus();
          }
          return { success: true };
        } catch (err: unknown) {
          return { success: false, error: extractLoginError(err) };
        } finally {
          if (loginRequestIdRef.current === requestId) {
            loginPromiseRef.current = null;
            loginCredentialsKeyRef.current = null;
          }
        }
      })();
      loginPromiseRef.current = pending;
      loginCredentialsKeyRef.current = credentialsKey;
      return pending;
    },
    [fetchStatus]
  );

  const changePassword = useCallback(
    async (
      currentPassword: string,
      newPassword: string,
      newPasswordConfirm: string
    ): Promise<{ success: boolean; error?: ParsedApiError }> => {
      try {
        await authApi.changePassword(currentPassword, newPassword, newPasswordConfirm);
        return { success: true };
      } catch (err: unknown) {
        return { success: false, error: getParsedApiError(err) };
      }
    },
    []
  );

  const logout = useCallback(async () => {
    if (logoutPromiseRef.current) {
      return logoutPromiseRef.current;
    }
    const pending = (async () => {
      let logoutError: unknown = null;
      try {
        try {
          await authApi.logout();
        } catch (err) {
          logoutError = err;
        } finally {
          if (mountedRef.current) {
            await fetchStatus();
          }
        }

        if (logoutError && getParsedApiError(logoutError).status !== 401) {
          throw logoutError;
        }
      } finally {
        logoutPromiseRef.current = null;
      }
    })();
    logoutPromiseRef.current = pending;
    return pending;
  }, [fetchStatus]);

  return (
    <AuthContext.Provider
      value={{
        authEnabled,
        loggedIn,
        passwordSet,
        passwordChangeable,
        setupState,
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
