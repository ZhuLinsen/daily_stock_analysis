import { describe, expect, it } from 'vitest';
import type { SetupStatusResponse } from '../../types/systemConfig';
import { localizeSetupStatus } from '../systemConfigI18n';

const status: SetupStatusResponse = {
  isComplete: false,
  readyForSmoke: false,
  requiredMissingKeys: ['stock_list'],
  checks: [
    {
      key: 'stock_list',
      title: '自选股',
      titleEn: 'Watchlist',
      category: 'base',
      required: true,
      status: 'needs_action',
      message: '当前 STOCK_LIST 为空。',
      messageEn: 'STOCK_LIST is empty.',
      nextStep: '请至少添加 1 只股票用于首次试跑。',
      nextStepEn: 'Add at least one stock for the first test run.',
    },
    {
      key: 'notification',
      title: '通知渠道',
      category: 'notification',
      required: false,
      status: 'configured',
      message: '已检测到至少一个通知渠道配置。',
      nextStep: null,
    },
  ],
};

describe('localizeSetupStatus', () => {
  it('uses the English texts in English and keeps Chinese in Chinese', () => {
    const en = localizeSetupStatus(status, 'en')!;
    expect(en.checks[0]).toMatchObject({
      title: 'Watchlist',
      message: 'STOCK_LIST is empty.',
      nextStep: 'Add at least one stock for the first test run.',
    });
    expect(localizeSetupStatus(status, 'zh')).toBe(status);
  });

  it('falls back to the original text when the API sends no English', () => {
    const en = localizeSetupStatus(status, 'en')!;
    expect(en.checks[1]).toMatchObject({ title: '通知渠道', nextStep: null });
    expect(localizeSetupStatus(null, 'en')).toBeNull();
  });
});
