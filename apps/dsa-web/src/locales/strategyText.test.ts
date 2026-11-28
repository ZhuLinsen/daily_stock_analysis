import { describe, expect, it } from 'vitest';

import { BUILTIN_STRATEGY_TEXT, getStrategyCategory, localizeSkill } from './strategyText';

const bundledStrategyYaml = import.meta.glob('../../../../strategies/*.yaml', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const readField = (yaml: string, field: string): string | undefined =>
  yaml.match(new RegExp(`^${field}:\\s*(.+)$`, 'm'))?.[1].trim();

describe('BUILTIN_STRATEGY_TEXT', () => {
  const bundled = Object.values(bundledStrategyYaml).map((yaml) => ({
    id: readField(yaml, 'name') ?? '',
    name: readField(yaml, 'display_name') ?? '',
    description: readField(yaml, 'description') ?? '',
  }));

  it('covers every bundled strategy with zh text that matches the YAML', () => {
    expect(bundled.length).toBeGreaterThan(0);
    for (const strategy of bundled) {
      expect(BUILTIN_STRATEGY_TEXT[strategy.id]?.zh, strategy.id).toEqual({
        name: strategy.name,
        description: strategy.description,
      });
    }
    expect(Object.keys(BUILTIN_STRATEGY_TEXT).sort()).toEqual(bundled.map((s) => s.id).sort());
  });

  it('has English text for every bundled strategy', () => {
    for (const [id, text] of Object.entries(BUILTIN_STRATEGY_TEXT)) {
      expect(text.en.name, id).toMatch(/^[\x20-\x7E]+$/);
      expect(text.en.description, id).toMatch(/^[\x20-\x7E]+$/);
    }
  });
});

describe('localizeSkill', () => {
  const builtin = { id: 'chan_theory', name: '缠论', description: BUILTIN_STRATEGY_TEXT.chan_theory.zh.description };

  it('translates bundled strategy text in English', () => {
    expect(localizeSkill(builtin, 'en')).toEqual({
      id: 'chan_theory',
      name: 'Chan Theory',
      description: BUILTIN_STRATEGY_TEXT.chan_theory.en.description,
    });
  });

  it('keeps the API text in Chinese', () => {
    expect(localizeSkill(builtin, 'zh')).toBe(builtin);
  });

  it('keeps custom or overridden text unchanged', () => {
    const custom = { id: 'my_strategy', name: '我的策略', description: '自定义' };
    const overridden = { id: 'chan_theory', name: '我的缠论', description: '自定义描述' };
    expect(localizeSkill(custom, 'en')).toBe(custom);
    expect(localizeSkill(overridden, 'en')).toEqual(overridden);
  });

  it('ignores ids that match Object.prototype properties', () => {
    for (const id of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
      const custom = { id, name: '自定义', description: '自定义描述' };
      expect(localizeSkill(custom, 'en')).toBe(custom);
    }
  });
});

describe('getStrategyCategory', () => {
  it('resolves built-in quant strategies and normalizes explicit API categories', () => {
    expect(getStrategyCategory('vcp_breakout')).toBe('quant');
    expect(getStrategyCategory('bollinger_squeeze')).toBe('quant');
    expect(getStrategyCategory('bull_trend')).toBe('trend');
    expect(getStrategyCategory('bottom_volume')).toBe('pattern_reversal');
    expect(getStrategyCategory('chan_theory')).toBe('framework');

    expect(getStrategyCategory('custom_quant_skill', 'quant')).toBe('quant');
    expect(getStrategyCategory('custom_pattern_skill', 'pattern')).toBe('pattern_reversal');
    expect(getStrategyCategory('custom_reversal_skill', 'Reversal')).toBe('pattern_reversal');
    expect(getStrategyCategory('custom_unknown_skill', 'unknown')).toBe('framework');
    expect(getStrategyCategory('custom_unknown_skill')).toBe('framework');
  });
});
