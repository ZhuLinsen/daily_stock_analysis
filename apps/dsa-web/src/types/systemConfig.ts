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
  options: string[];
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
