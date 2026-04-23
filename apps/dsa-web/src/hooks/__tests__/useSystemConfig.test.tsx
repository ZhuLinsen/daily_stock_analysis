import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSystemConfig } from '../useSystemConfig';

const { getConfig, validate, update } = vi.hoisted(() => ({
  getConfig: vi.fn(),
  validate: vi.fn(),
  update: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getConfig,
    validate,
    update,
  },
  SystemConfigConflictError: class extends Error {},
  SystemConfigValidationError: class extends Error {
    issues: unknown[] = [];
    parsedError = {
      title: 'validation error',
      message: 'validation error',
      rawMessage: 'validation error',
      category: 'http_error',
    };
  },
}));

const sampleConfig = {
  configVersion: 'v1',
  maskToken: '******',
  items: [
    {
      key: 'STOCK_LIST',
      value: 'SH600000',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'STOCK_LIST',
        category: 'base',
        dataType: 'string',
        uiControl: 'textarea',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 1,
      },
    },
  ],
};

describe('useSystemConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getConfig.mockResolvedValue(sampleConfig);
    validate.mockResolvedValue({ valid: true, issues: [] });
    update.mockResolvedValue({ warnings: [] });
  });

  it('keeps load callback stable after a successful load', async () => {
    const { result } = renderHook(() => useSystemConfig());
    const firstLoad = result.current.load;

    await act(async () => {
      await result.current.load();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(getConfig).toHaveBeenCalledTimes(1);
    expect(result.current.load).toBe(firstLoad);
  });
});
