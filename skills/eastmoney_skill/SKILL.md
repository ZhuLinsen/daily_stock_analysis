---
name: eastmoney_skill
display_name: 东方财富数据 Skill
description: 使用东方财富口径补充 A 股实时行情、K线、资金流、龙虎榜、涨停池和个股新闻，适合普通用户做每日复盘与个股观察。
category: data
required_tools:
  - eastmoney_realtime_quote
  - eastmoney_daily_kline
  - eastmoney_money_flow
  - eastmoney_lhb
  - eastmoney_limit_up_pool
  - eastmoney_stock_news
  - mx_data_query
  - mx_search_query
  - mx_xuangu_query
  - mx_zixuan_query
aliases:
  - 东方财富
  - 东财
  - eastmoney
default-priority: 45
market-regimes:
  - sector_hot
---

## 使用原则

当用户要求按东方财富、东财、妙想、资金流、龙虎榜、涨停池、智能选股或 A 股短线情绪做复盘时，优先采用本 Skill。

妙想工具需要服务端配置 `MX_APIKEY` 环境变量。该密钥只允许服务端读取，不得输出到报告、前端或日志。

## 分析框架

1. 先检查实时行情是否可用；若数据源返回延迟、缓存或异常，必须在结论里明确说明数据质量。
2. K 线分析使用普通投资者容易理解的语言：价格是否站上 MA5/10/20，是否放量，是否接近支撑或压力。
3. 资金流只作为复盘参考，不把单日主力净流入解释成确定性买卖信号。
4. 龙虎榜和涨停池用于识别短线情绪和风险，不承诺次日延续。
5. 妙想智能选股只能作为复盘筛选和学习参考，不自动交易、不接券商接口。
6. 结论必须包含免责声明：仅供学习和复盘，不构成投资建议。

## 输出要求

优先输出结构化观点：摘要、AI评分、状态标签、趋势、技术、资金、板块、风险、明日观察位和操作参考。操作参考只能使用“观察 / 持有 / 减仓 / 等待确认”，不得出现自动交易、券商下单或收益承诺。
