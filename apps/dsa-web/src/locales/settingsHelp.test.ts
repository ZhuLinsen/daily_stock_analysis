import { describe, expect, it } from 'vitest';

import { getSettingsHelpContent } from './settingsHelp';
import { getFieldDescriptionZh } from '../utils/systemConfigI18n';

const flattenHelp = (help: ReturnType<typeof getSettingsHelpContent>) => [
  help?.summary,
  help?.usage,
  ...(help?.valueNotes ?? []),
  ...(help?.impact ?? []),
  ...(help?.notes ?? []),
].filter(Boolean).join(' ');

describe('SearXNG settings help', () => {
  it('describes public SearXNG discovery as opt-in in Chinese', () => {
    const description = getFieldDescriptionZh('SEARXNG_PUBLIC_INSTANCES_ENABLED');

    expect(description).toContain('默认关闭');
    expect(description).toContain('设为 true');
    expect(description).not.toContain('设为 false 可禁用该默认行为');
  });
});

describe('Skill Outcome auto-weight settings help', () => {
  it('describes the attributable Outcome threshold in Chinese', () => {
    const help = getSettingsHelpContent(
      'settings.agent.AGENT_SKILL_AUTOWEIGHT',
      undefined,
      'zh',
    );
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('Outcome');
    expect(visibleCopy).toContain('30');
    expect(visibleCopy).toContain('1.0');
    expect(visibleCopy).toContain('不使用全局回测胜率');
    expect(visibleCopy).not.toContain('依赖回测');
    expect(getFieldDescriptionZh('AGENT_SKILL_AUTOWEIGHT')).toContain('Outcome');
  });

  it('describes the attributable Outcome threshold in English', () => {
    const help = getSettingsHelpContent(
      'settings.agent.AGENT_SKILL_AUTOWEIGHT',
      undefined,
      'en',
    );
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('Outcome');
    expect(visibleCopy).toContain('30');
    expect(visibleCopy).toContain('1.0');
    expect(visibleCopy).toContain('Global backtest win rates never substitute');
    expect(visibleCopy).not.toContain('Depends on backtest');
  });

  it('does not present Backtest as the Skill auto-weight data source', () => {
    const zhHelp = flattenHelp(getSettingsHelpContent(
      'settings.backtest.BACKTEST_ENABLED',
      undefined,
      'zh',
    ));
    const enHelp = flattenHelp(getSettingsHelpContent(
      'settings.backtest.BACKTEST_ENABLED',
      undefined,
      'en',
    ));

    expect(zhHelp).toContain('Skill Outcome');
    expect(zhHelp).toContain('不直接');
    expect(enHelp).toContain('Skill Outcome');
    expect(enHelp).toContain('does not directly');
  });
});

describe('TDX local vipdoc settings help', () => {
  it('describes the local vipdoc data source in Chinese', () => {
    const help = getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_PATH',
      undefined,
      'zh',
    );
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('vipdoc');
    expect(visibleCopy).toContain('回退网络数据源');
    expect(visibleCopy).toContain('未复权');
    expect(visibleCopy).not.toContain('必须配置到 GitHub Actions Secrets');

    const priority = flattenHelp(getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_PRIORITY',
      undefined,
      'zh',
    ));
    expect(priority).toContain('默认 0');
    expect(getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_MAX_STALE_DAYS',
      undefined,
      'zh',
    )?.summary).toContain('过期');
  });

  it('describes the local vipdoc data source in English', () => {
    const help = getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_PATH',
      undefined,
      'en',
    );
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('vipdoc');
    expect(visibleCopy).toContain('fallback to network providers');
    expect(visibleCopy).toContain('not registered');

    const priority = flattenHelp(getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_PRIORITY',
      undefined,
      'en',
    ));
    expect(priority).toContain('Default 0');
    expect(getSettingsHelpContent(
      'settings.data_source.TDX_LOCAL_MAX_STALE_DAYS',
      undefined,
      'en',
    )?.summary).toContain('stale');
  });
});
