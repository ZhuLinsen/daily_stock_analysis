import type React from 'react';
import { useEffect, useCallback } from 'react';

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  width?: string;
}

/**
 * 侧滑抽屉组件 - 终端风格
 */
export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  children,
  width = 'max-w-2xl',
}) => {
  // ESC 键关闭
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* 遮罩层 */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm transition-opacity duration-300"
        onClick={onClose}
      />

      {/* 抽屉内容 */}
      <div className={`absolute inset-y-0 right-0 w-full ${width} flex`}>
        <div
          className="relative w-full flex flex-col
            bg-card border-l border-white/10
            shadow-2xl
            transform transition-transform duration-300 ease-out
            animate-slide-in-right"
        >
          {/* 头部 */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
            {title && (
              <div>
                <span className="label-uppercase">DETAIL VIEW</span>
                <h2 className="text-lg font-semibold text-white mt-1">
                  {title}
                </h2>
              </div>
            )}
            <button
              type="button"
              onClick={onClose}
              className="dock-item !w-10 !h-10"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* 内容区 */}
          <div className="flex-1 overflow-y-auto p-6">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
};
