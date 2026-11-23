import type React from 'react';
import { Component, lazy, Suspense, useCallback, useMemo, useState } from 'react';
import type { ReportLanguage } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Drawer } from '../common/Drawer';

interface ReportMarkdownDrawerProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onClose: () => void;
  reportLanguage?: ReportLanguage;
}

interface ReportMarkdownDrawerErrorBoundaryProps {
  resetKey: number;
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface ReportMarkdownDrawerErrorBoundaryState {
  hasError: boolean;
}

class ReportMarkdownDrawerErrorBoundary extends Component<
  ReportMarkdownDrawerErrorBoundaryProps,
  ReportMarkdownDrawerErrorBoundaryState
> {
  state: ReportMarkdownDrawerErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): ReportMarkdownDrawerErrorBoundaryState {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: ReportMarkdownDrawerErrorBoundaryProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: unknown) {
    console.error('Report markdown drawer failed:', error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }

    return this.props.children;
  }
}

const ReportMarkdownLoadingState: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex h-64 flex-col items-center justify-center">
    <div className="home-spinner h-10 w-10 animate-spin border-[3px]" />
    <p className="mt-4 text-sm text-secondary-text">{message}</p>
  </div>
);

const ReportMarkdownChunkErrorState: React.FC<{
  message: string;
  dismissText: string;
  onRequestClose: () => void;
}> = ({ message, dismissText, onRequestClose }) => (
  <div className="flex h-64 flex-col items-center justify-center">
    <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-danger/10">
      <svg className="h-6 w-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    </div>
    <p className="text-sm text-danger">{message}</p>
    <button
      type="button"
      onClick={onRequestClose}
      className="home-surface-button mt-4 rounded-lg px-4 py-2 text-sm text-secondary-text"
    >
      {dismissText}
    </button>
  </div>
);

export const ReportMarkdownDrawer: React.FC<ReportMarkdownDrawerProps> = ({
  recordId,
  stockName,
  stockCode,
  onClose,
  reportLanguage = 'zh',
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const text = getReportText(normalizeReportLanguage(reportLanguage));
  const LazyReportMarkdownPanel = useMemo(
    () => lazy(() => import('./ReportMarkdownPanel').then((m) => ({ default: m.ReportMarkdownPanel }))),
    [],
  );

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setTimeout(onClose, 300);
  }, [onClose]);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={handleClose}
      width="max-w-3xl"
      zIndex={100}
      backdropClassName="bg-background/56 backdrop-blur-[2px]"
    >
      <ReportMarkdownDrawerErrorBoundary
        resetKey={recordId}
        fallback={(
          <ReportMarkdownChunkErrorState
            message={text.loadReportFailed}
            dismissText={text.dismiss}
            onRequestClose={handleClose}
          />
        )}
      >
        <Suspense fallback={<ReportMarkdownLoadingState message={text.loadingReport} />}>
          <LazyReportMarkdownPanel
            recordId={recordId}
            stockName={stockName}
            stockCode={stockCode}
            reportLanguage={reportLanguage}
            onRequestClose={handleClose}
          />
        </Suspense>
      </ReportMarkdownDrawerErrorBoundary>
    </Drawer>
  );
};
