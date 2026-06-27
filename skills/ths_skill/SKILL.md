---
name: ths_skill
display_name: 同花顺题材 Skill
description: 使用同花顺板块和概念口径补充行业、概念、成分股和题材归因，适合普通 A 股用户理解强势方向与个股所属主题。
category: sector
required_tools:
  - ths_stock_snapshot
  - ths_stock_daily_kline
  - ths_industry_boards
  - ths_concept_boards
  - ths_industry_constituents
  - ths_concept_constituents
  - ths_infer_stock_themes
aliases:
  - 同花顺
  - 题材
  - 概念
  - ths
default-priority: 46
market-regimes:
  - sector_hot
---

## 使用原则

当用户关注行业、概念、题材热度、板块成分股或“这只股票炒什么”时，优先采用本 Skill。

同花顺 Fuyao 官方 API 需要服务端配置 `FUYAO_API_KEY`（兼容读取 `THS_FUYAO_API_KEY` / `THS_API_KEY`）。密钥不得输出到报告、前端或日志。

## 分析框架

1. 区分行业与概念：行业更偏基本归属，概念更偏市场短期叙事。
2. 板块强不等于个股必然强，必须结合个股 K 线位置、资金流和风险标签。
3. 对普通用户使用人话解释：强势板块代表资金关注度高，风险板块代表短期承压或退潮。
4. 个股快照和 K 线优先用 `ths_stock_snapshot` / `ths_stock_daily_kline`，页面或报告需要快响应时不要触发慢远程兜底。
5. 如果同花顺接口异常或数据延迟，必须说明数据质量，并允许用原有板块排行或 SQLite 缓存兜底。
6. 不提供自动交易、不接券商接口、不承诺收益。

## 输出要求

输出题材归因、强弱排序、个股和板块的匹配度、风险点、明日观察清单，并固定包含免责声明：仅供学习和复盘，不构成投资建议。
