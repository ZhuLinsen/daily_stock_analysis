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

describe('Parallel Search MCP settings help', () => {
  it('keeps the Chinese settings copy default-off and fallback-only', () => {
    const help = getSettingsHelpContent(
      'settings.data_source.PARALLEL_SEARCH_MCP_ENABLED',
      undefined,
      'zh',
    );
    const visibleCopy = flattenHelp(help);

    expect(help?.title).toContain('Parallel Search MCP');
    expect(visibleCopy).toContain('默认关闭');
    expect(visibleCopy).toContain('不参与正常的多引擎轮换');
    expect(visibleCopy).toContain('https://search.parallel.ai/mcp');
    expect(getFieldDescriptionZh('PARALLEL_SEARCH_MCP_ENABLED')).toContain('末位兜底');
  });

  it('keeps the English settings copy default-off and fallback-only', () => {
    const help = getSettingsHelpContent(
      'settings.data_source.PARALLEL_SEARCH_MCP_ENABLED',
      undefined,
      'en',
    );
    const visibleCopy = flattenHelp(help);

    expect(help?.title).toContain('Parallel Search MCP');
    expect(visibleCopy).toContain('Disabled by default');
    expect(visibleCopy).toContain('never joins normal multi-provider rotation');
    expect(visibleCopy).toContain('https://search.parallel.ai/mcp');
  });
});
