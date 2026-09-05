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

权重使用当前快照 `totalMarketValue` 作为分母。
市场与币种暴露渲染全部非零分组，不截断 Top N，保证页面展示的权重不会因静默丢弃尾部分组而少于实际覆盖。

## 边界

- 本次不新增后端字段，所有数据均来自既有 snapshot 和 risk 响应。
- `/api/v1/portfolio/risk` 不可用或返回空风险块时，依赖服务端风险结果的旗标显示为“不可用”，不伪装成“正常”。
- 个股集中度只有在 `topWeightPct`、block-level `alert`、数组 `topPositions` 以及至少一条带有效 symbol/正权重的 top row 同时存在时才可用；不得在显示 `Top1: --` 时宣称“正常”或“需处理”。`UNCLASSIFIED`、非数组 `topSectors`、无效行业标签、非 number/非有限/非正的 `weightPct`、`coverage.unclassifiedCount`、`coverage.failedCount` 或行业错误表示行业分类覆盖不完整，不作为完整行业风险展示；两个 coverage counter 与 `errors` 数组都必须显式存在，缺字段也按不可用处理。全未分类、无效行或部分覆盖时，仅在个股集中度块自身完整可用时回退到个股饼图；个股集中度也缺字段时显示空态，避免把局部 `topPositions` 伪装成有效图表。行业风险 badge 与详情统一使用已校验的 block-level `sectorConcentration.alert`，不依赖可能缺失或不一致的 top-row `isAlert`。
- 市场与币种暴露仅在当前作用域可稳定推断到账户基准币到快照币种的比例、`snapshot.fxStale=false`、每个 `snapshot.accounts[].fxStale=false`，并且所有持仓都显式满足 `priceAvailable=true` 时展示；若处于“全部账户”且包含多种账户基准币、前端缺少逐账户已折算金额，或任一持仓缺价，暴露行降级为不可用。个股与行业集中度同样要求完整价格覆盖：后端会把缺价持仓用零市值占位，前端不能据此把剩余持仓误报为完整 Top1/行业风险。多基准币但 FX 和持仓价格证据完整时仍可展示；顶层或任一账户 FX stale 时均降级，避免 aggregate 未传播子账户质量时展示 fallback 1:1 产生的错误权重或告警。
- 原有持仓明细、集中度饼图、回撤、止损、AI 风险小卡继续保留。
- 价格质量只基于成功快照中的 `priceAvailable`、`priceSource` 和 `priceStale`，同一持仓只按“缺价或过期”计数一次，不额外请求行情；快照不可用时价格质量也显示“不可用”，不以空持仓误报为零问题。
- 止损计数只有在当前作用域内每个持仓都显式满足 `priceAvailable=true` 时展示；任一持仓缺价都会让止损旗标和详情降级为“不可用”，避免把占位价 `0` 误报为触发止损。历史收盘价仍属于可用但可能过期的证据，其时效性由独立价格质量旗标披露。
- 回撤至少需要两个估值观测点且历史估值未使用 stale/fallback FX；零个、单个观测点或 `fxStale=true` 都无法形成可靠比较，统一显示“不可用”。

## 后续扩展

- 按账户、行业、货币和市场增加可切换暴露视图。
- 接入 PersonalFinanceCalendar 后，在旗标中显示即将到期的分红、财报、期权或融资事件。
- 接入 ResearchArtifact 后，展示每只重仓股的 thesis 是否被风险旗标触发。
