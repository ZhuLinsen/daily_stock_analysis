# 市场支持与边界

## 日本/韩国个股 suffix-only MVP（Issue #1718，Refs #1718）

当前阶段支持手动输入日本、韩国股票的 Yahoo Finance 后缀代码，进入既有个股分析、历史保存和基础报告展示链路。Web 自动补全内置一批常用日股/韩股种子索引，支持按 suffix 代码、中英文名称或常用别名搜索。

支持格式：

- 日本：`7203.T`、`6758.T`
- 韩国 KOSPI：`005930.KS`
- 韩国 KOSDAQ：`035720.KQ`

约束与边界：

- 手动输入裸代码时会先检索本地/远程股票池；若 `005930`、`000660` 等裸码命中 `005930.KS`、`000660.KS` 等日韩条目，则按命中的市场提交分析；若股票池未命中，仍按既有 6 位数字代码规则默认落到 A 股语义。
- 日股/韩股日线和基础实时/近实时行情只走 `YfinanceFetcher`，不尝试 AkShare、Tushare、Efinance、Pytdx、Baostock 等 A 股专属数据源。
- 基本面复用既有 offshore yfinance 轻量路径；A 股专属资金流、龙虎榜、板块等能力按 `not_supported` 降级。
- 报告 Prompt 已增加日股/韩股市场语义，避免套用 A 股涨跌停、北向资金、龙虎榜、融资融券等概念。
- 交易日历注册 `jp: XTKS / Asia/Tokyo` 与 `kr: XKRX / Asia/Seoul`。若本地 `exchange-calendars` 版本缺少对应日历，既有 fail-open/fail-closed 语义保持不变。

不承诺项：

- 不承诺实时行情；Yahoo Finance 数据可能延迟或字段缺失。
- 不承诺完整基本面、行业/板块、市场宽度、涨跌家数或日韩大盘复盘。
- 不承诺完整日韩全市场股票列表；Web 自动补全当前仅覆盖仓内种子索引中的常用标的，未命中时仍可手动输入 suffix 代码。
- 不补齐 Portfolio 的 JPY/KRW 汇率、成本、市值完整口径；相关字段仅放开市场类型以避免前后端校验拒绝。

回滚方式：移除 `jp/kr` 市场识别、交易日历注册、YFinance 路由扩展、Web/API 类型放行、`scripts/stock_index_seeds/` 日韩种子索引，并删除本文档中的能力声明。
