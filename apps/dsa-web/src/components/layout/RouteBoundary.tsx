import type React from 'react';
import { Component, Suspense } from 'react';
import type { ErrorInfo } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

type PageLoadingFallbackProps = {
  fullPage?: boolean;
};

export const PageLoadingFallback: React.FC<PageLoadingFallbackProps> = ({ fullPage = true }) => (
  <div
    className={
      fullPage
        ? 'flex min-h-screen items-center justify-center bg-base'
        : 'flex min-h-[60vh] items-center justify-center'
    }
  >
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan/20 border-t-cyan" />
  </div>
);

type RouteErrorBoundaryProps = {
  children: React.ReactNode;
  resetKey: string;
  fullPage: boolean;
  text: {
    title: string;
    description: string;
    reload: string;
    backHome: string;
  };
};

type RouteErrorBoundaryState = {
  hasError: boolean;
};

class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  override state: RouteErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): RouteErrorBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Route page failed to render or load', error, errorInfo);
  }

  override componentDidUpdate(prevProps: RouteErrorBoundaryProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  override render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        className={
          this.props.fullPage
            ? 'flex min-h-screen items-center justify-center bg-base px-4'
            : 'flex min-h-[60vh] items-center justify-center px-2 py-8'
        }
      >
        <div className="w-full max-w-md rounded-2xl border border-border bg-card/94 p-6 text-center shadow-soft-card">
          <h1 className="text-xl font-semibold text-foreground">{this.props.text.title}</h1>
          <p className="mt-3 text-sm leading-6 text-secondary-text">
            {this.props.text.description}
          </p>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:justify-center">
            <button
              type="button"
              className="btn-primary"
              onClick={() => window.location.reload()}
            >
              {this.props.text.reload}
            </button>
            <button
              type="button"
              className="rounded-xl border border-border/70 bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-hover"
              onClick={() => window.location.assign('/')}
            >
              {this.props.text.backHome}
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export const RouteBoundary: React.FC<{ children: React.ReactNode; fullPage?: boolean }> = ({
  children,
  fullPage = true,
}) => {
  const location = useLocation();
  const { t } = useUiLanguage();
  const resetKey = `${location.pathname}${location.search}`;

  return (
    <RouteErrorBoundary
      resetKey={resetKey}
      fullPage={fullPage}
      text={{
        title: t('routeError.title'),
        description: t('routeError.description'),
        reload: t('routeError.reload'),
        backHome: t('routeError.backHome'),
      }}
    >
      <Suspense fallback={<PageLoadingFallback fullPage={fullPage} />}>{children}</Suspense>
    </RouteErrorBoundary>
  );
};

export const RouteOutletBoundary: React.FC = () => (
  <RouteBoundary fullPage={false}>
    <Outlet />
  </RouteBoundary>
);

export const StandaloneRouteBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <RouteBoundary fullPage>
    {children}
  </RouteBoundary>
);
