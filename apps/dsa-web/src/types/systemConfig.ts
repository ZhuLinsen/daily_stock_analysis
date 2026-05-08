export type SystemConfigCategory =
  | 'base'
  | 'data_source'
  | 'ai_model'
  | 'notification'
  | 'system'
  | 'agent'
  | 'backtest'
  | 'uncategorized';

export type SystemConfigDataType =
  | 'string'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'array'
  | 'json'
  | 'time';

export type SystemConfigUIControl =
  | 'text'
  | 'password'
  | 'number'
  | 'select'
  | 'textarea'
  | 'switch'
  | 'time';

export interface SystemConfigOption {
  label: string;
  value: string;
}

export interface SystemConfigFieldSchema {
  key: string;
  title?: string;
  description?: string;
  category: SystemConfigCategory;
  dataType: SystemConfigDataType;
  uiControl: SystemConfigUIControl;
  isSensitive: boolean;
  isRequired: boolean;
  isEditable: boolean;
  defaultValue?: string | null;
  options: Array<string | SystemConfigOption>;
  validation: Record<string, unknown>;
  displayOrder: number;
}

export interface SystemConfigCategorySchema {
  category: SystemConfigCategory;
  title: string;
  description?: string;
  displayOrder: number;
  fields: SystemConfigFieldSchema[];
}

export interface SystemConfigSchemaResponse {
  schemaVersion: string;
  categories: SystemConfigCategorySchema[];
}

export interface SystemConfigItem {
  key: string;
  value: string;
  rawValueExists: boolean;
  isMasked: boolean;
  schema?: SystemConfigFieldSchema;
}

export interface SystemConfigResponse {
  configVersion: string;
  maskToken: string;
  items: SystemConfigItem[];
  updatedAt?: string;
}

export interface ExportSystemConfigResponse {
  content: string;
  configVersion: string;
  updatedAt?: string;
}

export interface SystemConfigUpdateItem {
  key: string;
  value: string;
}

export interface UpdateSystemConfigRequest {
  configVersion: string;
  maskToken?: string;
  reloadNow?: boolean;
  items: SystemConfigUpdateItem[];
}

export interface UpdateSystemConfigResponse {
  success: boolean;
  configVersion: string;
  appliedCount: number;
  skippedMaskedCount: number;
  reloadTriggered: boolean;
  updatedKeys: string[];
  warnings: string[];
}

export interface ValidateSystemConfigRequest {
  items: SystemConfigUpdateItem[];
}

export interface ImportSystemConfigRequest {
  configVersion: string;
  content: string;
  reloadNow?: boolean;
}

export interface ConfigValidationIssue {
  key: string;
  code: string;
  message: string;
  severity: 'error' | 'warning';
  expected?: string;
  actual?: string;
}

export interface ValidateSystemConfigResponse {
  valid: boolean;
  issues: ConfigValidationIssue[];
}

export interface TestLLMChannelRequest {
  name: string;
  protocol: string;
  baseUrl?: string;
  apiKey?: string;
  models: string[];
  enabled?: boolean;
  timeoutSeconds?: number;
  capabilityChecks?: LLMCapabilityCheck[];
}

export type LLMCapabilityCheck = 'json' | 'tools' | 'vision' | 'stream';

export interface LLMCapabilityCheckResult {
  status: 'passed' | 'failed' | 'skipped';
  message: string;
  errorCode?: string | null;
  stage: string;
  retryable?: boolean | null;
  latencyMs?: number | null;
  details?: Record<string, unknown>;
}

export interface TestLLMChannelResponse {
  success: boolean;
  message: string;
  error?: string | null;
  errorCode?: string | null;
  stage?: string | null;
  retryable?: boolean | null;
  details?: Record<string, unknown>;
  resolvedProtocol?: string | null;
  resolvedModel?: string | null;
  latencyMs?: number | null;
  capabilityResults?: Partial<Record<LLMCapabilityCheck, LLMCapabilityCheckResult>>;
}

export type NotificationTestChannel =
  | 'wechat'
  | 'feishu'
  | 'telegram'
  | 'email'
  | 'pushover'
  | 'pushplus'
  | 'serverchan3'
  | 'custom'
  | 'discord'
  | 'slack'
  | 'astrbot';

export interface NotificationTestAttempt {
  channel: NotificationTestChannel;
  success: boolean;
  message: string;
  target?: string | null;
  errorCode?: string | null;
  stage: string;
  retryable: boolean;
  latencyMs?: number | null;
  httpStatus?: number | null;
}

export interface TestNotificationChannelRequest {
  channel: NotificationTestChannel;
  items?: SystemConfigUpdateItem[];
  maskToken?: string;
  title?: string;
  content?: string;
  timeoutSeconds?: number;
}

export interface TestNotificationChannelResponse {
  success: boolean;
  message: string;
  errorCode?: string | null;
  stage?: string | null;
  retryable: boolean;
  latencyMs?: number | null;
  attempts: NotificationTestAttempt[];
}

export interface DiscoverLLMChannelModelsRequest {
  name: string;
  protocol: string;
  baseUrl?: string;
  apiKey?: string;
  models?: string[];
  timeoutSeconds?: number;
}

export interface DiscoverLLMChannelModelsResponse {
  success: boolean;
  message: string;
  error?: string | null;
  errorCode?: string | null;
  stage?: string | null;
  retryable?: boolean | null;
  details?: Record<string, unknown>;
  resolvedProtocol?: string | null;
  models: string[];
  latencyMs?: number | null;
}

export interface SystemConfigValidationErrorResponse {
  error: string;
  message: string;
  issues: ConfigValidationIssue[];
}

export interface SystemConfigConflictResponse {
  error: string;
  message: string;
  currentConfigVersion: string;
}
