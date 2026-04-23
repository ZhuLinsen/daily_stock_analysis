const configuredApiBaseUrl = import.meta.env.VITE_API_URL?.trim();

declare const __APP_PACKAGE_VERSION__: string | undefined;
declare const __APP_BUILD_TIME__: string | undefined;

const PLACEHOLDER_WEB_VERSION = '0.0.0';
const UNKNOWN_BUILD_TIME = '未提供';

// 默认保持同源 API，避免生产/静态部署时把请求错误打到用户本机 localhost。
// 仅在显式提供 VITE_API_URL 时才覆盖默认行为。
export const API_BASE_URL = configuredApiBaseUrl || '';

export type WebBuildInfo = {
  version: string;
  rawVersion: string;
  buildId: string;
  buildTime: string;
  isFallbackVersion: boolean;
};

function padBuildPart(value: number) {
  return value.toString().padStart(2, '0');
}

export function normalizeBuildTimestamp(buildTimestamp?: string) {
  const normalized = buildTimestamp?.trim();
  if (!normalized) {
    return UNKNOWN_BUILD_TIME;
  }

  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return normalized;
  }

  return parsed.toISOString();
}

export function createBuildIdentifier(buildTimestamp?: string) {
  const normalized = buildTimestamp?.trim();
  if (!normalized || normalized === UNKNOWN_BUILD_TIME) {
    return 'build-local';
  }

  const parsed = new Date(normalized);
  if (!Number.isNaN(parsed.getTime())) {
    const datePart = `${parsed.getUTCFullYear()}${padBuildPart(parsed.getUTCMonth() + 1)}${padBuildPart(parsed.getUTCDate())}`;
    const timePart = `${padBuildPart(parsed.getUTCHours())}${padBuildPart(parsed.getUTCMinutes())}${padBuildPart(parsed.getUTCSeconds())}`;
    return `build-${datePart}-${timePart}Z`;
  }

  const compactValue = normalized.replace(/[^0-9A-Za-z]+/g, '-').replace(/^-+|-+$/g, '');
  return compactValue ? `build-${compactValue}` : 'build-local';
}

export function resolveWebBuildInfo({
  packageVersion,
  buildTimestamp,
}: {
  packageVersion?: string;
  buildTimestamp?: string;
}): WebBuildInfo {
  const rawVersion = packageVersion?.trim() || PLACEHOLDER_WEB_VERSION;
  const buildTime = normalizeBuildTimestamp(buildTimestamp);
  const buildId = createBuildIdentifier(buildTime);
  const isFallbackVersion = rawVersion === PLACEHOLDER_WEB_VERSION;

  return {
    version: isFallbackVersion ? buildId : rawVersion,
    rawVersion,
    buildId,
    buildTime,
    isFallbackVersion,
  };
}

const runtimePackageVersion = typeof __APP_PACKAGE_VERSION__ === 'string'
  ? __APP_PACKAGE_VERSION__.trim()
  : PLACEHOLDER_WEB_VERSION;
const runtimeBuildTime = typeof __APP_BUILD_TIME__ === 'string'
  ? __APP_BUILD_TIME__.trim()
  : '';

export const WEB_BUILD_INFO = resolveWebBuildInfo({
  packageVersion: runtimePackageVersion,
  buildTimestamp: runtimeBuildTime,
});
