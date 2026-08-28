export type DesktopRuntimeApi = {
  version?: unknown;
  getUpdateState?: () => Promise<RawDesktopUpdateState>;
  checkForUpdates?: () => Promise<RawDesktopUpdateState>;
  installDownloadedUpdate?: () => Promise<boolean>;
  openReleasePage?: (releaseUrl?: string) => Promise<boolean>;
  onUpdateStateChange?: (listener: (state: RawDesktopUpdateState) => void) => (() => void) | void;
};

export type DesktopWindow = Window & {
  dsaDesktop?: DesktopRuntimeApi;
};

export type DesktopUpdateState = {
  status?: string;
  updateMode?: string;
  currentVersion?: string;
  latestVersion?: string;
  releaseUrl?: string;
  checkedAt?: string;
  publishedAt?: string;
  message?: string;
  releaseName?: string;
  tagName?: string;
  downloadPercent?: number | null;
  downloadedBytes?: number | null;
  totalBytes?: number | null;
};

export type RawDesktopUpdateState = {
  status?: unknown;
  updateMode?: unknown;
  currentVersion?: unknown;
  latestVersion?: unknown;
  releaseUrl?: unknown;
  checkedAt?: unknown;
  publishedAt?: unknown;
  message?: unknown;
  releaseName?: unknown;
  tagName?: unknown;
  downloadPercent?: unknown;
  downloadedBytes?: unknown;
  totalBytes?: unknown;
};

export function trimDesktopRuntimeString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

export function normalizeDesktopRuntimeNumber(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

export function getDesktopRuntimeApi() {
  if (typeof window === 'undefined') {
    return undefined;
  }

  return (window as DesktopWindow).dsaDesktop;
}

export function getDesktopAppVersion() {
  return trimDesktopRuntimeString(getDesktopRuntimeApi()?.version);
}

export function canUseDesktopUpdateApi(runtime = getDesktopRuntimeApi()) {
  return Boolean(runtime?.getUpdateState && runtime?.checkForUpdates && runtime?.openReleasePage);
}
