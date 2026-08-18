import type React from 'react';
import { lazy, useEffect, useMemo } from 'react';
import {
  Navigate,
  createBrowserRouter,
  useLocation,
  RouterProvider,
} from 'react-router-dom';
import { ApiErrorAlert, Shell } from './components/common';
import {
  PageLoadingFallback,
  RouteOutletBoundary,
  StandaloneRouteBoundary,
} from './components/layout/RouteBoundary';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UiLanguageProvider, useUiLanguage } from './contexts/UiLanguageContext';
import { useAgentChatStore } from './stores/agentChatStore';
import './App.css';

const HomePage = lazy(() => import('./pages/HomePage'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'));
const DecisionSignalsPage = lazy(() => import('./pages/DecisionSignalsPage'));
const AlertsPage = lazy(() => import('./pages/AlertsPage'));
const TokenUsagePage = lazy(() => import('./pages/TokenUsagePage'));
const StockScreeningPage = lazy(() => import('./pages/StockScreeningPage'));

const AppContent: React.FC = () => {
  const location = useLocation();
  const { authEnabled, loggedIn, isLoading, loadError, refreshStatus } = useAuth();
  const { t } = useUiLanguage();

  useEffect(() => {
    useAgentChatStore.getState().setCurrentRoute(location.pathname);
  }, [location.pathname]);

  if (isLoading) {
    return <PageLoadingFallback />;
  }

  if (loadError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-base px-4">
        <div className="w-full max-w-lg">
          <ApiErrorAlert error={loadError} />
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => void refreshStatus()}
        >
          {t('common.retry')}
        </button>
      </div>
    );
  }

  if (authEnabled && !loggedIn) {
    if (location.pathname === '/login') {
      return (
        <StandaloneRouteBoundary>
          <LoginPage />
        </StandaloneRouteBoundary>
      );
    }
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }

  if (location.pathname === '/login') {
    return <Navigate to="/" replace />;
  }

  return (
    <Shell>
      <RouteOutletBoundary />
    </Shell>
  );
};

const routeChildren = [
  { path: '/', element: <HomePage /> },
  { path: '/chat', element: <ChatPage /> },
  { path: '/portfolio', element: <PortfolioPage /> },
  { path: '/decision-signals', element: <DecisionSignalsPage /> },
  { path: '/screening', element: <StockScreeningPage /> },
  { path: '/backtest', element: <BacktestPage /> },
  { path: '/alerts', element: <AlertsPage /> },
  { path: '/usage', element: <TokenUsagePage /> },
  { path: '/settings', element: <SettingsPage /> },
  { path: '*', element: <NotFoundPage /> },
];

const App: React.FC = () => {
  // Construct the data router lazily on first mount. `createBrowserRouter`
  // reads `window.location` at construction time, so for it to honour the
  // current URL (especially under tests that `window.history.pushState(...)`
  // before rendering, and to react when navigating the same module instance
  // across different entry URLs) it must be built inside the React tree, not
  // at module import time.
  const router = useMemo(
    () =>
      createBrowserRouter([
        {
          element: <AppContent />,
          children: routeChildren,
        },
      ]),
    [],
  );

  return (
    <UiLanguageProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </UiLanguageProvider>
  );
};

export default App;
