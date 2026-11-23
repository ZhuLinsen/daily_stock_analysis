import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getDesktopUpdateBadgeTone } from '../../desktop/updateState';
import { useDesktopUpdate } from '../../hooks/useDesktopUpdate';
import { cn } from '../../utils/cn';
import { Button } from '../common/Button';
import { StatusDot } from '../common/StatusDot';

export const DesktopUpdateIndicator: React.FC = () => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();
  const {
    canCheckDesktopUpdate,
    desktopAppVersion,
    state,
    isBusy,
    isChecking,
    notice,
    checkForUpdates,
    openReleasePage,
    installDownloadedUpdate,
  } = useDesktopUpdate();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const status = state?.status;
  const busy = isBusy;
  const badgeTone = getDesktopUpdateBadgeTone(status);
  const currentVersion = state?.currentVersion || desktopAppVersion;
  const latestVersion = state?.latestVersion || state?.tagName;

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  if (!canCheckDesktopUpdate) {
    return null;
  }

  const tooltip = notice?.message
    || notice?.title
    || t('layout.desktopUpdateIdleHint', { version: currentVersion || t('settings.desktopLatest') });
  const canOpenRelease = Boolean(state?.releaseUrl) && (status === 'update-available' || status === 'error');
  const canInstall = status === 'update-downloaded';
  const showRecheck = !busy || status === 'error';

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        className={cn(
          'relative inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/85 text-secondary-text shadow-soft-card backdrop-blur-md transition-colors hover:bg-hover hover:text-foreground',
          open ? 'border-border text-foreground' : '',
        )}
        aria-label={t('layout.desktopUpdateEntry')}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={tooltip}
        onClick={() => setOpen((current) => !current)}
      >
        {busy ? (
          <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Download className="h-4 w-4" aria-hidden="true" />
        )}
        {badgeTone ? (
          <StatusDot
            tone={badgeTone}
            pulse={status === 'update-downloaded' || status === 'update-available'}
            className="absolute right-1.5 top-1.5 h-2 w-2"
            data-testid="desktop-update-badge"
            aria-label={notice?.title || t('layout.desktopUpdateEntry')}
          />
        ) : null}
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label={t('layout.desktopUpdateEntry')}
          className="absolute right-0 z-50 mt-2 w-[min(20rem,calc(100vw-1.5rem))] rounded-2xl border border-border/70 bg-card/95 p-3 shadow-soft-card backdrop-blur-xl"
        >
          <div className="space-y-1">
            <p className="text-sm font-semibold text-foreground">
              {notice?.title || t('settings.desktopUpdate')}
            </p>
            <p className="text-xs leading-5 text-secondary-text">
              {notice?.message || t('layout.desktopUpdateIdleHint', {
                version: currentVersion || t('settings.desktopLatest'),
              })}
            </p>
            {currentVersion || latestVersion ? (
              <p className="text-[11px] text-muted-text">
                {latestVersion && currentVersion && latestVersion !== currentVersion
                  ? t('layout.desktopUpdateVersionRange', { current: currentVersion, latest: latestVersion })
                  : t('layout.desktopUpdateCurrentVersion', { version: currentVersion || latestVersion || '' })}
              </p>
            ) : null}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {showRecheck ? (
              <Button
                type="button"
                variant="settings-secondary"
                size="sm"
                onClick={() => void checkForUpdates()}
                disabled={busy && status !== 'error'}
                isLoading={isChecking}
                loadingText={t('settings.checkingDesktopUpdate')}
              >
                {status === 'error' ? t('layout.desktopUpdateRecheck') : t('settings.checkDesktopUpdate')}
              </Button>
            ) : null}
            {canOpenRelease || notice?.actionKind === 'release' ? (
              <Button
                type="button"
                variant="settings-primary"
                size="sm"
                onClick={() => void openReleasePage()}
              >
                {t('settings.desktopDownload')}
              </Button>
            ) : null}
            {canInstall ? (
              <Button
                type="button"
                variant="settings-primary"
                size="sm"
                onClick={() => void installDownloadedUpdate()}
              >
                {t('settings.desktopInstall')}
              </Button>
            ) : null}
          </div>

          <button
            type="button"
            className="mt-3 text-xs text-secondary-text underline-offset-2 transition-colors hover:text-foreground hover:underline"
            onClick={() => {
              setOpen(false);
              navigate('/settings?category=system#desktop-version-info');
            }}
          >
            {t('layout.desktopUpdateOpenSettings')}
          </button>
        </div>
      ) : null}
    </div>
  );
};
