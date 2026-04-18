import { describe, expect, it } from 'vitest';
import { markdownToPlainText } from '../markdown';

/**
 * Stock report specific tests for markdownToPlainText
 * Tests real-world stock analysis report scenarios
 */
describe('markdownToPlainText - Stock Report Scenarios', () => {
  it('handles typical Chinese stock report with tables and indicators', () => {
    const stockReport = `# 贵州茅台 (600519) 分析报告

## 技术分析

| 指标 | 当前值 | 信号 |
|------|--------|------|
| MA5 | 1680.50 | 🟢 |
| MA10 | 1675.30 | 🟢 |
| MA20 | 1665.80 | 🟢 |

**MACD**: 金叉信号，买入参考
**RSI**: 56.8，处于中性区域

## 基本面分析

- **市盈率**: 28.5
- **市净率**: 8.2
- **营收增长**: +15.3% YoY

> 风险提示：短期波动加大，建议控制仓位

## 操作建议

\`\`\`python
# 推荐买入区间
entry_zone = [1650, 1680]
stop_loss = 1620
target = 1750
\`\`\`

[查看详细数据](https://example.com/stock/600519)`;

    const result = markdownToPlainText(stockReport);

    // Verify key content is preserved
    expect(result).toContain('贵州茅台');
    expect(result).toContain('600519');
    expect(result).toContain('技术分析');
    expect(result).toContain('MACD');
    expect(result).toContain('金叉信号');
    expect(result).toContain('市盈率');
    expect(result).toContain('风险提示');
    expect(result).toContain('entry_zone');
    expect(result).toContain('查看详细数据');

    // Verify markdown symbols are removed
    expect(result).not.toMatch(/^#{1,6}\s+/m);
    expect(result).not.toMatch(/\*\*[^*]+\*\*/);
    // Note: remove-markdown preserves table structure with pipe characters
    // This is a known limitation - tables remain pipe-separated
  });

  it('handles Hong Kong stock report with English and Chinese mix', () => {
    const hkReport = `# Tencent (00700.HK) Technical Analysis

## Key Indicators

* **Current Price**: HKD 368.20
* **Change**: +2.5% 📈
* **Volume**: 18.2M

## Support & Resistance

1. **Resistance 1**: HKD 375.00
2. **Resistance 2**: HKD 380.00
3. **Support 1**: HKD 365.00

> 建议在回调至 365-368 区间关注

\`\`\`
MA5 > MA10 > MA20 (多头排列)
RSI(14) = 58.3 (中性偏强)
\`\`\`

[Click for more details](https://finance.qq.com/q/go.php/vInvestConsult/stock/00700)`;

    const result = markdownToPlainText(hkReport);

    expect(result).toContain('Tencent');
    expect(result).toContain('00700.HK');
    expect(result).toContain('368.20');
    expect(result).toContain('Resistance 1');
    expect(result).toContain('Support 1');
    expect(result).toContain('建议在回调');
    expect(result).toContain('MA5 > MA10');
    expect(result).toContain('Click for more details');
  });

  it('handles US stock report with financial data', () => {
    const usReport = `# Apple Inc. (AAPL) Analysis Report

## Financial Metrics

| Metric | Value | Change |
|--------|-------|--------|
| Price | $178.35 | +1.2% |
| Market Cap | $2.8T | - |
| P/E Ratio | 28.5 | - |
| EPS | $6.16 | +8.3% |

## Technical Indicators

- **MA50**: $175.20 (Above)
- **MA200**: $168.80 (Above)
- **RSI**: 62.5 (Slightly Overbought)
- **MACD**: Bullish crossover

## Recommendation

***Strong Buy*** with target price of **$195.00**

> Risk: Trade tensions may impact supply chain

\`\`\`javascript
const entryPrice = 178.35;
const stopLoss = 172.00;
const targetPrice = 195.00;
const riskReward = (targetPrice - entryPrice) / (entryPrice - stopLoss);
// Risk/Reward ratio: 2.1:1
\`\`\`

![AAPL Chart](https://example.com/charts/aapl.png)`;

    const result = markdownToPlainText(usReport);

    expect(result).toContain('Apple Inc.');
    expect(result).toContain('AAPL');
    expect(result).toContain('178.35');
    expect(result).toContain('2.8T');
    expect(result).toContain('Strong Buy');
    expect(result).toContain('195.00');
    expect(result).toContain('Risk/Reward ratio');
  });

  it('handles market review report with multiple stocks', () => {
    const marketReview = `# A股市场复盘

## 指数表现

| 指数 | 收盘 | 涨跌幅 | 成交额 |
|------|------|--------|--------|
| 上证指数 | 3050.32 | +0.85% | 4285亿 |
| 深证成指 | 9850.45 | +1.12% | 5250亿 |
| 创业板指 | 1950.28 | +1.45% | 2180亿 |

## 热点板块

1. **人工智能** 🤖
   - 原因：大模型技术突破
   - 龙头：科大讯飞、寒武纪

2. **新能源汽车** 🚗
   - 原因：销量数据超预期
   - 龙头：比亚迪、理想汽车

3. **半导体** 💾
   - 原因：国产替代加速
   - 龙头：中芯国际、北方华创

## 资金流向

- **北向资金**: +85.5亿
- **融资融券**: +32.8亿
- **主力资金**: 净流入 156.8亿

## 后市展望

> 预期明日震荡区间：3040-3065

**策略**：关注科技主线，控制仓位`;

    const result = markdownToPlainText(marketReview);

    expect(result).toContain('A股市场复盘');
    expect(result).toContain('上证指数');
    expect(result).toContain('3050.32');
    expect(result).toContain('人工智能');
    expect(result).toContain('科大讯飞');
    expect(result).toContain('北向资金');
    expect(result).toContain('85.5亿');
    expect(result).toContain('3040-3065');
  });

  it('handles report with special characters and formulas', () => {
    const report = `# 技术指标计算

## MACD 计算

\`\`\`python
# MACD = EMA(12) - EMA(26)
# Signal = EMA(MACD, 9)
# Histogram = MACD - Signal

def calculate_macd(prices, fast=12, slow=26, signal=9):
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal).mean()
    return macd, signal_line
\`\`\`

## RSI 公式

$$RSI = 100 - \frac{100}{1 + RS}$$

其中：
- RS = 平均涨幅 / 平均跌幅
- 周期：默认 14 天

## 布林带

- **中轨** = MA(20)
- **上轨** = MA(20) + 2 × STD(20)
- **下轨** = MA(20) - 2 × STD(20)

> 当前股价在上轨附近，注意回调风险`;

    const result = markdownToPlainText(report);

    expect(result).toContain('MACD 计算');
    expect(result).toContain('EMA(12) - EMA(26)');
    expect(result).toContain('RSI');
    expect(result).toContain('布林带');
    expect(result).toContain('MA(20)');
    expect(result).toContain('注意回调风险');
  });

  it('handles report with code snippets in multiple languages', () => {
    const report = `# 策略回测代码

## Python 策略

\`\`\`python
import pandas as pd
import numpy as np

def moving_average_strategy(data, short=5, long=20):
    signals = pd.DataFrame(index=data.index)
    signals['signal'] = 0

    signals['short_ma'] = data['close'].rolling(window=short).mean()
    signals['long_ma'] = data['close'].rolling(window=long).mean()

    signals.loc[signals['short_ma'] > signals['long_ma'], 'signal'] = 1
    signals.loc[signals['short_ma'] < signals['long_ma'], 'signal'] = -1

    return signals
\`\`\`

以上代码可直接用于策略回测。`;

    const result = markdownToPlainText(report);

    // Verify key content is preserved
    expect(result).toContain('策略回测代码');
    expect(result).toContain('Python 策略');
    expect(result).toContain('以上代码可直接用于策略回测');

    // Verify code content is preserved
    expect(result).toContain('import pandas');
    expect(result).toContain('moving_average_strategy');
  });

  it('handles edge case: very long stock code list', () => {
    const stockList = `# 股票池列表

## 沪深300成分股（部分）

| 代码 | 名称 | 现价 | 涨跌幅 |
|------|------|------|--------|
| 600519 | 贵州茅台 | 1680.50 | +0.85% |
| 000858 | 五粮液 | 125.30 | +1.20% |
| 600036 | 招商银行 | 32.50 | -0.25% |
| 000001 | 平安银行 | 11.85 | +0.42% |
| 601318 | 中国平安 | 45.20 | +0.15% |
| 000333 | 美的集团 | 58.80 | +1.80% |
| 600276 | 恒瑞医药 | 42.50 | +2.10% |
| 300750 | 宁德时代 | 185.30 | +3.20% |
| 688981 | 中芯国际 | 52.80 | +4.50% |
| 601012 | 隆基绿能 | 25.60 | -1.20% |

## 筛选条件

- **市值**: > 500亿
- **PE**: 10-50
- **ROE**: > 15%
- **负债率**: < 60%`;

    const result = markdownToPlainText(stockList);

    // Verify all stock codes are preserved
    expect(result).toContain('600519');
    expect(result).toContain('000858');
    expect(result).toContain('601012');
    expect(result).toContain('贵州茅台');
    expect(result).toContain('宁德时代');
    expect(result).toContain('筛选条件');
    expect(result).toContain('ROE');
  });

  it('handles mixed Chinese and English punctuation correctly', () => {
    const text = `# 报告摘要

**主要观点**：
1. 短期看涨，目标价 $195.00
2. 支撑位：$168.50-172.00
3. 压力位：$180.50-185.00

"Risk: Trade war impact"

> 风险提示：中美贸易摩擦可能影响出口

*关注点*：AI chip business growth`;

    const result = markdownToPlainText(text);

    expect(result).toContain('主要观点');
    expect(result).toContain('短期看涨');
    expect(result).toContain('195.00');
    expect(result).toContain('Risk: Trade war impact');
    expect(result).toContain('风险提示');
    expect(result).toContain('关注点');
    expect(result).toContain('AI chip business');
  });

  it('preserves numerical data and percentages accurately', () => {
    const report = `# 数据报告

## 关键指标

- 营收: 1,234.56亿
- 净利润: +23.45%
- 市占率: 15.67%
- ROE: 18.9%
- 负债率: 45.2%

## 价格区间

| 日期 | 开盘 | 最高 | 最低 | 收盘 |
|------|------|------|------|------|
| 2024-01-15 | 1680.50 | 1695.30 | 1675.20 | 1688.80 |
| 2024-01-16 | 1688.80 | 1702.50 | 1685.30 | 1698.20 |

涨跌幅: +1.23% (今日)`;

    const result = markdownToPlainText(report);

    expect(result).toContain('1,234.56');
    expect(result).toContain('23.45%');
    expect(result).toContain('15.67%');
    expect(result).toContain('1680.50');
    expect(result).toContain('1695.30');
    expect(result).toContain('1.23%');
  });
});
