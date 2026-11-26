import axios from 'axios';
import type { UiLanguage } from '../i18n/uiText';
import { resolveActiveUiLanguage } from '../utils/format';

const parsedErrorResolvers = new WeakMap<ParsedApiError, (language: UiLanguage) => ParsedApiError>();
const originalErrorMessages = new WeakMap<object, string>();

export type ApiErrorCategory =
  | 'agent_disabled'
  | 'missing_params'
  | 'llm_not_configured'
  | 'model_tool_incompatible'
  | 'invalid_tool_call'
  | 'portfolio_oversell'
  | 'portfolio_busy'
  | 'upstream_llm_400'
  | 'upstream_timeout'
  | 'upstream_network'
  | 'local_connection_failed'
  | 'http_error'
  | 'unknown';

export interface ParsedApiError {
  title: string;
  message: string;
  rawMessage: string;
  status?: number;
  category: ApiErrorCategory;
  code?: string;
}

type ResponseLike = {
  status?: number;
  data?: unknown;
  statusText?: string;
};

type ErrorCarrier = {
  response?: ResponseLike;
  code?: string;
  message?: string;
  parsedError?: ParsedApiError;
  cause?: unknown;
};

type CreateParsedApiErrorOptions = {
  title: string;
  message: string;
  rawMessage?: string;
  status?: number;
  category?: ApiErrorCategory;
  code?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function pickString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function stringifyValue(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === 'string') {
    return value.trim() || null;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function getResponse(error: unknown): ResponseLike | undefined {
  if (!isRecord(error)) {
    return undefined;
  }

  const response = (error as ErrorCarrier).response;
  return response && typeof response === 'object' ? response : undefined;
}

function getErrorCode(error: unknown): string | undefined {
  return isRecord(error) && typeof (error as ErrorCarrier).code === 'string'
    ? (error as ErrorCarrier).code
    : undefined;
}

function getErrorMessage(error: unknown): string | null {
  if (typeof error === 'string') {
    return error.trim() || null;
  }

  if (error instanceof Error) {
    if (originalErrorMessages.has(error)) {
      return (originalErrorMessages.get(error) ?? '').trim() || null;
    }
    return error.message.trim() || null;
  }

  if (isRecord(error) && typeof (error as ErrorCarrier).message === 'string') {
    const message = (error as ErrorCarrier).message?.trim();
    return message || null;
  }

  return null;
}

function getCauseMessage(error: unknown): string | null {
  if (!isRecord(error)) {
    return null;
  }

  return getErrorMessage((error as ErrorCarrier).cause);
}

function buildMatchText(parts: Array<string | undefined | null>): string {
  return parts
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join(' | ')
    .toLowerCase();
}

function includesAny(haystack: string, needles: string[]): boolean {
  return needles.some((needle) => haystack.includes(needle.toLowerCase()));
}

function extractValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) {
    return null;
  }

  const parts = detail
    .map((item) => {
      if (!isRecord(item)) {
        return stringifyValue(item);
      }

      const location = Array.isArray(item.loc)
        ? item.loc.map((segment) => String(segment)).join('.')
        : null;
      const message = pickString(item.msg, item.message, item.error);
      if (!location && !message) {
        return stringifyValue(item);
      }
      return [location, message].filter(Boolean).join(': ');
    })
    .filter((entry): entry is string => Boolean(entry));

  return parts.length > 0 ? parts.join('; ') : null;
}

function extractErrorCode(data: unknown): string | null {
  if (!isRecord(data)) {
    return null;
  }

  const detail = data.detail;
  if (isRecord(detail)) {
    return pickString(detail.error, detail.code, data.error, data.code);
  }

  return pickString(data.error, data.code);
}

function extractConfigValidationIssues(data: unknown, language: UiLanguage): string | null {
  if (!isRecord(data)) return null;
  const payload = isRecord(data.detail) ? data.detail : data;
  if (!Array.isArray(payload.issues)) return null;
  const isEnglish = language === 'en';
  const separator = isEnglish ? ': ' : '：';
  const messages = payload.issues.filter(isRecord).map((issue) => {
    const key = pickString(issue.key);
    let message = pickString(issue.message);
    if (issue.code === 'missing_api_key') {
      message = isEnglish ? 'Please enter an API Key for this channel.' : '请填写此渠道的 API Key。';
    }
    if (issue.code === 'missing_models') {
      message = isEnglish ? 'Please enter available models for your account.' : '请填写账号可用的模型。';
    }
    if (issue.code === 'unknown_model') {
      message = isEnglish
        ? 'Please choose a model from an enabled channel or clear the invalid selection.'
        : '请选择当前启用渠道中的模型，或清空无效的模型选项。';
    }
    return message ? [key, message].filter(Boolean).join(separator) : null;
  }).filter((message): message is string => Boolean(message));
  return messages.length ? messages.join('\n') : null;
}

