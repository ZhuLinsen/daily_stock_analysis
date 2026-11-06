# 组合风险与暴露看板

Web 持仓页新增“风险与暴露看板”，放在组合总览指标和持仓明细之间，用于提供一眼可读的组合风险状态。

## 风险旗标

| 旗标 | 数据来源 | 触发语义 |
| --- | --- | --- |
| 个股集中 | `risk.concentration` | Top1 个股权重触发 concentration alert |
| 行业集中 | `risk.sectorConcentration` | Top1 行业权重触发 sector alert |
| 回撤 | `risk.drawdown` | 当前或最大回撤触发 drawdown alert |
| 止损 | `risk.stopLoss` | 存在接近或已触发止损标的 |
| AI 信号 | `risk.decisionSignalRisk` | 存在 sell / reduce / alert 等防御型建议 |
| 价格质量 | `snapshot.accounts[].positions[]` | 缺价或价格过期 |

## 暴露看板

| 暴露维度 | 聚合方式 |
| --- | --- |
| 市场暴露 | 先将 `position.marketValueBase` 从账户基准币折算到快照聚合币种，再按 `position.market` 聚合 |
| 币种暴露 | 先将 `position.marketValueBase` 从账户基准币折算到快照聚合币种，再按 `position.currency` 聚合 |

权重使用当前快照 `totalMarketValue` 作为分母。快照请求失败时，看板总市值、持仓数量、明细数量和账户数显示 `--`，汇率状态不可用，持仓区域提示快照不可用，不将未知数据当作空组合；成功加载的空组合仍显示零与真正空态。
市场与币种暴露渲染全部非零分组，不截断 Top N，保证页面展示的权重不会因静默丢弃尾部分组而少于实际覆盖。
合法零市值账户不会阻断其他账户的暴露展示；持仓估值缺失、非有限或为负时，整个暴露降级为不可用，避免静默丢弃异常持仓。
缺价、过期汇率、缺少换算证据等降级场景显示“暴露不可用”；成功加载且汇率证据完整的空组合显示“暂无暴露数据”。

## 边界

- 数据来自 snapshot 和 risk 响应。snapshot 追加可选字段 `accounts[].totalMarketValueAggregate`（API 原始字段 `total_market_value_aggregate`），复用现有汇率换算结果，表示该账户以顶层 `snapshot.currency` 计价的市值；原有账户与持仓本币金额保持不变，无数据库变更。
- `/api/v1/portfolio/risk` 不可用或返回空风险块时，依赖服务端风险结果的旗标显示为“不可用”，不伪装成“正常”。
- 个股集中度只有在 `topWeightPct`、block-level `alert`、数组 `topPositions` 以及完整有效的 `topPositions` 同时存在时才可用：每行必须有有效 symbol 和有限非负权重，首行权重必须为正；后台四位小数舍入后的零权重尾行仍有效（绘图时省略零面积扇区），权重不超过 100，按权重降序排列，首行权重必须与 `topWeightPct` 一致；不得过滤坏行后将另一只股票冒充 Top1；不得在显示 `Top1: --` 时宣称“正常”或“需处理”。`UNCLASSIFIED`、非数组 `topSectors`、无效行业标签、非 number/非有限/负数的 `weightPct`、`coverage.unclassifiedCount`、`coverage.failedCount` 或行业错误表示行业分类覆盖不完整，不作为完整行业风险展示；`coverage.classifiedCount` 必须为正数，`unclassifiedCount` 和 `failedCount` 必须为零，三个 coverage counter 与 `errors` 数组都必须显式存在，缺字段也按不可用处理。全未分类、无效行或部分覆盖时，仅在个股集中度块自身完整可用时回退到个股饼图；个股集中度也缺字段时显示空态，避免把局部 `topPositions` 伪装成有效图表。行业行同样必须按权重降序，首行权重与 `sectorConcentration.topWeightPct` 一致且每行权重不超过 100，允许有效分类的舍入零权重尾行；乱序或不一致时行业旗标/图表降级，并仅在个股证据完整时显示个股饼图。行业风险 badge 与详情统一使用已校验的 block-level `sectorConcentration.alert`，不依赖可能缺失或不一致的 top-row `isAlert`。
- 市场与币种暴露在多账户基准币混合时，使用各账户 `totalMarketValueAggregate` 与持仓本币市值合计的比例，逐账户折算后聚合；单一估值币种兼容旧响应，使用快照总市值与持仓市值合计推算换算比例。仅在 `snapshot.fxStale=false`、每个 `snapshot.accounts[].fxStale=false`，并且所有持仓都显式满足 `priceAvailable=true`、`priceSource` 不是 `missing`、`lastPrice` 为有限正数时展示；多基准币账户的换算字段缺失（例如旧版后端）、持仓估值币种与账户基准币不一致，或任一持仓缺价时，暴露行降级为不可用；有效 CNY/USD 混合账户正常展示各市场和币种金额及权重。个股与行业集中度同样要求完整价格覆盖：后端会把缺价持仓用零市值占位，前端不能据此把剩余持仓误报为完整 Top1/行业风险。多基准币但 FX 和持仓价格证据完整时仍可展示；顶层或任一账户 FX stale 时均降级，避免 aggregate 未传播子账户质量时展示 fallback 1:1 产生的错误权重或告警。
- 原有持仓明细、集中度饼图、回撤、止损、AI 风险小卡继续保留。
- 价格质量使用与集中度、暴露及止损一致的报价校验：`priceAvailable=true`、`priceSource` 不是 `missing`、`lastPrice` 为有限正数；不满足时计为缺价，可用但 `priceStale=true` 时计为过期价。同一持仓只按“缺价或过期”计数一次，不额外请求行情；快照不可用时价格质量也显示“不可用”，不以空持仓误报为零问题。
- 止损计数只有在当前作用域内每个持仓都显式满足 `priceAvailable=true`、`priceSource` 不是 `missing`、`lastPrice` 为有限正数时展示；任一持仓缺价都会让止损旗标和详情降级为“不可用”，避免把占位价 `0` 误报为触发止损。历史收盘价仍属于可用但可能过期的证据，其时效性由独立价格质量旗标披露。
- 回撤至少需要两个估值观测点且历史估值未使用 stale/fallback FX；零个、单个观测点或 `fxStale=true` 都无法形成可靠比较，统一显示“不可用”。

## 后续扩展

- 按账户、行业、货币和市场增加可切换暴露视图。
- 接入 PersonalFinanceCalendar 后，在旗标中显示即将到期的分红、财报、期权或融资事件。
- 接入 ResearchArtifact 后，展示每只重仓股的 thesis 是否被风险旗标触发。

## 确定性视觉验证

`cd apps/dsa-web && npx playwright install chromium && npx playwright test --config playwright.fixture.config.ts`
运行真实组合页面的 mock API 浏览器用例，覆盖完整多市场数据、缺价、快照失败、错误个股/行业 Top1、真实空组合以及合法零权重尾行。
每种状态生成 1440px 桌面与 390px 窄屏截图，校验无页面横向溢出。截图前逐个验证完整数据、无效行业回退及舍入零尾行的扇区数量与最终 SVG 弧长，避免 Recharts JavaScript 动画的中间帧进入证据；无有效集中度的状态必须没有扇区。
产物在 `apps/dsa-web/test-results/fixtures/`，CI 的 `web-gate` 同步上传 `web-ui-evidence-<head SHA>` artifact；一次性截图不入库。
