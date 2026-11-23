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

describe('Zulip and Raft settings help', () => {
  it('provides channel-specific English descriptions for each field', () => {
    for (const key of ['ZULIP_URL', 'ZULIP_BOT_EMAIL', 'ZULIP_API_KEY', 'ZULIP_STREAM', 'ZULIP_TOPIC',
      'RAFT_URL', 'RAFT_AGENT_KEY', 'RAFT_TARGET']) {
      const help = getSettingsHelpContent(`settings.notification.${key}`, undefined, 'en');
      expect(help?.summary).toBeTruthy();
      expect(help?.title).toContain(key.startsWith('ZULIP') ? 'Zulip' : 'Raft');
      expect(help?.summary).not.toContain('Discord');
    }
  });
});

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
