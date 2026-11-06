import { useCallback, useEffect, useMemo, useState } from 'react';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import {
  canUseDesktopUpdateApi,
  getDesktopAppVersion,
  getDesktopRuntimeApi,
  type DesktopUpdateState,
} from '../desktop/runtime';
import {
  beginDesktopUpdateCheck,
  endDesktopUpdateCheck,
  getSharedDesktopUpdateState,
  isDesktopUpdateCheckInFlight,
  setSharedDesktopUpdateState,
  subscribeSharedDesktopUpdateState,
} from '../desktop/updateStore';
import { getDesktopUpdateNotice, isBusyDesktopUpdateStatus, normalizeDesktopUpdateState } from '../desktop/updateState';

export function useDesktopUpdate() {
  const { t } = useUiLanguage();
  const [state, setState] = useState<DesktopUpdateState | null>(() => getSharedDesktopUpdateState());
  const runtime = getDesktopRuntimeApi();
  const isDesktopRuntime = Boolean(runtime);
  const canCheckDesktopUpdate = canUseDesktopUpdateApi(runtime);
  const desktopAppVersion = getDesktopAppVersion();
  const isBusy = isBusyDesktopUpdateStatus(state?.status);
  const isChecking = state?.status === 'checking';

  useEffect(() => subscribeSharedDesktopUpdateState(() => {
    setState(getSharedDesktopUpdateState());
  }), []);

  useEffect(() => {
    if (!canCheckDesktopUpdate) {
      setSharedDesktopUpdateState(null);
      return undefined;
    }

    let active = true;

    const syncDesktopUpdateState = async () => {
      try {
        const nextState = await runtime?.getUpdateState?.();
        if (!active) {
          return;
        }
        const incoming = normalizeDesktopUpdateState(nextState);
        const current = getSharedDesktopUpdateState();
        if (
          (isDesktopUpdateCheckInFlight() || isBusyDesktopUpdateStatus(current?.status))
          && !isBusyDesktopUpdateStatus(incoming?.status)
        ) {
          return;
        }
        setSharedDesktopUpdateState(incoming);
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        setSharedDesktopUpdateState({
          status: 'error',
          message: error instanceof Error ? error.message : t('settings.desktopUpdateErrorMessage'),
        });
      }
    };

    void syncDesktopUpdateState();

    const unsubscribe = runtime?.onUpdateStateChange?.((nextState) => {
      if (!active) {
        return;
      }
      setSharedDesktopUpdateState(normalizeDesktopUpdateState(nextState));
    });

    return () => {
      active = false;
      if (typeof unsubscribe === 'function') {
        unsubscribe();
      }
    };
  }, [canCheckDesktopUpdate, runtime, t]);

  const checkForUpdates = useCallback(async () => {
    if (!runtime?.checkForUpdates) {
      return;
    }

    const currentState = getSharedDesktopUpdateState();
    if (isBusyDesktopUpdateStatus(currentState?.status) || !beginDesktopUpdateCheck()) {
      return;
    }

    setSharedDesktopUpdateState({
      ...(currentState || {}),
      status: 'checking',
      message: t('settings.desktopUpdateCheckingMessage'),
    });

    try {
      const nextState = await runtime.checkForUpdates();
      setSharedDesktopUpdateState(normalizeDesktopUpdateState(nextState));
    } catch (error: unknown) {
      setSharedDesktopUpdateState({
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopUpdateErrorMessage'),
      });
    } finally {
      endDesktopUpdateCheck();
    }
  }, [runtime, t]);

  const openReleasePage = useCallback(async () => {
    if (!runtime?.openReleasePage) {
      return;
    }

    await runtime.openReleasePage(state?.releaseUrl);
  }, [runtime, state?.releaseUrl]);

  const installDownloadedUpdate = useCallback(async () => {
    if (!runtime?.installDownloadedUpdate) {
      setSharedDesktopUpdateState({
        ...(getSharedDesktopUpdateState() || {}),
        status: 'error',
        message: t('settings.desktopManualUnsupported'),
      });
      return;
    }

    try {
      setSharedDesktopUpdateState({
        ...(getSharedDesktopUpdateState() || {}),
        status: 'installing',
        message: t('settings.desktopUpdateInstallingMessage'),
      });
      await runtime.installDownloadedUpdate();
    } catch (error: unknown) {
      setSharedDesktopUpdateState({
        ...(getSharedDesktopUpdateState() || {}),
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopManualUnsupported'),
      });
    }
  }, [runtime, t]);

  const notice = useMemo(() => getDesktopUpdateNotice(state, t), [state, t]);

  return {
    isDesktopRuntime,
    canCheckDesktopUpdate,
    desktopAppVersion,
    state,
    isBusy,
    isChecking,
    notice,
    checkForUpdates,
    openReleasePage,
    installDownloadedUpdate,
  };
}
