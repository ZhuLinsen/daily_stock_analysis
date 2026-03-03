import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  SystemConfigConflictResponse,
  SystemConfigResponse,
  SystemConfigSchemaResponse,
  SystemConfigValidationErrorResponse,
  UpdateSystemConfigRequest,
  UpdateSystemConfigResponse,
  ValidateSystemConfigRequest,
  ValidateSystemConfigResponse,
} from '../types/systemConfig';

type ApiErrorPayload = {
  error?: string;
  message?: string;
  issues?: unknown;
  current_config_version?: string;
};

export class SystemConfigValidationError extends Error {
  issues: SystemConfigValidationErrorResponse['issues'];

  constructor(message: string, issues: SystemConfigValidationErrorResponse['issues']) {
    super(message);
    this.name = 'SystemConfigValidationError';
    this.issues = issues;
  }
}

export class SystemConfigConflictError extends Error {
  currentConfigVersion?: string;

  constructor(message: string, currentConfigVersion?: string) {
    super(message);
    this.name = 'SystemConfigConflictError';
    this.currentConfigVersion = currentConfigVersion;
  }
}

function toSnakeUpdatePayload(payload: UpdateSystemConfigRequest): Record<string, unknown> {
  return {
    config_version: payload.configVersion,
    mask_token: payload.maskToken ?? '******',
    reload_now: payload.reloadNow ?? true,
    items: payload.items.map((item) => ({
      key: item.key,
      value: item.value,
    })),
  };
}

function toSnakeValidatePayload(payload: ValidateSystemConfigRequest): Record<string, unknown> {
  return {
    items: payload.items.map((item) => ({
      key: item.key,
      value: item.value,
    })),
  };
}

function extractApiMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object' || !('response' in error)) {
    return fallback;
  }

  const response = (error as { response?: { data?: ApiErrorPayload } }).response;
  return response?.data?.message || fallback;
}

export const systemConfigApi = {
  async getConfig(includeSchema = true): Promise<SystemConfigResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/system/config', {
      params: { include_schema: includeSchema },
    });
    return toCamelCase<SystemConfigResponse>(response.data);
  },

  async getSchema(): Promise<SystemConfigSchemaResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/system/config/schema');
    return toCamelCase<SystemConfigSchemaResponse>(response.data);
  },

  async validate(payload: ValidateSystemConfigRequest): Promise<ValidateSystemConfigResponse> {
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/system/config/validate',
      toSnakeValidatePayload(payload),
    );
    return toCamelCase<ValidateSystemConfigResponse>(response.data);
  },

  async update(payload: UpdateSystemConfigRequest): Promise<UpdateSystemConfigResponse> {
    try {
      const response = await apiClient.put<Record<string, unknown>>(
        '/api/v1/system/config',
        toSnakeUpdatePayload(payload),
      );
      return toCamelCase<UpdateSystemConfigResponse>(response.data);
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'response' in error) {
        const status = (error as { response?: { status?: number } }).response?.status;
        const payloadData = (error as { response?: { data?: ApiErrorPayload } }).response?.data;

        if (status === 400) {
          const validationError = toCamelCase<SystemConfigValidationErrorResponse>(payloadData ?? {});
          throw new SystemConfigValidationError(
            validationError.message || '配置校验失败',
            validationError.issues || [],
          );
        }

        if (status === 409) {
          const conflict = toCamelCase<SystemConfigConflictResponse>(payloadData ?? {});
          throw new SystemConfigConflictError(
            conflict.message || '配置版本冲突',
            conflict.currentConfigVersion,
          );
        }
      }

      throw new Error(extractApiMessage(error, '更新系统配置失败'));
    }
  },
};
