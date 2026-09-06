# 选股解释契约

选股候选同时返回 `why_selected`、`why_now` 和 `explanation_quality`。解释由后端在候选归一化和 DSA 数据补充完成后生成，Web 只展示契约，不再根据 `change_pct`、`amount` 或 LLM 字段自行猜测。

## 字段

每条 explanation item 包含：

- `code`：稳定原因代码，例如 `selection_reason`、`top_factors`、`news`、`quote_change_pct`、`awaiting_evidence`。
- `text`：用户可见说明。
- `source`：`screening`、`realtime_quote`、新闻来源、事件来源或 `llm`。
- `quality`：`observed`、`inferred` 或 `unknown`。
- `value`：可选数值；真实 `0` 必须原样保留。

`explanation_quality.why_selected/why_now` 汇总为 `ok`、`partial` 或 `unknown`。

## Why Selected

确定性本地解释优先使用 screening reason 和当前策略实际参与评分的因子；零权重或未配置的因子既不会进入缺省 `selection_reason`，也不会被写成“核心因子”，两处展示顺序都按“因子分数 × 策略权重”的真实贡献排列。`risk_summary` / `risk_level` 始终保留在独立风险展示，不会在缺少 reason 时提升为 `selection_reason`；行业标签也不会单独冒充入选依据。缺少 reason 和可核验加权因子时只确认“已进入当前选股候选结果”，不会把可能经过 LLM 排序、组合约束或后处理调整的最终名次误写成“确定性筛选排名”。来自 `post_analysis_summaries` 的 DSA/外部 analyzer 摘要保留 `post_analyzer:<name>` 来源并标记为 inferred，不冒充本地 observed；即使候选同时已有显式 `reason` / `ranking_reason`，不同内容的后分析摘要也会作为 `post_analysis_summary` 一并返回，同文案只展示一次。纯本地确定性 `scorecard` 摘要保持 observed，但只要 scorecard 消费了 `llm_confidence`、`llm_catalysts` 或 `llm_risks`，其解释质量就保持 inferred。即使 LLM 未配置、超时或返回无效结构，候选仍至少返回入选结果说明；LLM 不是本地解释的前置条件。

## Why Now

时点解释只使用带来源的证据：DSA 新闻、事件，以及 `dsa_context.quote` 中明确存在的实时行情字段。新闻与事件都必须带可解析的 `published_date`，且发布时间在最近 30 天内；解析复用 SearchService 已支持的 ISO、RFC 2822、中文日期、Unix timestamp 和相对日期格式。缺日期或过期的新闻/事件不标记为 observed，包括复用已补充候选上下文而未重新搜索的路径。候选顶层的 `change_pct=0` 或 `amount=0` 不能单独证明数据真实存在，因为旧数据源可能用 0 表示缺失；没有 quote provenance 时返回 `awaiting_evidence`，不会写成“当前涨跌幅 0%”。

当 `dsa_context.quote.change_pct` 明确存在且为 `0` 时，它是合法平盘数据，返回 `value=0` 和 `quality=observed`。LLM catalyst 可作为 `inferred` 补充，但不能冒充观测事实。
若 quote 标记 `is_stale`/`price_stale`，或质量为 partial/unavailable/stale/missing/fetch_failed，则其中数值不进入 Why Now observed；没有其他新鲜证据时返回 `awaiting_evidence`。

## 当前阶段边界

本阶段只完成 API explanation 和 Web 展示。Issue #2282 中的策略 metadata 扩充、结果行 action、run history diff、export/backtest 等仍是后续范围。

## 回滚

移除 explanation 生成、Web 字段/卡片和对应测试即可回滚；原候选字段与 screening 排序流程保持兼容。
