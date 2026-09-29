import { describe, expect, it } from 'vitest';
import {
  type DecisionActionLabelMap,
  getDecisionActionLabel,
  getLegacyDecisionAction,
  getDecisionActionTone,
  getLegacyDecisionActionLabel,
} from '../decisionAction';

const englishLabels: DecisionActionLabelMap = {
  buy: 'Buy',
  add: 'Add',
  hold: 'Hold',
  reduce: 'Reduce',
  sell: 'Sell',
  watch: 'Watch',
  avoid: 'Avoid',
  alert: 'Alert',
};

describe('decisionAction helpers', () => {
  it('uses structured action taxonomy before server label and legacy advice text', () => {
    expect(getDecisionActionLabel('avoid', '回避', '买入', '建议')).toBe('回避');
    expect(getDecisionActionLabel('sell', '买入', null, 'Advice', englishLabels)).toBe('Sell');
    expect(getDecisionActionTone('sell', '买入', null)).toBe('danger');
    expect(getDecisionActionLabel(null, '买入', null, 'Advice', englishLabels)).toBe('买入');
  });

  it('falls back to the action taxonomy label when actionLabel is absent', () => {
    expect(getDecisionActionLabel('add', null, '持有', '建议')).toBe('加仓');
    expect(getDecisionActionLabel('watch', null, '持有', 'Advice', englishLabels)).toBe('Watch');
  });

  it('keeps legacy fallback compatible with negated buy advice', () => {
    expect(getLegacyDecisionActionLabel('不建议买入，等待确认')).toBe('回避');
    expect(getDecisionActionLabel(null, null, '避免买入', '建议')).toBe('回避');
    expect(getLegacyDecisionActionLabel('暂不买入，等待确认')).toBe('回避');
    expect(getLegacyDecisionActionLabel('先不建仓，等待放量')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无需买入，等待确认')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无须建仓，继续观察')).toBe('回避');
    expect(getLegacyDecisionActionLabel('无需布局，等待突破')).toBe('回避');
    expect(getLegacyDecisionActionLabel('no buy until breakout')).toBe('回避');
    expect(getLegacyDecisionActionLabel('no need to buy before confirmation')).toBe('回避');
    expect(getLegacyDecisionActionLabel('cannot buy before confirmation')).toBe('回避');
    expect(getLegacyDecisionActionLabel("can't buy before confirmation")).toBe('回避');
    expect(getLegacyDecisionActionLabel('not a buy yet')).toBe('回避');
    expect(getLegacyDecisionActionLabel('not a buy yet', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('not to buy', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('avoid buying', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('avoid buying into weakness', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('waiting to buy')).toBeNull();
  });

  it('keeps legacy fallback compatible with negated sell and add advice', () => {
    expect(getLegacyDecisionActionLabel('不建议卖出，继续观察')).toBe('持有');
    expect(getLegacyDecisionActionLabel('洗盘观察')).toBe('持有');
    expect(getLegacyDecisionActionLabel('洗盘观察', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('无需减仓，维持仓位')).toBe('持有');
    expect(getLegacyDecisionActionLabel('无须减仓，维持仓位')).toBe('持有');
    expect(getLegacyDecisionActionLabel('不建议加仓，等待回踩')).toBe('持有');
    expect(getLegacyDecisionActionLabel('无须加仓，等待回踩')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no add before confirmation')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot add before confirmation')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no need to accumulate here')).toBe('持有');
    expect(getLegacyDecisionActionLabel("can't accumulate here")).toBe('持有');
    expect(getLegacyDecisionActionLabel('no sell before earnings')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot sell before earnings')).toBe('持有');
    expect(getLegacyDecisionActionLabel('no need to reduce exposure')).toBe('持有');
    expect(getLegacyDecisionActionLabel("can't reduce exposure")).toBe('持有');
    expect(getLegacyDecisionActionLabel('no trim while trend holds')).toBe('持有');
    expect(getLegacyDecisionActionLabel('cannot trim while trend holds')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a sell yet')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a trim yet')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not to sell')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not to trim')).toBe('持有');
    expect(getLegacyDecisionActionLabel('not a trim yet', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid selling into weakness', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid trimming before earnings', englishLabels)).toBe('Hold');
    expect(getLegacyDecisionActionLabel('avoid reducing exposure before earnings', englishLabels)).toBe('Hold');
    expect(getDecisionActionTone(null, null, '不建议卖出，继续观察')).toBe('success');
  });

  it('does not turn ambiguous English advice into a badge action', () => {
    expect(getLegacyDecisionActionLabel('buy or sell')).toBeNull();
    expect(getDecisionActionLabel(null, null, 'buy or sell', 'Advice', englishLabels)).toBe('Advice');
  });

  it('does not match financial compound words as legacy actions', () => {
    expect(getLegacyDecisionActionLabel('no buyback announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('cannot buyback shares now', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('share buy-back announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('share buy back announced', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('no selloff risk', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('not selloff yet', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('sell-off risk remains low', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('sell off risk remains low', englishLabels)).toBeNull();
    expect(getLegacyDecisionActionLabel('no sell-off pressure', englishLabels)).toBeNull();
    expect(getDecisionActionLabel(null, null, 'no buyback announced', 'Advice', englishLabels)).toBe('Advice');
    expect(getDecisionActionLabel(null, null, 'no selloff risk', 'Advice', englishLabels)).toBe('Advice');
    expect(getLegacyDecisionActionLabel('no buy until breakout', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('cannot buy before confirmation', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('no sell before earnings', englishLabels)).toBe('Hold');
  });

  it('keeps separate action terms next to financial compounds', () => {
    expect(getLegacyDecisionAction('buy after sell-off')).toBe('buy');
    expect(getLegacyDecisionActionLabel('buy after sell-off', englishLabels)).toBe('Buy');
    expect(getLegacyDecisionAction('sell after buy-back rumor')).toBe('sell');
    expect(getLegacyDecisionActionLabel('sell after buy-back rumor', englishLabels)).toBe('Sell');
  });

  it('does not match Chinese financial context words as legacy actions', () => {
    expect(getLegacyDecisionActionLabel('买盘增强，继续观察')).toBeNull();
    expect(getLegacyDecisionActionLabel('卖压缓解，继续观察')).toBeNull();
    expect(getLegacyDecisionActionLabel('卖方评级分歧')).toBeNull();
    expect(getDecisionActionLabel(null, null, '买盘增强，继续观察', '建议')).toBe('建议');
    expect(getDecisionActionLabel(null, null, '卖压缓解，继续观察', '建议')).toBe('建议');
  });

  it('keeps multi-guard legacy advice empty instead of prioritizing avoid or alert', () => {
    expect(getLegacyDecisionActionLabel('risk alert, avoid buying')).toBeNull();
    expect(getLegacyDecisionActionLabel('风险预警，避免买入')).toBeNull();
    expect(getDecisionActionLabel(null, null, 'risk alert, avoid buying', 'Advice', englishLabels)).toBe('Advice');
    expect(getLegacyDecisionActionLabel('avoid buying', englishLabels)).toBe('Avoid');
    expect(getLegacyDecisionActionLabel('risk alert', englishLabels)).toBe('Alert');
  });

  it('maps action tone without reading legacy text when action is present', () => {
    expect(getDecisionActionTone('buy', null, '卖出')).toBe('success');
    expect(getDecisionActionTone('reduce', null, '买入')).toBe('danger');
    expect(getDecisionActionTone('alert', null, '买入')).toBe('warning');
    expect(getDecisionActionTone(null, '观望', '买入')).toBe('warning');
    expect(getDecisionActionTone(null, 'Sell', '买入')).toBe('danger');
    expect(getDecisionActionTone(null, null, 'avoid buying')).toBe('warning');
  });
});
