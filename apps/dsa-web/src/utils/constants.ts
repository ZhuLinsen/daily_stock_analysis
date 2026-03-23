const configuredApiBaseUrl = import.meta.env.VITE_API_URL?.trim();

// 默认保持同源 API，避免生产/静态部署时把请求错误打到用户本机 localhost。
// 仅在显式提供 VITE_API_URL 时才覆盖默认行为。
export const API_BASE_URL = configuredApiBaseUrl || '';
