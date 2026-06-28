# 市场支持与边界

## 日本/韩国个股 suffix-only MVP（Issue #1718，Refs #1718）

当前阶段支持手动输入日本、韩国股票的 Yahoo Finance 后缀代码，进入既有个股分析、历史保存和基础报告展示链路。Web 自动补全内置一批常用日股/韩股种子索引，支持按 suffix 代码、中英文名称或常用别名搜索。

支持格式：

- 日本：`7203.T`、`6758.T`
- 韩国 KOSPI：`005930.KS`
- 韩国 KOSDAQ：`035720.KQ`

约束与边界：

- 手动输入裸代码时会先检索本地/远程股票池；若 `005930`、`000660` 等裸码命中 `005930.KS`、`000660.KS` 等日韩条目，则按命中的市场提交分析；若股票池未命中，仍按既有 6 位数字代码规则默认落到 A 股语义，并保留为可追踪的跨市场歧义边界。
- 日股/韩股 suffix 识别已集中到共享市场代码工具，数据源路由、Prompt 市场识别、交易日历和股票索引裸码解析复用同一组规则，减少后续市场扩展时的规则漂移。
- 日股/韩股日线和基础实时/近实时行情只走 `YfinanceFetcher`，不尝试 AkShare、Tushare、Efinance、Pytdx、Baostock 等 A 股专属数据源；yfinance 报价会尽量带上 `market`、`currency`、`data_quality`、`missing_fields` 等质量元数据。
- 基本面复用既有 offshore yfinance 轻量路径；A 股专属资金流、龙虎榜、板块等能力按 `not_supported` 降级，offshore 基本面上下文也会标记 provider、as_of、data_quality 和缺失块。
- 报告 Prompt 已增加日股/韩股市场语义，避免套用 A 股涨跌停、北向资金、龙虎榜、融资融券等概念。
- 交易日历注册 `jp: XTKS / Asia/Tokyo` 与 `kr: XKRX / Asia/Seoul`。若本地 `exchange-calendars` 版本缺少对应日历，既有 fail-open/fail-closed 语义保持不变。

兼容性与回退说明（针对结构化检测命中项）：

- `#1815` 本次仅新增 `yfinance` 报价/基本面上下文中的可选字段元数据（如 `market`、`currency`、`data_quality`、`missing_fields`、`provider`），未改动 LLM provider/model/base URL、配置 Schema、运行时环境变量、数据库字段、存量缓存序列化或消息协议版本。
- 外部 API 边界仍仅限既有 `yfinance` fetch 路径（含 `Ticker`/`history`/`fast_info`）与既有兜底逻辑；没有新增或迁移 API 网关/host，`YFINANCE_PRIORITY` 是唯一受影响的可见参数。
- 兼容性验证依据：行情/基本面上下文在 `data_provider/base.py` 与 `realtime_types.py` 中按现有 `getattr`/可选字段约定向下游透传，不强制读写新增字段；无配置迁移脚本，未观察到 provider/model/base URL fallback 路径变更。
- 回退方式：若新增元数据字段在某端产生兼容问题，可先忽略这些字段并按既有市场判定+行情展示链路运行；必要时回滚本次提交或通过移除 `jp/kr` `MarketSymbol` 及路由扩展恢复旧行为。

不承诺项：

- 不承诺实时行情；Yahoo Finance 数据可能延迟或字段缺失。
- 不承诺完整基本面、行业/板块、市场宽度、涨跌家数或日韩大盘复盘。
- 不承诺完整日韩全市场股票列表；Web 自动补全当前仅覆盖仓内种子索引中的常用标的（已扩充至各 30 只左右的头部标的），未命中时仍可手动输入 suffix 代码。
- 不补齐 Portfolio 的 JPY/KRW 汇率、成本、市值完整口径；相关字段仅放开市场类型以避免前后端校验拒绝。

回滚方式：移除 `jp/kr` 市场识别、交易日历注册、YFinance 路由扩展、Web/API 类型放行、`scripts/stock_index_seeds/` 日韩种子索引，并删除本文档中的能力声明。

## 台湾个股 suffix-only MVP（Issue #1772，Refs #1772）

当前阶段支持手动输入台湾股票的 Yahoo Finance 后缀代码，进入既有个股分析、历史保存和基础报告展示链路。TWSE 上市股票使用 `.TW` 后缀，TPEx 上柜（柜买）股票使用 `.TWO` 后缀，二者折叠为同一 `tw` 市场标签。**本次覆盖市场识别（detection）、数据路由层、DecisionSignal/Portfolio/Intelligence 服务层与 API 市场枚举，以及 DecisionSignal/Portfolio 前端市场类型与筛选**；台股股票索引/种子、Web 自动补全与告警（大盘红绿灯）市场放行仍作为后续 PR。对齐 #1718 日韩 MVP 模式。

支持格式：

- 上市（TWSE）：`2330.TW`、`0050.TW`
- 上柜（TPEx / 柜买）：`6488.TWO`、`5483.TWO`
- 代码 base 为 4-6 位数字（普通股 4 位，ETF/其他至 6 位，如 `00878.TW`、`006208.TW`），较日股 `.T` 的 4-5 位更宽。

约束与边界：

- **严格 suffix-only**：裸 `2330`、`00878` 等不带后缀的代码不会进入台股语义（`detect_market` / `get_market_for_stock` 仅在显式 `.TW`/`.TWO` 后缀时返回 `tw`）。本次**不引入任何台股股票索引/种子解析**，故裸码不可能经本地/远程股票池被改写为台股 suffix；该索引解析（与 jp/kr 同款的裸码命中行为）属后续 PR。
- 台股日线和基础实时/近实时行情只走 `YfinanceFetcher`，不尝试 AkShare、Tushare、Efinance、Pytdx、Baostock 等 A 股专属数据源。
- 基本面复用既有 offshore yfinance 轻量路径；A 股专属资金流、龙虎榜、板块等能力按 `not_supported` 降级。
- 报告 Prompt 已增加台股市场语义（新台币、三大法人、TWSE/TPEx ±10% 涨跌停），避免套用 A 股北向资金、龙虎榜等概念。
- 交易日历注册 `tw: XTAI / Asia/Taipei`。TWSE 为 09:00–13:30 连续交易、无午休；收盘集合竞价暂不建模，与 jp/kr 一致。若本地 `exchange-calendars` 版本缺少对应日历，既有 fail-open/fail-closed 语义保持不变。
- 主要指数提供加权指数 `^TWII` 与柜买指数 `^TWOII`。

不承诺项：

- 不承诺实时行情；Yahoo Finance 数据可能延迟或字段缺失。
- 不承诺完整基本面、行业/板块、市场宽度、涨跌家数或台股大盘复盘。
- 台股股票索引/种子、Web 自动补全与告警（大盘红绿灯）市场放行仍作为后续 PR；告警 MarketRegion 与后端 market_light 仍为 cn/hk/us，未含 tw。
- 不补齐 Portfolio 的 TWD 汇率、成本、市值完整口径（属上述后续 PR 范围）。

回滚方式：移除 `tw` 市场识别、交易日历注册、YFinance 路由扩展与服务层/API 市场枚举及前端市场类型放行，并删除本文档中的能力声明。
