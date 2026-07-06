import { describe, expect, it } from 'vitest';
import {
  matchSectionsToModules,
  orderMarketEntries,
  stripInjectedTables,
  stripSectionNumbering,
} from '../marketReviewModuleMatching';

describe('matchSectionsToModules', () => {
  it('maps zh sections regardless of numeral drift', () => {
    const { modules, narrative } = matchSectionsToModules([
      { key: 'overview', title: 'Overview', markdown: '引言。' },
      { key: 's1', title: '一、盘面总览', markdown: '总览。' },
      { key: 's2', title: '二、指数结构', markdown: '指数。' },
      { key: 's3', title: '四、板块主线', markdown: '板块。' }, // 编号漂移
      { key: 's4', title: '三、资金与情绪', markdown: '资金。' },
      { key: 's5', title: '五、消息催化', markdown: '催化。' },
      { key: 's6', title: '六、明日交易计划', markdown: '计划。' },
      { key: 's7', title: '七、风险提示', markdown: '风险。' },
      { key: 's8', title: '后市展望', markdown: '展望。' },
    ]);

    expect(modules.conclusion).toBe('引言。\n\n总览。');
    expect(modules.indices).toBe('指数。');
    expect(modules.sectors).toBe('板块。');
    expect(modules.breadth).toBe('资金。');
    expect(modules.catalysts).toBe('催化。');
    expect(modules.plan).toBe('计划。');
    expect(narrative.map((s) => s.title)).toEqual(['七、风险提示', '后市展望']);
  });

  it('maps en sections and drops empty ones', () => {
    const { modules, narrative } = matchSectionsToModules([
      { key: 's1', title: '1. Market Summary', markdown: 'summary.' },
      { key: 's2', title: 'Index Commentary', markdown: 'indices.' },
      { key: 's3', title: '3. Fund Flows', markdown: 'flows.' },
      { key: 's4', title: 'Sector/Theme Highlights', markdown: 'sectors.' },
      { key: 's5', title: '5. News Catalysts', markdown: 'news.' },
      { key: 's6', title: '7. Strategy Plan', markdown: 'plan.' },
      { key: 's7', title: 'Outlook', markdown: 'outlook.' },
      { key: 's8', title: 'Empty', markdown: '   ' },
    ]);

    expect(modules.conclusion).toBe('summary.');
    expect(modules.indices).toBe('indices.');
    expect(modules.breadth).toBe('flows.');
    expect(modules.sectors).toBe('sectors.');
    expect(modules.catalysts).toBe('news.');
    expect(modules.plan).toBe('plan.');
    expect(narrative.map((s) => s.title)).toEqual(['Outlook']);
  });

  it('degrades korean titles to narrative', () => {
    const { modules, narrative } = matchSectionsToModules([
      { key: 's1', title: '1. 시장 요약', markdown: '요약.' },
    ]);
    expect(Object.keys(modules)).toHaveLength(0);
    expect(narrative).toHaveLength(1);
  });
});

describe('stripInjectedTables', () => {
  it('removes table rows and orphaned #### data headings, keeps prose', () => {
    const input = [
      '叙事第一段。',
      '',
      '#### 行业板块领涨 Top 5',
      '| 排名 | 行业板块 | 涨跌幅 |',
      '|------|------|--------|',
      '| 1 | 煤炭 | +3.20% |',
      '',
      '叙事第二段。',
      '',
      '#### 小节标题（正文）',
      '正文内容。',
    ].join('\n');

    const output = stripInjectedTables(input);
    expect(output).toContain('叙事第一段。');
    expect(output).toContain('叙事第二段。');
    expect(output).not.toContain('|');
    expect(output).not.toContain('行业板块领涨');
    // 后随正文的 #### 标题保留
    expect(output).toContain('#### 小节标题（正文）');
    expect(output).toContain('正文内容。');
  });

  it('collapses excessive blank lines and handles empty input', () => {
    expect(stripInjectedTables('')).toBe('');
    expect(stripInjectedTables('a\n\n\n\n\nb')).toBe('a\n\nb');
  });
});

describe('orderMarketEntries', () => {
  it('orders known regions by backend order and appends unknown regions', () => {
    const entries = orderMarketEntries({ us: 1, xx: 3, cn: 2 });
    expect(entries.map(([region]) => region)).toEqual(['cn', 'us', 'xx']);
  });
});

describe('stripSectionNumbering', () => {
  it('strips emoji/decoration prefixes before numbering (real DeepSeek headings)', () => {
    expect(stripSectionNumbering('📰 五、消息催化')).toBe('消息催化');
    expect(stripSectionNumbering('⚠️ 七、风险提示')).toBe('风险提示');
    expect(stripSectionNumbering('🎯 六、明日交易计划')).toBe('明日交易计划');
    expect(stripSectionNumbering('七、风险提示')).toBe('风险提示');
    expect(stripSectionNumbering('7. Risk Notes')).toBe('Risk Notes');
  });
});
