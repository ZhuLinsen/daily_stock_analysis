import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReportLanguage } from '../../types/analysis';
import { Drawer } from '../common/Drawer';
import { ReportMarkdownPanel } from './ReportMarkdownPanel';

export interface ReportMarkdownProps {
  recordId: number;
  stockName: string;
  stockCode: string;
  onClose: () => void;
  reportLanguage?: ReportLanguage;
}

/**
 * Compatibility wrapper for direct ReportMarkdown usage.
 * HomePage uses ReportMarkdownDrawer to lazy-load the panel.
 */
export const ReportMarkdown: React.FC<ReportMarkdownProps> = ({
  recordId,
  stockName,
  stockCode,
  onClose,
  reportLanguage = 'zh',
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const closeTimerRef = useRef<number | null>(null);
  const isClosingRef = useRef(false);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
      onCloseRef.current();
    }
  }, []);

  const handleClose = useCallback(() => {
    if (isClosingRef.current) return;
    isClosingRef.current = true;
    setIsOpen(false);
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      onCloseRef.current();
    }, 300);
  }, []);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={handleClose}
      width="max-w-3xl"
      zIndex={100}
      backdropClassName="bg-background/56 backdrop-blur-[2px]"
    >
      <ReportMarkdownPanel
        recordId={recordId}
        stockName={stockName}
        stockCode={stockCode}
        reportLanguage={reportLanguage}
        onRequestClose={handleClose}
      />
    </Drawer>
  );
};
