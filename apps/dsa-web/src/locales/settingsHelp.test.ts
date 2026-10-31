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

describe('News digest settings help', () => {
  it('describes the opt-in daily digest windows in Chinese', () => {
    const help = getSettingsHelpContent('settings.system.news_digest', undefined, 'zh');
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('默认关闭');
    expect(visibleCopy).toContain('08:00-09:15');
    expect(visibleCopy).toContain('09:00-18:00');
    expect(visibleCopy).toContain('每日一份');
    expect(visibleCopy).toContain('仅支持 cn');
  });

  it('describes the opt-in daily digest windows in English', () => {
    const help = getSettingsHelpContent('settings.system.news_digest', undefined, 'en');
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('Off by default');
    expect(visibleCopy).toContain('08:00-09:15');
    expect(visibleCopy).toContain('09:00-18:00');
    expect(visibleCopy).toContain('At most once per day');
    expect(visibleCopy).toContain('cn only');
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