export function extractErrorPayloadText(data: unknown): string | null {
  if (typeof data === 'string') {
    return data.trim() || null;
  }

  if (Array.isArray(data)) {
    return extractValidationDetail(data) ?? stringifyValue(data);
  }

  if (!isRecord(data)) {
    return stringifyValue(data);
  }

  const detail = data.detail;
  if (isRecord(detail)) {
    return (
      pickString(detail.message, detail.error)
      ?? extractValidationDetail(detail.detail)
      ?? stringifyValue(detail)
    );
  }

  return (
    pickString(
      detail,
      data.message,
      data.error,
      data.title,
      data.reason,
      data.description,
      data.msg,
    )
    ?? extractValidationDetail(detail)
    ?? stringifyValue(data)
  );
}

export function createParsedApiError(options: CreateParsedApiErrorOptions): ParsedApiError {
  return {
    title: options.title,
    message: options.message,
    rawMessage: options.rawMessage?.trim() || options.message,
    status: options.status,
    category: options.category ?? 'unknown',
    ...(options.code ? { code: options.code } : {}),
  };
}

export function createLocalizedParsedApiError(
  resolver: (language: UiLanguage) => ParsedApiError,
  language?: UiLanguage,
): ParsedApiError {
  const resolved = resolver(resolveActiveUiLanguage(language));
  parsedErrorResolvers.set(
    resolved,
    (nextLanguage) => createLocalizedParsedApiError(resolver, nextLanguage),
  );
  return resolved;
}

export function localizeParsedApiError(parsed: ParsedApiError, language?: UiLanguage): ParsedApiError {
  const resolver = parsedErrorResolvers.get(parsed);
  return resolver ? resolver(resolveActiveUiLanguage(language)) : parsed;
}

export function isParsedApiError(value: unknown): value is ParsedApiError {
  return isRecord(value)
    && typeof value.title === 'string'
    && typeof value.message === 'string'
    && typeof value.rawMessage === 'string'
    && typeof value.category === 'string';
}

export function isApiRequestError(
  value: unknown,
): value is Error & ErrorCarrier & { parsedError: ParsedApiError } {
  return value instanceof Error
    && isRecord(value)
    && isParsedApiError((value as ErrorCarrier).parsedError);
}

export function formatParsedApiError(parsed: ParsedApiError, language?: UiLanguage): string {
  if (!parsed.title.trim()) {
    return parsed.message;
  }
  if (parsed.title === parsed.message) {
    return parsed.title;
  }
  const separator = resolveActiveUiLanguage(language) === 'en' ? ': ' : '：';
  return `${parsed.title}${separator}${parsed.message}`;
}

export function getParsedApiError(error: unknown, language?: UiLanguage): ParsedApiError {
  const activeLanguage = resolveActiveUiLanguage(language);
  if (isParsedApiError(error)) {
    return localizeParsedApiError(error, activeLanguage);
  }
  if (isRecord(error) && isParsedApiError((error as ErrorCarrier).parsedError)) {
    return localizeParsedApiError((error as ErrorCarrier).parsedError as ParsedApiError, activeLanguage);
  }
  return parseApiError(error, activeLanguage);
}

export function createApiError(
  parsed: ParsedApiError,
  extra: { response?: ResponseLike; code?: string; cause?: unknown } = {},
): Error & ErrorCarrier & { status?: number; category: ApiErrorCategory; rawMessage: string } {
  const apiError = new Error(formatParsedApiError(parsed)) as Error & ErrorCarrier & {
    status?: number;
    category: ApiErrorCategory;
    rawMessage: string;
  };
  apiError.name = 'ApiRequestError';
  apiError.parsedError = parsed;
  apiError.response = extra.response;
  apiError.code = extra.code ?? parsed.code;
  apiError.status = parsed.status;
  apiError.category = parsed.category;
  apiError.rawMessage = parsed.rawMessage;
  if (extra.cause !== undefined) {
    apiError.cause = extra.cause;
  }
  return apiError;
}

