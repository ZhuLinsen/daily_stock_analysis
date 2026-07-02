import { describe, expect, it } from 'vitest';
import type { MarketReviewPayload } from '../../types/analysis';
import { toCamelCase } from '../utils';

describe('toCamelCase', () => {
  it('passes through null and undefined', () => {
    expect(toCamelCase<null>(null)).toBeNull();
    expect(toCamelCase<undefined>(undefined)).toBeUndefined();
  });

  // 复盘工作台字段大小写契约（Issue #1584）：后端只输出全小写 snake_case，
  // ma5/ma10/ma20 无分隔符经 camelcase-keys 深转换后保持原样；
  // 此测试固化映射，防止后端改用 MA5/ma_5 等变体导致键名静默塌缩。
  it('maps market review workbench snake_case keys to the TypeScript contract', () => {
    const raw = {
      summary: {
        temperature_score: 45,
        temperature_label: '震荡',
        market_state: '指数强但个股弱',
        market_state_source: 'deterministic',
        suggested_position: '3-5成',
        core_conclusion: '权重护盘、成长杀跌。',
        structure_note: '上证50明显强于创业板指。',
        weight_stock_note: '权重拉动。',
      },
      indices: [{
        code: 'sh000016',
        name: '上证50',
        change_pct: 0.6,
        ma5: 2690.5,
        ma10: 2685.2,
        ma20: 2702.8,
        ma_status: { ma5: 'above', ma10: 'above', ma20: 'below' },
        technical_status: '站上MA5/MA10，MA20 之下',
        comment: '权重护盘明显',
      }],
      breadth: {
        up_count: 1800,
        divergence_diagnosis: '宽度不足。',
      },
      style_rotation: { strong: ['资源'], weak: ['半导体'], comment: '切向防御。' },
      sectors: {
        top: [{ name: '煤炭', change_pct: 3.2, leader: '中国神华', leader_change_pct: 5.6, persistence: '强' }],
      },
      catalysts: [{
        news_index: 0,
        title: '关税政策调整影响出口',
        nature: '利空',
        duration: '中期',
        digestion: '部分消化',
      }],
      next_session_plan: {
        position_advice: '维持3-5成',
        focus_sectors: ['资源'],
        avoid_sectors: ['高位半导体'],
        key_levels: ['上证3400'],
        risk_triggers: ['宽度<40%减仓'],
      },
      data_quality: { notes: ['均线状态缺失（sh000688）'] },
    };

    const payload = toCamelCase<MarketReviewPayload>(raw);

    expect(payload.summary?.temperatureScore).toBe(45);
    expect(payload.summary?.marketState).toBe('指数强但个股弱');
    expect(payload.summary?.suggestedPosition).toBe('3-5成');
    expect(payload.summary?.coreConclusion).toBe('权重护盘、成长杀跌。');
    const index = payload.indices?.[0];
    expect(index?.ma5).toBe(2690.5);
    expect(index?.ma20).toBe(2702.8);
    expect(index?.maStatus?.ma5).toBe('above');
    expect(index?.technicalStatus).toContain('MA20');
    expect(index?.comment).toBe('权重护盘明显');
    expect(payload.breadth?.divergenceDiagnosis).toBe('宽度不足。');
    expect(payload.styleRotation?.strong).toEqual(['资源']);
    const sector = payload.sectors?.top?.[0];
    expect(sector?.leader).toBe('中国神华');
    expect(sector?.leaderChangePct).toBe(5.6);
    expect(sector?.persistence).toBe('强');
    expect(payload.catalysts?.[0].newsIndex).toBe(0);
    expect(payload.catalysts?.[0].digestion).toBe('部分消化');
    expect(payload.nextSessionPlan?.positionAdvice).toBe('维持3-5成');
    expect(payload.nextSessionPlan?.riskTriggers).toEqual(['宽度<40%减仓']);
    expect(payload.dataQuality?.notes).toEqual(['均线状态缺失（sh000688）']);
  });
});
