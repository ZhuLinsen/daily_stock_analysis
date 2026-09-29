# 个股研究聚合 API

本文档说明 Issue #2279 的后端契约阶段。目标是让后续 `/stocks/:code` 工作台通过单一端点消费数据，而不是在浏览器并发拼装行情、历史、报告、资讯、持仓和监控接口。

## 端点

`GET /api/v1/stocks/{stock_code}/profile?history_days=60`

端点先把输入统一为 canonical code。实时行情、历史和报告链使用 canonical code；对可能由旧入口按别名持久化的 intelligence 与 monitor 记录，读取时会展开仓库既有等价代码集合并按 ID 去重：

- A 股：`SH600519`、`600519.SH` 等收敛为 `600519`。入口已经显式携带 `SH` / `SZ` / `BJ` 时，后续报告、资讯和监控别名展开会持续保留该市场身份；即使股票索引存在同形日韩代码，也不会重新按裸数字推断为其他市场。显式交易所与代码规则冲突（如 `600519.SZ`）时返回 400，不会剥离交易所后查询另一标的。
- 日股：`7203.T` 保留 Yahoo canonical suffix，并返回 `market=jp`。
- 韩股：`005930.KS`、`035720.KQ` 保留 Yahoo canonical suffix，并返回 `market=kr`；股票索引唯一识别出的旧裸代码也沿用解析后的韩国市场身份。缓存持仓中的旧裸六位韩股在 market 已明确为 `kr` 时按解析身份与档案 suffix 的数字主体比较，不会再次按无 market 的 A 股规则解释。
- 台股：profile 入口接受 4–6 位 `.TW` / `.TWO` Yahoo suffix（包括六位 ETF），并返回 `market=tw`。市场限定的资讯查询兼容旧裸数字 scope，但 `global` 查询继续排除该歧义别名；缓存持仓已明确 `market=tw` 时，旧裸代码按同市场数字主体与档案匹配。
- 港股：`00700`、`00700.HK`、`HK00700` 收敛为 `HK00700`；缓存持仓已明确 `market=hk` 时，`700` 等旧短格式也会补零后参与身份比较。
- 美股 ticker 统一为裸大写形式，例如 `aapl`、`AAPL.US` 都收敛为 `AAPL`；持久化读取仍查询裸 ticker 与 `.US` 等价别名。

响应包含 `quote`、`history`、`research`、`intelligence`、`portfolio`、`monitors` 六个独立块，以及顶层 `evidence_quality` 汇总。每个块的 `status` 只允许：

| 状态 | 语义 |
| --- | --- |
| `fresh` | 本次请求成功取得可用数据；不代表所有外部来源具有同一时区或刷新频率 |
| `partial` | 核心信息仍可用，但存在明确限制，例如只有报告列表、缺少详情，或持仓关系只来自缓存 |
| `unavailable` | 本次没有可用数据；原因以稳定的 `limitations` code 返回，不暴露原始异常或密钥 |

任一可选块失败不会让其他块消失。例如 quote 失败时，历史报告、结构化 ResearchArtifact、symbol intelligence 和监控规则仍可返回；最新报告详情失败时，`research.recent_reports` 仍保留，`structured_report` 为 `null` 并标记 `latest_report_detail_unavailable`。

## 数据来源与边界

- quote/history：复用 `StockService`，不新增数据获取器。
- research：复用 `HistoryService` 和 #2291 的 `ResearchArtifact` builder。报告查询把档案入口已经解析出的 market hint 传到 `HistoryService` 的候选生成层：只保留能在无提示解析时仍确认属于当前市场的裸数字别名；例如 `600519` 可继续兼容 A 股旧记录，`005930` 可兼容已唯一登记为韩股的旧报告，而与韩股同形的显式 A 股 `SZ000660` 不会查询裸 `000660`。日韩台查询保留交易所后缀及其他已确认同市场的旧裸数字代码，但不展开可能命中其他市场历史记录的别名；市场限定后候选为空时直接返回空分页，不会退化成无过滤查询。artifact 同时复用历史详情的上下文、raw result 和独立基本面快照 fallback，保留财报、分红与市场结构专项证据及其 source count。
- service 导入边界：`api.v1` 的 router 改为延迟导出，因此 `StockProfileService -> ResearchArtifact schema` 不会反向触发全部 API endpoints。CLI、独立脚本和单元测试可在没有预先导入 `api.app` 的情况下直接导入 profile service。
- intelligence：复用 `IntelligenceService` 的 symbol scope 查询，并兼容 canonical、交易所前后缀、港股前后缀、混合大小写及日韩台市场限定的裸数字历史别名；无法无提示解析回当前市场的歧义裸码不会进入 `global` 查询。查询别名按 casefold identity 去重，由 repository 的 symbol-only 不区分大小写过滤兼容历史大小写，避免重复 count/select。任一别名/市场查询失败时块保持 partial limitation，即使其余查询成功但为空，也不误报为已确认无资讯。
- portfolio：只读 `PortfolioRepository.list_cached_position_identities()`，并使用每条缓存持仓自己的 market 解析旧裸代码；只有 market 与档案身份一致时才算持有。不为了打开个股页触发实时估值或写 snapshot，所以状态固定为 `partial` 并包含 `cached_positions_only`。
- monitors：复用 `AlertService.list_rules()`，以不区分大小写的 symbol 过滤分页汇总并去重 canonical code 及等价历史别名下的 `single_symbol` 规则。由于现有告警目标没有独立 market 字段，日韩台档案不会查询可能与 A/HK 同形的裸数字别名，避免跨市场规则误归属。

本阶段不新增 Web 路由/页面、不接线 Home/Watchlist/Screening/Portfolio/Report 入口，也不包含日历事件。后续 Web PR 必须消费本端点并分别渲染块状态；不得重新恢复多请求页面聚合。日历事件在 #2307 契约合入后再作为独立块扩展。

## 回滚

Revert 本 PR 即可移除 profile schema、service、endpoint、测试和文档。没有数据库迁移、配置变更或数据清理步骤。
