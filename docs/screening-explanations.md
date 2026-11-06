# 选股解释契约

选股候选同时返回 `why_selected`、`why_now` 和 `explanation_quality`。解释由后端在候选归一化和 DSA 数据补充完成后生成，Web 逐条展示 text、source 和 quality；分组综合质量只作摘要，不取代条目来源。Web 不再根据 `change_pct`、`amount` 或 LLM 字段自行猜测。

## 字段

每条 explanation item 包含：

- `code`：稳定原因代码，例如 `selection_reason`、`top_factors`、`news`、`quote_change_pct`、`awaiting_evidence`。
- `text`：用户可见说明。
- `source`：`screening`、`realtime_quote`、新闻来源、事件来源或 `llm`。
- `quality`：`observed`、`inferred` 或 `unknown`。
- `value`：可选数值；真实 `0` 必须原样保留。

`explanation_quality.why_selected/why_now` 汇总为 `ok`、`partial` 或 `unknown`。

## Why Selected

确定性本地解释优先使用 screening reason 和当前策略实际参与评分的因子；零权重或未配置的因子既不会进入缺省 `selection_reason`，也不会被写成“核心因子”，两处展示顺序都按“因子分数 × 策略权重”的真实贡献排列。`risk_summary` / `risk_level` 始终保留在独立风险展示，不会在缺少 reason 时提升为 `selection_reason`；行业标签也不会单独冒充入选依据。缺少 reason 和可核验加权因子时只确认“已进入当前选股候选结果”，不会把可能经过 LLM 排序、组合约束或后处理调整的最终名次误写成“确定性筛选排名”。来自 `post_analysis_summaries` 的 DSA/外部 analyzer 摘要保留 `post_analyzer:<name>` 来源并标记为 inferred，不冒充本地 observed；即使候选同时已有显式 `reason` / `ranking_reason`，后分析摘要也会作为 `post_analysis_summary` 一并返回。去重身份为 `(text, source, quality)`：同一来源和质量的相同文案只保留一次，不同来源或质量即使文案相同也分别保留。显式 reason 若只是后分析摘要的别名，不凭空增加 screening/observed 来源。纯本地确定性 `scorecard` 摘要保持 observed，但只要 scorecard 消费了 `llm_confidence`、`llm_catalysts` 或 `llm_risks`，其解释质量就保持 inferred。LLM ranking 的 `reason` 与 `thesis` 都是合法独立解释入口，即使仅返回 thesis 也保留为 llm/inferred；两者内容不同则同时保留，相同则按上述身份去重。归一化 raw 包装对象时先合并响应字段，再判断 scorecard 是否消费了外层 LLM 输入。即使 LLM 未配置、超时或返回无效结构，候选仍至少返回入选结果说明；LLM 不是本地解释的前置条件。

后分析器省略摘要、返回 `null` 或空白摘要时，若 `post_analysis_status` 为 `completed` 且 `post_analysis_score_deltas` 是有限非零数值，Why Selected 返回 `post_analysis_score_delta` 条目，说明分析器已完成、评分调整值以及未提供摘要；`value` 保留带符号的分差，来源仍为 `post_analyzer:<name>`，质量沿用该分析器摘要的规则。该条目只说明评分影响，不推测调分依据。有摘要时沿用摘要条目，不重复追加调分说明；失败、跳过、零分差或无有效分差时不生成此类条目。归一化、服务响应和历史持久化保留状态、分差及生成的解释，不改变原评分与重排行为。

## Why Now

时点解释只使用带来源的证据：DSA 新闻、事件，以及 `dsa_context.quote` 中明确存在的实时行情字段。新闻与事件都必须带可解析的 `published_date`，且发布时间在最近 30 天内；解析复用 SearchService 已支持的 ISO、RFC 2822、中文日期、Unix timestamp 和相对日期格式。缺日期或过期的新闻/事件不标记为 observed，包括复用已补充候选上下文而未重新搜索的路径。候选顶层的 `change_pct=0` 或 `amount=0` 不能单独证明数据真实存在，因为旧数据源可能用 0 表示缺失；没有 quote provenance 时返回 `awaiting_evidence`，不会写成“当前涨跌幅 0%”。

当 `dsa_context.quote.change_pct` 明确存在且为 `0` 时，它是合法平盘数据，返回 `value=0` 和 `quality=observed`。LLM catalyst 可作为 `inferred` 补充，但不能冒充观测事实。
若 quote 标记 `is_stale`/`price_stale`，或质量为 partial/unavailable/stale/missing/fetch_failed，则其中数值不进入 Why Now observed；没有其他新鲜证据时返回 `awaiting_evidence`。

