import { useCallback, useEffect, useMemo, useState } from 'react';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import {
  canUseDesktopUpdateApi,
  getDesktopAppVersion,
  getDesktopRuntimeApi,
  type DesktopUpdateState,
} from '../desktop/runtime';
import { getDesktopUpdateNotice, normalizeDesktopUpdateState } from '../desktop/updateState';

export function useDesktopUpdate() {
  const { t } = useUiLanguage();
  const [state, setState] = useState<DesktopUpdateState | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const runtime = getDesktopRuntimeApi();
  const isDesktopRuntime = Boolean(runtime);
  const canCheckDesktopUpdate = canUseDesktopUpdateApi(runtime);
  const desktopAppVersion = getDesktopAppVersion();

  useEffect(() => {
    if (!canCheckDesktopUpdate) {
      setState(null);
      setIsChecking(false);
      return undefined;
    }

    let active = true;

    const syncDesktopUpdateState = async () => {
      try {
        const nextState = await runtime?.getUpdateState?.();
        if (active) {
          setState(normalizeDesktopUpdateState(nextState));
        }
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        setState({
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
      setState(normalizeDesktopUpdateState(nextState));
      setIsChecking(false);
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

    setIsChecking(true);
    setState((current) => ({
      ...(current || {}),
      status: 'checking',
      message: t('settings.desktopUpdateCheckingMessage'),
    }));

    try {
      const nextState = await runtime.checkForUpdates();
      setState(normalizeDesktopUpdateState(nextState));
    } catch (error: unknown) {
      setState({
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopUpdateErrorMessage'),
      });
    } finally {
      setIsChecking(false);
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
      setState((current) => ({
        ...(current || {}),
        status: 'error',
        message: t('settings.desktopManualUnsupported'),
      }));
      return;
    }

    try {
      setState((current) => ({
        ...(current || {}),
        status: 'installing',
        message: t('settings.desktopUpdateInstallingMessage'),
      }));
      await runtime.installDownloadedUpdate();
    } catch (error: unknown) {
      setState((current) => ({
        ...(current || {}),
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopManualUnsupported'),
      }));
    }
  }, [runtime, t]);

  const notice = useMemo(() => getDesktopUpdateNotice(state, t), [state, t]);

  return {
    isDesktopRuntime,
    canCheckDesktopUpdate,
    desktopAppVersion,
    state,
    isChecking,
    notice,
    checkForUpdates,
    openReleasePage,
    installDownloadedUpdate,
  };
}
