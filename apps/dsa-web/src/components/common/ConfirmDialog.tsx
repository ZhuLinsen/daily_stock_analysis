import type React from 'react';
import { createPortal } from 'react-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  confirmDisabled?: boolean;
  cancelDisabled?: boolean;
  isDanger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Generic confirmation dialog component.
 * Style is consistent with ChatPage.
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmText,
  cancelText,
  confirmDisabled = false,
  cancelDisabled = false,
  isDanger = false,
  onConfirm,
  onCancel,
}) => {
  const { t } = useUiLanguage();

  if (!isOpen) return null;

  const dialog = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-all"
      onClick={() => {
        if (!cancelDisabled) {
          onCancel();
        }
      }}
    >
      <div
        className="mx-4 w-full max-w-sm rounded-xl border border-border/70 bg-elevated p-6 shadow-2xl animate-in fade-in zoom-in duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-2 text-lg font-medium text-foreground">{title}</h3>
        <p className="text-sm text-secondary-text mb-6 leading-relaxed">
          {message}
        </p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelDisabled}
            className="rounded-lg border border-border/70 px-4 py-2 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            {cancelText ?? t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-foreground transition-colors ${
              isDanger
                ? 'bg-red-500/80 hover:bg-red-500 shadow-lg shadow-red-500/20'
                : 'bg-cyan/80 hover:bg-cyan shadow-lg shadow-cyan/20'
            } disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {confirmText ?? t('common.confirm')}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
};