## 当前阶段边界

本阶段只完成 API explanation 和 Web 展示。Issue #2282 中的策略 metadata 扩充、结果行 action、run history diff、export/backtest 等仍是后续范围。

## 回滚

移除 explanation 生成、Web 字段/卡片和对应测试即可回滚；原候选字段与 screening 排序流程保持兼容。

## 浏览器验收

`cd apps/dsa-web && npx playwright test --config playwright.fixture.config.ts` 使用固定 API fixture 渲染真实页面，不依赖后端服务或密钥。CI 的 `web-gate` 安装 Chromium、执行验收，并将截图上传为 `web-ui-evidence-<head SHA>` artifact（保留 30 天）；截图不提交到仓库。该验收验证页面交互和展示，不代表实时 provider/LLM 可用性。

## 旧版历史兼容

打开或自动恢复旧版已持久化运行时，若候选缺少 `why_selected` 但保留 `reason`、`llm_thesis` 或后分析摘要，Web 在解释卡片保留所有不同的“历史摘要（来源未记录）”，来源为 `legacy_result`、质量为 `unknown`。不会用当前策略权重重新解释旧因子，也不会把旧行情或顶层占位 0 当作当前 observed 证据。已有 explanation 数组优先使用；兼容展示不回写数据库、不修改历史记录。

## 验收矩阵

- 接受的 ranker 响应：reason-only、thesis-only、reason+thesis、同文案 reason/thesis、risk-only。
- 归一化：plain Pick、raw 包装字段、重复归一化后 provenance 保持一致。
- 后分析：显式 reason 与每个 analyzer 共存；真实 scorecard、DSA 和 external_http 调分并重排后，排名理由与已完成的 analyzer 摘要仍分别保留；external_http 无摘要的正负调分与重排保留通用来源说明，服务响应与历史记录一致；同文案不同来源不丢失 inferred；本地 scorecard 与消费 LLM 输入的 scorecard 分别分类。
- 传输/持久化：同步 screen、异步 task、history 的前端映射保留条目；screen 保存和 history_detail 读取逐项一致。
- 页面：混合来源逐条标注，综合 partial 不覆盖单条 observed/inferred；旧历史来源 unknown；真实 0 与缺失值分离。

### 预补充证据刷新

后排名补充与 Why Now 使用相同的可用性判断：新闻和事件必须有来源、非空标题/摘要，且发布时间在 30 天窗口内。仅当两类缓存均可用时跳过补充；过期、无日期或缺来源/正文的一类会单独刷新，另一类有效缓存和已有行情/基本面继续复用。刷新失败保留降级告警，不把旧新闻提升为 observed；候选数上限和原搜索超时保持不变。

标题和摘要分别去除首尾空白后取值；标题缺失或仅含空白时使用有效摘要。缓存判断与 Why Now 展示复用同一正文取值，避免空白标题遮蔽摘要并触发不必要的刷新。

回归验证覆盖真实 `screen()` 入口、搜索响应归一化及 `history_detail()` 读取：顶层或上下文中的过期/无日期新闻与事件触发单类刷新，新证据以 observed 写入响应和历史；两类缓存均有效时跳过补充并保留已有告警。

### 无理由模型排序

成功接受的 LLM 排序结果即使省略 reason/thesis（包括仅 risk、仅 code 的合法响应），仍以 llm/inferred 显示“模型已参与排序（未提供入选理由）”，整体 Why Selected 为 partial；真实 0 分仍算模型输入。风险文本只保留在风险区，失败后回退的纯因子结果不添加模型参与项。

回归验证使用双候选实际重排，覆盖缺省分数、零分及 risk-only 响应；重排后每个候选的本地加权因子保持 observed，模型参与项保持 inferred，重复归一化后综合质量仍为 partial。

### 浏览器测试入口隔离

`npm run test:smoke` 使用默认 `playwright.config.ts`，明确排除 `e2e/fixtures/`；未设置 `DSA_WEB_SMOKE_PASSWORD` 时继续跳过需要登录的 smoke，不启动后端/Web 服务。选股的 5 个 API mock fixture 仅通过 `npx playwright test --config playwright.fixture.config.ts` 运行，该配置独立启动 Web 服务，不需要密码或后端。CI 同时执行无密码默认入口与专用 fixture 入口，避免仅专用配置通过掩盖默认入口回归。