export function attachParsedApiError(error: unknown): ParsedApiError {
  if (error instanceof Error && !originalErrorMessages.has(error)) {
    originalErrorMessages.set(error, error.message);
  }
  const parsed = parseApiError(error);
  if (isRecord(error)) {
    const carrier = error as ErrorCarrier;
    carrier.parsedError = parsed;
  }
  if (error instanceof Error) {
    error.name = 'ApiRequestError';
    error.message = formatParsedApiError(parsed);
  }
  return parsed;
}

export function isLocalConnectionFailure(error: unknown): boolean {
  return parseApiError(error).category === 'local_connection_failed';
}

function buildParsedApiError(error: unknown, activeLanguage: UiLanguage): ParsedApiError {
  const isEnglish = activeLanguage === 'en';
  const response = getResponse(error);
  const status = response?.status;
  const payloadText = extractErrorPayloadText(response?.data);
  const errorCode = extractErrorCode(response?.data);
  const errorMessage = getErrorMessage(error);
  const causeMessage = getCauseMessage(error);
  const code = getErrorCode(error);
  const defaultFallbackMessage = isEnglish
    ? 'Request did not complete. Please try again later.'
    : '请求未成功完成，请稍后重试。';
  const rawMessage = pickString(payloadText, response?.statusText, errorMessage, causeMessage, code)
    ?? defaultFallbackMessage;
  const matchText = buildMatchText([rawMessage, errorMessage, causeMessage, code, errorCode, response?.statusText]);

  if (errorCode === 'validation_failed') {
    const issues = extractConfigValidationIssues(response?.data, activeLanguage);
    const message = issues
      ? (isEnglish ? `Please fix the following configuration issues and try again:\n${issues}` : `请修正以下配置后重试：\n${issues}`)
      : (isEnglish ? 'Please check your channel API Key, models, and runtime parameters, then try again.' : '请检查渠道的 API Key、模型和运行参数后重试。');
    return createParsedApiError({
      title: isEnglish ? 'Configuration Needs Attention' : '配置需要调整',
      message,
      rawMessage: message,
      status,
      category: 'http_error',
      code: errorCode,
    });
  }

  if (errorCode === 'backend_removed') {
    return createParsedApiError({
      title: isEnglish ? 'Ask AI Backend Removed' : '问股后端已移除',
      message: rawMessage,
      rawMessage,
      status,
      code: 'backend_removed',
      category: 'http_error',
    });
  }

  if (errorCode === 'session_state_conflict' || code === 'session_state_conflict') {
    return createParsedApiError({
      title: isEnglish ? 'Session Updated' : '会话已更新',
      message: isEnglish
        ? 'Please refresh the session and try again. Your current message was not accepted; keep your question and selections.'
        : '请刷新会话后重试。当前输入尚未被接受，请保留问题与选择。',
      rawMessage,
      status,
      code: 'session_state_conflict',
      category: 'http_error',
    });
  }

  if (includesAny(matchText, ['agent mode is not enabled', 'agent_mode'])) {
    return createParsedApiError({
      title: isEnglish ? 'Agent Mode Disabled' : 'Agent 模式未开启',
      message: isEnglish
        ? 'This feature requires Agent mode. Please enable it and try again.'
        : '当前功能依赖 Agent 模式，请先开启后再重试。',
      rawMessage,
      status,
      category: 'agent_disabled',
    });
  }

  const hasStockCodeField = includesAny(matchText, ['stock_code', 'stock_codes']);
  const hasMissingParamText = includesAny(matchText, ['必须提供 stock_code 或 stock_codes', 'missing', 'required']);
  if (hasStockCodeField && hasMissingParamText) {
    return createParsedApiError({
      title: isEnglish ? 'Missing Required Parameters' : '请求缺少必要参数',
      message: isEnglish
        ? 'Please enter a stock code or required inputs and try again.'
        : '请先补充股票代码或必要输入后再试。',
      rawMessage,
      status,
      category: 'missing_params',
    });
  }

  if (errorCode === 'portfolio_oversell' || includesAny(matchText, ['oversell detected'])) {
    return createParsedApiError({
      title: isEnglish ? 'Sell Quantity Exceeds Holdings' : '卖出数量超过可用持仓',
      message: isEnglish
        ? 'Sell quantity exceeds available holdings. Please delete or correct the corresponding sell entry and try again.'
        : '卖出数量超过当前可用持仓，请删除或修正对应卖出流水后重试。',
      rawMessage,
      status,
      category: 'portfolio_oversell',
    });
  }

  if (errorCode === 'portfolio_busy' || includesAny(matchText, ['portfolio ledger is busy'])) {
    return createParsedApiError({
      title: isEnglish ? 'Portfolio Ledger Busy' : '持仓账本正忙',
      message: isEnglish
        ? 'Another portfolio update is currently in progress. Please try again shortly.'
        : '持仓账本正在处理另一笔变更，请稍后重试。',
      rawMessage,
      status,
      category: 'portfolio_busy',
    });
  }

  if (errorCode === 'screening_unavailable' || includesAny(matchText, ['内建选股引擎初始化失败', '选股功能初始化失败'])) {
    return createParsedApiError({
      title: isEnglish ? 'Stock Screening Unavailable' : '选股功能未就绪',
      message: isEnglish
        ? 'Stock screening is not ready. Please check strategy configuration, data dependencies, and server logs.'
        : '选股功能暂不可用，请检查策略配置、数据依赖和服务日志。',
      rawMessage,
      status,
      category: 'http_error',
      code: 'screening_unavailable',
    });
  }

  if (errorCode === 'screening_screen_task_not_found') {
    return createParsedApiError({
      title: isEnglish ? 'Screening Task Not Recoverable' : '选股任务不可恢复',
      message: isEnglish
        ? 'The server could not find this screening task (it may have restarted or expired). Please run a new screen.'
        : '服务端没有找到这次选股任务，可能后端已重启或任务记录已清理，请重新运行选股。',
      rawMessage,
      status,
      category: 'http_error',
      code: 'screening_screen_task_not_found',
    });
  }

  if (errorCode === 'screening_screen_failed') {
    return createParsedApiError({
      title: isEnglish ? 'Stock Screening Failed' : '选股失败',
      message: isEnglish
        ? 'Failed to reach quote, snapshot, or model services during screening. Please retry or check network/proxy settings.'
        : '选股访问行情、快照或模型服务失败，请稍后重试，或检查网络与代理设置。',
      rawMessage,
      status,
      category: 'upstream_network',
      code: 'screening_screen_failed',
    });
  }

  const noConfiguredLlm = (
    includesAny(matchText, ['all llm models failed']) && includesAny(matchText, ['last error: none'])
  ) || includesAny(matchText, [
    'no llm configured',
    'no effective primary model configured',
    'litellm_model not configured',
    'ai analysis will be unavailable',
  ]);
  if (noConfiguredLlm) {
    return createParsedApiError({
      title: isEnglish ? 'No Usable LLM Configured' : '系统没有配置可用的 LLM 模型',
      message: isEnglish
        ? 'Please configure a primary model, enabled channel, or API Key in Settings before retrying.'
        : '请先在系统设置中配置主模型、可用渠道或相关 API Key 后再重试。',
      rawMessage,
      status,
      category: 'llm_not_configured',
    });
  }

  if (includesAny(matchText, [
    'tool call',
    'function call',
    'does not support tools',
    'tools is not supported',
    'reasoning',
  ])) {
    return createParsedApiError({
      title: isEnglish ? 'Model Does Not Support Tool Calling' : '当前模型不兼容工具调用',
      message: isEnglish
        ? 'This model is not suitable for Agent / tool-calling workflows. Please switch to a tool-capable model and retry.'
        : '当前模型不适合 Agent / 工具调用场景，请更换支持工具调用的模型后重试。',
      rawMessage,
      status,
      category: 'model_tool_incompatible',
    });
  }

  if (includesAny(matchText, [
    'thought_signature',
    'missing function',
    'missing tool',
    'invalid tool call',
    'invalid function call',
  ])) {
    return createParsedApiError({
      title: isEnglish ? 'Incomplete Upstream Tool Call' : '上游模型返回的数据结构不完整',
      message: isEnglish
        ? 'The upstream model returned an invalid tool-call structure. Try another model or disable reasoning mode and retry.'
        : '上游模型返回的工具调用结构不符合要求，请更换模型或关闭相关推理模式后重试。',
      rawMessage,
      status,
      category: 'invalid_tool_call',
    });
  }

  if (includesAny(matchText, ['timeout', 'timed out', 'read timeout', 'connect timeout']) || code === 'ECONNABORTED') {
    return createParsedApiError({
      title: isEnglish ? 'Upstream Request Timed Out' : '连接上游服务超时',
      message: isEnglish
        ? 'The server timed out waiting for an external dependency. Please retry or check network/proxy settings.'
        : '服务端访问外部依赖时超时，请稍后重试，或检查当前网络与代理设置。',
      rawMessage,
      status,
      category: 'upstream_timeout',
    });
  }

  if (
    status === 502
    || status === 503
    || includesAny(matchText, [
      'dns',
      'enotfound',
      'name or service not known',
      'temporary failure in name resolution',
      'proxy',
      'tunnel',
      '502',
      '503',
    ])
  ) {
    return createParsedApiError({
      title: isEnglish ? 'Server Cannot Reach External Services' : '服务端无法访问外部依赖',
      message: isEnglish
        ? 'The browser reached the local server, but the server failed to contact external model or data APIs. Check proxy, DNS, or outbound network settings.'
        : '页面已连接到本地服务，但本地服务访问外部模型或数据接口失败，请检查代理、DNS 或出网配置。',
      rawMessage,
      status,
      category: 'upstream_network',
    });
  }

  const hasLlmProviderHint = includesAny(matchText, [
    'chat/completions',
    'generativelanguage',
    'openai',
    'gemini',
  ]);
  if (status === 400 && hasLlmProviderHint) {
    return createParsedApiError({
      title: isEnglish ? 'Upstream Model Rejected Request' : '上游模型接口拒绝了当前请求',
      message: isEnglish
        ? 'The local server is running, but the upstream LLM API rejected the request. Check the model name, parameters, or tool compatibility.'
        : '本地服务正常，但上游模型接口拒绝了请求，请检查模型名称、参数格式或工具调用兼容性。',
      rawMessage,
      status,
      category: 'upstream_llm_400',
    });
  }

  const localConnectionFailed = !response && (
    includesAny(matchText, ['fetch failed', 'failed to fetch', 'network error', 'connection refused', 'econnrefused'])
    || code === 'ERR_NETWORK'
    || code === 'ECONNREFUSED'
  );
  if (localConnectionFailed) {
    return createParsedApiError({
      title: isEnglish ? 'Cannot Connect to Local Service' : '无法连接到本地服务',
      message: isEnglish
        ? 'Unable to reach the local Web service. Verify that the server is running and listening on the expected host and port.'
        : '浏览器当前无法连接到本地 Web 服务，请检查服务是否启动、监听地址是否正确、端口是否开放。',
      rawMessage,
      status,
      category: 'local_connection_failed',
    });
  }

  if (payloadText || status) {
    return createParsedApiError({
      title: isEnglish ? 'Request Failed' : '请求失败',
      message: payloadText ?? (isEnglish ? `Request failed (HTTP ${status}).` : `请求未成功完成（HTTP ${status}）。`),
      rawMessage,
      status,
      category: 'http_error',
    });
  }

  return createParsedApiError({
    title: isEnglish ? 'Request Failed' : '请求失败',
    message: rawMessage,
    rawMessage,
    status,
    category: 'unknown',
  });
}

export function parseApiError(error: unknown, language?: UiLanguage): ParsedApiError {
  if (isParsedApiError(error) && parsedErrorResolvers.has(error)) {
    return localizeParsedApiError(error, language);
  }
  return createLocalizedParsedApiError(
    (activeLanguage) => buildParsedApiError(error, activeLanguage),
    language,
  );
}

export function toApiErrorMessage(
  error: unknown,
  fallback?: string,
  language?: UiLanguage,
): string {
  const activeLanguage = resolveActiveUiLanguage(language);
  const resolvedFallback = fallback
    ?? (activeLanguage === 'en' ? 'Request did not complete. Please try again later.' : '请求未成功完成，请稍后重试。');
  const parsed = getParsedApiError(error, activeLanguage);
  const message = formatParsedApiError(parsed, activeLanguage);
  return message.trim() || resolvedFallback;
}

export function isAxiosApiError(error: unknown): boolean {
  return axios.isAxiosError(error);
}
