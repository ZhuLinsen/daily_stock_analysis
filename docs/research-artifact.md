# ResearchArtifact 结构化研究产物

`ResearchArtifact` 是报告的结构化版本，用于后续 Dashboard、个股研究页、监控中心、自选股和 Copilot 复用同一份研究结论。

## 目标

首版解决三个问题：

- 把报告结论沉淀为 `thesis`，而不是只依赖 Markdown。
- 每份结构化报告必须带 `invalidation_conditions`，明确什么时候需要推翻或重新评估。
- 证据项统一带 `freshness` 与 `quality_level`，让页面能展示数据新鲜度和可信度。

## 字段

顶层结构：

- `schema_version`：固定为 `research-artifact-v1`。
- `artifact_id`：稳定产物 id，优先使用 `report:<source_report_id>`；尚未持久化时使用 `report:<stock_code>:<query_id>`，避免批量分析中多个股票共享 query id 造成碰撞；无 query id 时回退为 `report:<stock_code>`。
- `source_report_id`：历史报告主键。
- `source_query_id`：分析任务 query id。
- `created_at`：报告创建时间。
- `subject`：标的。
- `thesis`：结构化观点。
- `evidence`：证据列表。
- `invalidation_conditions`：失效条件，至少一条。
- `next_actions`：下一步动作。
- `data_quality`：输入质量摘要。
- `metadata`：低敏扩展字段。

## Thesis

`thesis` 包含：

- `direction`：`bullish` / `bearish` / `neutral` / `unknown`。
- `summary`：核心观点。
- `confidence`：由情绪分换算的置信度。
- `score`：原始情绪分。
- `action` / `action_label`：结构化建议动作。
- `reasons`：支持理由。
- `risks`：主要风险。

## Evidence

`evidence` 包含：

- `source_type`：例如 `analysis_context`、`news`、`fundamental`、`market_structure`。
- `freshness`：`fresh` / `stale` / `unknown`。
- `quality_level`：`good` / `usable` / `limited` / `poor` / `unknown`。
- `source`、`as_of`、`url`、`metadata` 等低敏扩展字段。

时间与新鲜度边界：

- `as_of` 仅来自显式 `provider_timestamp`，保留上游时区；不会用报告创建时间或抓取时间代替行情观测时间。
- `metadata.context_timestamp` 保留 context block 的原始时间语义，`metadata.fetched_at` 单独记录抓取时间。两者都不证明数据是最新的。
- 上游明确 `stale` 时保留 `stale`；仅有 `available`、`fallback`、`partial`、`estimated` 或 `ok` 时，freshness 为 `unknown`，质量状态仍按原逻辑计算。没有统一 TTL，也不把股票交易日规则套用于 24/7 市场。
- 旧报告没有时间字段时继续兼容。当前适配器不根据读取时的时钟重新判断历史证据，也不冻结完整证据快照。

首版适配器会从 `analysis_context_pack_overview.blocks`、新闻摘要、财报、分红和市场结构中提取证据。

## Invalidation

每份 `ResearchArtifact` 必须包含至少一条 `invalidation_conditions`。

首版默认来源：

- `strategy.stop_loss` 生成价格失效条件。
- `strategy.take_profit` 生成止盈复核条件。
- 数据质量限制生成 `data_quality` 失效条件。
- 新闻缺失披露生成 `evidence` 失效条件。
- 如果没有显式条件，生成 `manual:thesis_reassessment` 兜底复核条件。

## Numeric grounding and position sizing

`metadata.levels` is generated from the report strategy by parsing numeric sniper
levels and checking the entry/secondary-entry, stop-loss and take-profit geometry.
For offensive actions (`buy` / `add`), a stop-loss at or above either entry, a
secondary entry above the ideal entry, or a take-profit at or below the ideal
entry produces `validation=direction_conflict` and `status=invalid`. An entry
that differs from the analysis-time reference price by more than 25% produces
`validation=out_of_range`; non-offensive actions remain `conditional_watch`.

`metadata.position` is a stop-distance risk-budget estimate, not an execution
instruction and not a broker order size. It uses a default 1.2% account-risk
budget, caps poor/limited data conservatively, and returns zero when the action
is non-offensive, data quality is poor, or level validation fails. The returned
`max_pct` is rounded down so the displayed percentage cannot exceed the budget
implied by the validated stop distance. The current method name is retained for
API compatibility; the calculation is based on validated stop distance and does
not claim to be a historical ATR value.

`metadata.risk_flags` mirrors grounding and data-quality failures for the Web
report. When the persisted raw result contains committee disagreement or risk
override details, they are exposed under `metadata.committee`. History detail
and Stock Profile build the artifact from the same current-price and raw-result
inputs so the same report does not change its grounding result by entry point.

## 兼容边界

`AnalysisReport` 新增可选字段：

```text
structured_report?: ResearchArtifact | null
```

旧报告可以继续不返回该字段；Web 类型和后端 schema 都按可选字段处理。

当前 Stock Profile API 会从历史详情动态构建该产物；报告生成时冻结并持久化完整 `structured_report` 仍是后续范围。

## 实现入口

后端：

- Schema：`api/v1/schemas/research_artifact.py`
- Helper：`src/services/research_artifact_service.py`
- 测试：`tests/test_research_artifact_service.py`

Web：

- 类型：`apps/dsa-web/src/types/researchArtifact.ts`
- `AnalysisReport.structuredReport`：可选消费入口

## 后续接入

1. 报告生成链路在持久化时写入 `structured_report`。
2. 个股研究页直接读取 `thesis`、`evidence` 和 `invalidation_conditions`。
3. 监控中心把失效条件转成可编辑规则。
4. Dashboard 的 What Changed 可以比较两份 `ResearchArtifact` 的 thesis 与 evidence 差异。
