# AnalysisContextPack：P0 盘点、P1/P2 契约、P3 Runtime Consumption、P4 可见性、P5 数据质量、#1386 P6 联动与 #1389 P6 迁移回滚

本页是 Issue #1389 的专题文档，用于记录当前 DSA 分析上下文的真实来源、消费路径、字段状态边界，以及 `AnalysisContextPack` 内部契约、builder、运行态消费、低敏可见性、数据质量评分、告警/持仓/历史/回测联动、迁移和回滚边界。P0 负责现状盘点和契约边界；P1 只新增内部 schema/envelope、block catalog、类型约定和脱敏序列化；P2 只从 pipeline 已有 artifacts 组装 pack；P3 只把低敏摘要接入普通分析和 Agent 初始 Prompt；P4 只把低敏 overview 接入历史详情、同步分析响应、completed task status 和 Web 报告页；P5 在同一 `PACK_VERSION = "1.0"` 内补齐数据质量评分、`fetch_failed` 状态、Prompt 数据限制和 overview 低敏展示；#1386 P6 复用同一公开 overview 做告警、持仓、历史、回测和通知联动，并在手动持仓分析时加入可选辅助 `portfolio` block；#1389 P6 只补齐文档、配置可见性、迁移和回滚说明，不新增 pack runtime、pack feature flag、DB migration 或 schema 版本。

## 术语与边界

当前仓库里有多种名为 context / snapshot 的数据面，P0 必须先消歧，避免把现有运行时结构误写成未来 pack。

| 术语 | 当前含义 | 当前主要消费方 | P0 边界 |
| --- | --- | --- | --- |
| `storage.get_analysis_context()` | `src/storage.py` 中从数据库最近两天 OHLCV 生成的技术面简上下文，包含 `today`、`yesterday`、`volume_change_ratio`、`price_change_ratio`、`ma_status` 等。当前实现接收 `target_date`，但实际仍取最新两天数据。 | 普通分析主链路、Agent 工具 `get_analysis_context` | 记录为历史技术面输入来源，不把它直接等同于未来 pack。 |
| `enhanced_context` | 普通分析中由 `src/core/pipeline.py` 基于 DB 简上下文、实时行情、筹码、趋势、基本面和语言信息增强后的 prompt 上下文。 | `src/analyzer.py` prompt 渲染、`_build_context_snapshot()` | 记录当前 prompt 输入面；P0 不改变字段名或结构。 |
| `analysis_history.context_snapshot` | 分析完成后写入历史表的持久化快照。普通分析通常包含 `enhanced_context`、`news_content`、`realtime_quote_raw`、`chip_distribution_raw`；Agent 路径保存 `initial_context`。 | 历史详情、同步 analysis/status 响应、回测、部分基本面 fallback 展示 | 记录为持久化消费面；必须保留 `context_snapshot.enhanced_context.date` 兼容。 |
| Agent executor message context | `AgentExecutor._build_user_message()` 注入首轮用户消息的上下文，适用于 `AGENT_ARCH=single` 路径，目前包含股票代码、报告类型、输出语言、`realtime_quote`、`chip_distribution`、`news_context`。 | 单 Agent 首轮 LLM 消息 | 记录当前首轮可见字段；P0 不补 runtime 注入。 |
| Agent orchestrator `AgentContext` | `AgentOrchestrator._build_context()` 写入多 Agent 共享上下文，适用于 `AGENT_ARCH=multi` 路径，可预注入 `realtime_quote`、`daily_history`、`chip_distribution`、`trend_result`、`news_context`。 | Technical / Intel / Risk / Decision 多 Agent 链路 | 记录为 orchestrator 内部共享数据面；不预注入 `fundamental_context`，`trend_result` 是否存在取决于 caller 是否传入。 |

## P0 范围与非目标

P0 的目标是让后续 P1/P2/P3 可以基于真实仓库边界设计 `AnalysisContextPack`，而不是提前改造运行时。

- P0 覆盖普通分析、Agent、告警、持仓、回测、历史、通知七条路径的上下文盘点。
- P0 固定字段质量状态词；P1 已新增 `AnalysisContextPack` 内部 schema，但仍不新增 builder、不接入 runtime、不公开完整 pack。
- P0 不新增 builder，不新增配置项，不新增数据库字段，不改变 API、报告、历史或通知 payload。
- P0 不接入 runtime，不改 `src/` 分析、Agent、告警、持仓、回测或通知逻辑。
- P0 不 pack 化 `market_review`、`market_light` 或大盘红绿灯专题快照；这些只作为历史快照中的其他 `report_kind` / 专题消费边界记录。
- P0 当时不把 `fetch_failed` 加入字段质量状态词；P5 已在同一 1.0 umbrella 内追加该状态，用于明确区分“不支持”和“本次抓取失败”。
- P0 不在 README 扩写实现细节；本页作为专题文档，由 `docs/INDEX.md` / `docs/INDEX_EN.md` 入口发现。

## P1 内部契约

P1 落地 `src/schemas/analysis_context_pack.py`，只定义内部 schema/envelope，方便 P2 builder 和 P3 runtime 消费时复用同一结构。P1 不填充运行时数据、不新增 fetcher、不改变 Prompt、不写入 history/task/report metadata，也不把完整 pack 暴露到 API、Web、Bot、Desktop 或通知。

P1 schema 包含：

- `PACK_VERSION = "1.0"`，并通过 `AnalysisContextPack.pack_version` 标记契约版本。
- `ContextFieldStatus`：P1 首版只允许 `available`、`missing`、`not_supported`、`fallback`、`stale`、`estimated`、`partial`；P5 已追加 `fetch_failed`，表示字段或数据块本次抓取明确失败，不代表整次分析失败。
- `AnalysisSubject`：顶层身份槽，只包含 `code`、`stock_name`、`market`；`exchange`、`currency`、`industry` 留给后续扩展，P2 builder 不扩 P1 schema，也不重复新增 `identity` block。
- `AnalysisContextItem`：字段级输入项，包含 `status`、`value`、`source`、`timestamp`、`fallback_from`、`missing_reason`、`warnings`、`metadata`。
- `AnalysisContextBlock`：数据块级分组，包含 `status`、`items`、`source`、`timestamp`、`warnings`、`metadata`，其中 `items` 是 `Dict[str, AnalysisContextItem]`。
- `DataQuality`：P1 只保留 `warnings` 与 `metadata` 容器；P5 已追加 `overall_score`、`level`、`block_scores`、`limitations`，仍保持低敏，不承载 raw payload。
- `AnalysisContextPack`：顶层 envelope，包含 `pack_version`、`subject`、`phase`、`blocks`、`data_quality`、`metadata`、`created_at`。

时间字段约定：

- `AnalysisContextPack.created_at` 使用 `datetime`，由 `model_dump(mode="json")` 输出 ISO 8601 字符串。
- `AnalysisContextItem.timestamp` 与 `AnalysisContextBlock.timestamp` 使用 `Optional[str]`，约定为 ISO 8601 datetime 字符串；P1 schema 在构造时校验该格式，date-only、自然语言时间或斜杠分隔日期会被拒绝；P2 builder 复用现有 artifact 时间戳时不做强制二次转换。

状态语义：

- `block.status` 表示整块可用性。
- `item.status` 表示字段级质量。
- P1 不实现 `item.status` 到 `block.status` 的自动聚合推导。

P1 Block Catalog：

| block key | P1 语义 | P1 边界 |
| --- | --- | --- |
| `quote` | 实时行情和报价相关输入 | 只定义可表达位置，不抓取或填充数据。 |
| `daily_bars` | 完整日线窗口和最近完整日线日期 | P1 不判断 partial bar。 |
| `technical` | 技术指标、量价结构和形态 | P1 不生成指标。 |
| `fundamentals` | 估值、成长、盈利、财报和股东回报 | P1 不新增基本面 fetcher。 |
| `news` | 新闻、公告、舆情和催化事件输入 | P1 不改变新闻搜索。 |
| `portfolio` | 是否持仓、账户摘要、成本、数量、仓位和 stale 摘要 | P1 不纳入交易流水、现金流水或完整账户隐私数据。 |
| `chip` / `capital_flow` | 筹码、资金流和主力行为 | 后续扩展键，P1 只允许契约表达。 |
| `events` / `market_context` | 风险事件、市场宽度、指数、板块和热点环境 | 后续扩展键，不把 `market_review` / `market_light` 作为首版单股 pack。 |

`phase` 字段只接收 #1386 `MarketPhaseContext.to_dict()` 产物，保持 `Dict[str, Any]`，不重新定义 phase enum 或 phase 子模型。

脱敏边界：

- `AnalysisContextPack.to_safe_dict()` 先执行 `model_dump(mode="json")`，再调用 `redact_sensitive_mapping()`。
- `redact_sensitive_mapping()` 只做 dict/list 的 key-based 递归脱敏，命中 `api_key`、`access_token`、`refresh_token`、`authorization_header`、`webhook_url`、`password`、`cookie`、`secret`、`token`、`sendkey`、`license_key` 等敏感键或短语时把值替换为 `[REDACTED]`。
- P1 不扫描普通字符串值，不做 URL 正则脱敏，不把 `data_api` 或裸 `api` / `key` 当作敏感命中，避免把本契约扩展成通用 secrets engine。

## P2 Builder 契约

P2 新增 `AnalysisContextBuilder`，但首版只做 assembler：从普通分析 pipeline 已经拿到的 artifacts 组装内部 `AnalysisContextPack`。Issue 验收项里的“复用现有数据源”在本 slice 中解释为复用 pipeline 已 fetch 的 `realtime_quote`、`base_context`、`enhanced_context`、`trend_result`、`chip_data`、`fundamental_context`、`news_context` 等 artifacts；builder 本身 zero-fetch，不调用 DB、fetcher、SearchService、Agent 工具或具体 provider。

P2 输入契约使用 `PipelineAnalysisArtifacts`：`code`、`stock_name`、`market`、`phase`、`base_context`、`enhanced_context`、`realtime_quote`、`trend_result`、`chip_data`、`fundamental_context`、`news_context`、`news_result_count`、`metadata`。单股 `build()` 与批量 `build_batch()` 复用同一结构，避免 P3 runtime 接入时再次改签名。

P2 block 组装边界：

- `subject` 仍只写 `code`、`stock_name`、`market` 三字段，不扩 `AnalysisSubject`。
- `phase` 只接收传入的 `MarketPhaseContext.to_dict()` 产物，不从 `enhanced_context` 反推。
- `quote` 从 `realtime_quote` 组装；缺失为 `missing`；`source=fallback` 或显式 `fallback_from` 映射为 `fallback`，但 `source` 保留真实成功源；`fallback_from` 只在 artifact/metadata 显式提供时填写，否则只记录稳定 warning code，不伪造 provider 链。
- `quote` 会透传 #1386 P3 的 `fetched_at`、`provider_timestamp`、`is_stale`、`stale_seconds`、`fallback_from`。状态优先级固定为 `STALE > FALLBACK > AVAILABLE`：`is_stale=True`、`price_stale`、`quote_stale`、`quote_stale_seconds` 等显式 marker 标为 `stale`；`stale_seconds` 且 `is_stale=False` 只是元数据，不单独推断 stale。builder 只映射上游 artifact，不做质量评分。
- `daily_bars` 只表达完整日线窗口，优先读 `base_context.today`、`base_context.yesterday`、`base_context.date`、`base_context.data_missing`；date-only 放入 `value` 或 `metadata`，不写入 `timestamp`。
- `enhanced_context.today` 上的 `is_partial_bar`、`is_estimated`、`estimated_fields` 优先进入 `technical`；缺失时仍兼容 `enhanced_context.today.data_source` 为 `realtime:*` 的旧 heuristic。partial/estimated 只进入 `technical`，`daily_bars` 不承载 partial/estimated，warning 使用 `intraday_realtime_overlay`。
- `technical` 优先复用 `trend_result.to_dict()`；无 trend artifact 时为 `missing`。
- `chip` 复用 `chip_data.to_dict()`；无 chip artifact 默认 `missing`，只有输入 metadata/artifact 明确 not_supported 时才标 `not_supported`。
- `fundamentals` 只读 `fundamental_context` 参数；`ok` 映射为 `available`，`not_supported` 映射为 `not_supported`，`partial` 映射为 `partial`，P5 后 `failed` 映射为 `fetch_failed` + 稳定 reason code `fundamental_pipeline_failed`；不写入 `errors[]` 原文。
- `news` 非空白字符串为 `available`，空白或缺失为 `missing`；`news_result_count` 写入 pack metadata。

P2 不组装 `portfolio`、`events`、`market_context`，也不把 `capital_flow` 拆成独立 block；首版只把它保留在 fundamentals 的 coverage/source chain metadata 中。P2 当时也不改变 Prompt、不让普通分析或 Agent runtime 消费 pack、不写入 history/task/report metadata、不暴露完整 pack 到 API/Web/Bot/Desktop/通知；P5 只在现有 builder 上追加低敏评分、`fetch_failed` 细分和 Prompt 限制，不新增 fetcher。

## P3 Runtime Consumption

P3 在 P2 `AnalysisContextBuilder` 之后接入运行态消费，但消费面限定为低敏 `analysis_context_pack_summary`。`StockAnalysisPipeline` 是 summary 的唯一生产者：在普通分析路径和 Agent 路径内完成 `PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()` -> `format_analysis_context_pack_prompt_section()`，下游 analyzer、single-agent、multi-agent 只接收 summary 字符串，不自行构造完整 pack，也不读取 `AnalysisContextPack.to_safe_dict()` 的 block item 原始值。

普通分析 Prompt 的顺序固定为：基础信息 -> #1386 `market_phase_context` 渲染区块 -> `analysis_context_pack_summary` -> 技术面、实时行情、新闻等既有区块。`analysis_context_pack_summary` 只包含 subject、`pack_version`、block `status` / `source` / `warnings` / `missing_reason`、`metadata.news_result_count`、`data_quality.warnings` 和 P5 低敏数据限制，不得输出 `news.content`、`trend_result`、`chip`、`fundamental_context` 等原始 payload。

Agent 路径同样只传 summary。`AgentExecutor._build_user_message()` 在 market phase 段之后、pre-fetched JSON 之前插入 summary；`AgentOrchestrator._build_context()` 只把 summary 放入 `ctx.meta["analysis_context_pack_summary"]`，禁止写入 `ctx.data`；`BaseAgent._build_messages()` 在 market phase user message 之后、`_inject_cached_data()` 之前插入 summary。Agent 路径会在 `_ensure_agent_history()` 预取后读取一次 `storage.get_analysis_context()` 作为 `daily_bars` 的低敏状态来源，读取失败或无可用上下文时才标记 `daily_bars_missing`，该读取 fail-open 且不把日线原始 payload 写入 Agent runtime context。Agent 首轮没有复用普通分析新闻检索，`news` block 为 `missing` 是当前 P3 的预期状态。

P3 当时不持久化完整 pack，不新增 API/Web/Bot/Desktop 字段，不改变报告 JSON schema，不把 summary 写入 `analysis_history.context_snapshot`、task status 或 report metadata；history snapshot 和 diagnostic snapshot 会剥离 `market_phase_context`、`analysis_context_pack`、`analysis_context_pack_summary` 等 runtime prompt key。P4 在此基础上新增低敏 overview，可见性只覆盖历史详情、同步分析响应、completed task status 和 Web 报告页；P5 继续复用 summary 消费路径，不改 LLM 输出 JSON schema。Agent 工具级 pack cache 复用仍是后续工作。

## #1381 Daily Market Context

#1381 在 AnalysisContextPack 之外新增一个小型每日大盘环境摘要通道，避免把 `market_review` / `market_light` 直接 pack 化。`DAILY_MARKET_CONTEXT_ENABLED` 默认开启；当 `MARKET_REVIEW_ENABLED=true` 且 `DAILY_MARKET_CONTEXT_ENABLED=true` 时，`StockAnalysisPipeline` 会按个股市场（`cn` / `hk` / `us`）加载当日大盘上下文：优先复用 `analysis_history(code=MARKET, report_type=market_review)` 中同日同市场记录；没有同日记录时才调用 `run_market_review(..., return_structured=True, send_notification=False)` 生成本次上下文，且通过进程内 cache 避免同一 Pipeline 重复生成，并在 CLI/定时任务并发路径上通过 market review lock 串行化生成。`DAILY_MARKET_CONTEXT_ENABLED=false` 只关闭个股分析的低敏摘要注入与保守护栏，不关闭大盘复盘本身。

**Background：**`#1381` 聚焦单股分析的当日大盘上下文复用与回退控制，不改变现有日内阶段、日报或状态建模架构。该段与 `docs/CHANGELOG.md` [Unreleased] 的 #1381 条目保持一致，可作为本轮变更说明的收敛边界。
**Scope（本轮实现范围）：**`#1381` 仅覆盖后端 runtime 的大盘上下文注入、当日/目标交易日复用控制与保守护栏；不包含独立 API、Web 阶段结果独立展示、四阶段日报结构化持久化或新增日报状态表。涉及主要入口为 `main.py`（调度与 `--no-market-review`）、`src/core/pipeline.py`、`src/core/market_review.py`、`src/services/daily_market_context.py`、`src/analyzer.py`、`src/analysis_context_pack_overview.py`、`src/agent/executor.py`、`src/agent/orchestrator.py`、`src/agent/agents/base_agent.py`、`src/daily_market_context_guardrail.py`；Web 侧仅同步 `DAILY_MARKET_CONTEXT_ENABLED` 设置项文案/帮助，不新增阶段结果展示。
**验收闭环边界：**本 PR 仅对应 `#1381` 的 runtime 接入与护栏子目标；除非独立 API、Web 阶段展示、四阶段日报持久化和日报状态表已在后续变更中落地并验证，否则不得把 Issue #1381 标记为完整验收通过。
**Acceptance Criteria（验收边界）：**本轮仅按 runtime 与配置入口验收，不纳入 PR 过程中的 API/Web UI 独立阶段展示验收。当前验收路径限制为 `tests/test_main_schedule_mode.py`、`tests/test_pipeline_daily_market_context.py`、`tests/test_daily_market_context.py`、`tests/test_daily_market_context_guardrail.py`、`tests/test_agent_executor.py`、`tests/test_config_env_compat.py`、`tests/test_config_registry.py` 和 `apps/dsa-web/tests/system_config_i18n.test.ts`。重点覆盖项为：`--no-market-review` 禁止触发大盘复盘生成、`DAILY_MARKET_CONTEXT_ENABLED=false` 关闭个股上下文注入但保留大盘复盘、单次 schedule 复用同一 `target_date`、多市场上下文加载（`cn,us`）、`daily_market_context` 只在同一次分析主链路注入一次、普通分析与 Agent 路径应用护栏且不泄漏原始 `market_review_payload`。
**Compatibility/Risk（兼容与风险）：**`#1381` 不改变 `provider/model/base_url`、默认模型或配置清理/回填/迁移语义；不新增数据库或运行时配置表变更。`main.py::_bootstrap_environment`、`src/core/pipeline.py`、`src/analyzer.py`、`src/agent/executor.py`、`src/agent/orchestrator.py`、`src/agent/agents/base_agent.py`、`src/services/daily_market_context.py`、`src/daily_market_context_guardrail.py` 只在既有读取链路消费 LLM 与市场复盘上下文，不新增 `SystemConfig` 保存或回写分支。官方兼容依据沿用 `LiteLLM OpenAI-compatible` 与 `OpenAI Chat Completion`（见后文“兼容性证据与核验边界”）；回滚方式为常规发布回滚（撤销相关提交），如必要可配合重启并清理 `env_file` / `--env-file` / 进程级同名环境覆盖项，恢复用户历史持久化配置。
**兼容性证据与核验边界：**本轮仅复用既有 LLM 配置链路读取配置，不新增 `.env` 写入分支，不新增配置迁移/清理/回写入口。官方依据沿用：`LiteLLM OpenAI-compatible` <https://docs.litellm.ai/docs/providers/openai_compatible>、`OpenAI Chat Completion` <https://platform.openai.com/docs/api-reference/chat/create>；版本约束见 `requirements.txt`（`litellm`、`openai`）当前窗口。可回溯代码路径：`main.py::_bootstrap_environment`、`src/analyzer.py::_init_litellm`、`src/agent/agents/base_agent.py::_get_analyzer_config`（仅读取）、`src/agent/executor.py`、`src/agent/orchestrator.py`、`src/core/pipeline.py`、`src/services/daily_market_context.py`、`src/daily_market_context_guardrail.py`。回归核验点为 `tests/test_config_env_compat.py`、`tests/test_config_registry.py`、`tests/test_system_config_service.py`、`tests/test_system_config_api.py`、`tests/test_llm_channel_config.py`、`tests/test_market_review_runtime.py`。

普通分析与 Agent 分析只接收低敏字段：`daily_market_context`（region、trade_date、summary、risk_tags、source、可选 position_cap）和 `daily_market_context_summary` Prompt 段，不传递完整 `market_review_payload`、原始新闻、密钥或通知配置。普通分析 Prompt 在市场阶段段落后、技术面数据前插入大盘摘要；Agent 单体与多 Agent 路径在 market phase 后、pre-fetched 数据前插入同一摘要。Agent 自由聊天只在调用方已经提供 `daily_market_context` / `daily_market_context_summary` 时注入，不为每次聊天自动触发大盘复盘。

结果后处理新增保守大盘环境护栏：当摘要或标签显示 `high_risk`、`market_cooling`、`conservative`、`low_position_cap`，且处于保守/高风险语境下时，模型给出 `buy` 决策（含“立即买入/追高/激进加仓”等买入类建议）会被软化为观望或小仓等待确认，并把高置信度降为中等。该护栏只修改当次 `AnalysisResult` 与 dashboard 中的低敏限制说明，不新增数据库表或 API 字段。回滚方式为撤销 #1381 相关服务、Prompt 注入和 guardrail 代码，既有大盘复盘历史记录保持兼容。

## P4 历史记录、任务状态与 Web 可见性

P4 把 P3 已构建的 `AnalysisContextPack` 投影为公共低敏 `analysis_context_pack_overview`。该 overview 由专用 renderer 生成，公共 API 不允许直接返回 `AnalysisContextPack.to_safe_dict()` 或完整 pack dump。renderer 只输出白名单字段：`pack_version`、`created_at`、`subject.code` / `stock_name` / `market`、数据块 `key` / `label` / `status` / `source` / `warnings` / `missing_reasons`、按 block status 计数的 `counts`、顶层 `data_quality.warnings` 和 `metadata.trigger_source` / `metadata.news_result_count`。P5 在同一 overview 上追加 `data_quality` 低敏对象，不重复顶层 `warnings`。

overview 不输出 `blocks.*.items`、`items.value`、`news.content`、`trend_result`、`chip`、`fundamental_context` 原始 payload，也不输出 `api_key`、`token`、`cookie`、`webhook_url`、`password`、`secret`、`authorization`、`sendkey`、`license_key` 等敏感键或值。

P4 持久化面只在 `analysis_history.context_snapshot` 顶层写入 `analysis_context_pack_overview`。运行态 prompt 字段仍会从 `enhanced_context` 和 history snapshot 中剥离：`market_phase_context`、`analysis_context_pack`、`analysis_context_pack_summary` 不进入公开历史详情或任务状态。`SAVE_CONTEXT_SNAPSHOT=false` 时不持久化整份 `analysis_history.context_snapshot`，因此也不会落库 overview、`market_phase_summary`、`enhanced_context` 或 raw snapshot 字段；旧记录或缺少 overview 的记录继续返回空字段，不影响历史详情读取。

公共 API 字段固定为 `report.details.analysis_context_pack_overview`，Web 端经深度 camelCase 后读取 `analysisContextPackOverview`。接线面包括：

- `GET /api/v1/history/{record_id}` 历史详情。
- 同步 `POST /api/v1/analysis/analyze` 返回的 `AnalysisResultResponse.report.details`，但 overview 依赖已持久化的 `analysis_history.context_snapshot`；`SAVE_CONTEXT_SNAPSHOT=false` 时，新记录不保证返回 overview。
- completed `GET /api/v1/analysis/status/{task_id}`，包括内存队列 enrichment 和 DB completed fallback。

API 返回给 Web 的 `details.context_snapshot` 会通过 `sanitize_context_snapshot_for_api()` 剥离顶层 `analysis_context_pack_overview`，避免 raw snapshot 面板重复展示或被当作完整上下文导出；overview 只从 `extract_analysis_context_pack_overview()` 单独取出。Agent 路径与普通分析路径写入同一 overview 形状，Agent 无新闻计数时 `metadata.news_result_count` 可为空。

P4 Web 展示只在报告详情页渲染 `AnalysisContextSummary`，位置在策略点位和资讯之后、运行诊断之前；该区域默认折叠，折叠头部展示可用数、缺失数、非零的其他状态计数和触发来源，展开后的每个数据块只展示状态、来源、告警和说明。来源为空时显示“未记录输入来源”；说明行把已知缺失原因翻译为原因、对本次分析的影响和简短处理建议，并在括号中保留诊断码，未知原因则按 block 状态提供通用建议。`fallback`、`stale`、`estimated`、`partial` 等没有缺失原因的降级状态也在同一说明行解释，不新增处理、范围或证据字段。报告页相关资讯由独立接口加载，其有无不能通过 overview 的 `metadata.news_result_count` 推断；资讯区只说明自身是报告页补充资讯，输入数据块只说明新闻是否进入本次 LLM 分析，避免把两套数据范围混为同一结果集。展开区仍展示状态计数和新闻结果数。P5 后折叠头部还会展示质量分/等级，展开后展示 `limitations` 和 `fetch_failed` 状态。无 overview 时不渲染占位。在 #1386 P4b 中，Web 会在同一报告详情页展示 `report.meta.market_phase_summary` 阶段标签，并继续复用该低敏数据质量摘要；不扩大完整 pack、Prompt summary、raw payload 或 snapshot 内部字段的公开面。P4/P5 不覆盖 pending/processing TaskPanel 的 AnalysisContextPack 数据质量摘要或 SSE 进行中 overview 可见性，不改通知摘要、Bot/Desktop 专属展示或 `market_review` overview。

## P5 数据质量评分与 Prompt 数据限制

P5 在不升级 `PACK_VERSION`、不新增 fetcher、不新增配置项、不做历史迁移的前提下补齐三件事：内部低敏数据质量评分、跨模型通用的 Prompt 数据限制区块，以及既有 `analysis_context_pack_overview` 的低敏可见性扩展。#1389 P5 仍不改变 LLM 输出 JSON schema，也不做后处理强制改写；#1386 P5 会消费这里的低敏输入质量，在报告 `dashboard.phase_decision` 中输出盘中动作字段与质量护栏结果。

状态契约新增 `fetch_failed`，用于“当前字段或数据块本次抓取明确失败”。首版只在已有 artifact 明确失败时使用，例如 `fundamental_context.status == "failed"`；空新闻、未配置搜索、无实时 quote artifact 或 chip 缺失仍保持既有 `missing` / `not_supported` 语义，避免把未启用能力误报成抓取失败。`fetch_failed` 不代表整次分析失败。

`DataQuality` 追加以下低敏字段，并保留旧 `warnings` / `metadata`：

- `overall_score: Optional[int]`：0-100 总分。
- `level: Optional["good"|"usable"|"limited"|"poor"]`：`>=85 good`、`>=70 usable`、`>=55 limited`，否则 `poor`。
- `block_scores: Dict[str, int]`：固定六块的状态分。
- `limitations: List[str]`：最多 5 条稳定限制说明，使用 `block: status` 形式。

评分只计算固定六块，不随辅助块缺失重归一化，未来新增 block 不自动影响总分。权重固定为 `quote=25`、`daily_bars=25`、`technical=25`、`news=10`、`fundamentals=10`、`chip=5`；状态分固定为 `available=100`、`partial=75`、`estimated=75`、`not_supported=70`、`fallback=65`、`stale=50`、`missing=35`、`fetch_failed=25`。总分公式为 `round(sum(block_score * weight) / 100)`。

`limitations` 优先列出核心块 `quote` / `daily_bars` / `technical` 的 `stale`、`fallback`、`missing`、`fetch_failed`、`partial`、`estimated`；其次列出辅助块 `news` / `fundamentals` / `chip` 的 `fetch_failed`、`fallback`、`stale`。辅助块单纯缺失不进入限制列表，避免把新闻缺失、未配置搜索或不支持能力解释成利好/利空。

Prompt 数据限制只在 `format_analysis_context_pack_prompt_section()` 内渲染，紧跟 pack summary，因此普通分析、single Agent 和 multi-agent 复用同一消费路径。中文输出 `数据限制`，英文输出 `Data Limitations`；只有真实 score 存在时才输出评分行。若 `quote`、`daily_bars` 或 `technical` 为 degraded 状态，Prompt 明确要求最终 JSON 的 `confidence_level` 不得为 `高` / `High`。Prompt 继续只使用 status/source/warnings/missing_reason/低敏评分，不输出 raw payload、新闻正文、趋势原始值、secret、token 或 webhook。

#1386 P2-full 在 P5 score/limitations 之后、confidence/safety 之前追加最小的 `phase × degraded data` 交叉约束：当 `AnalysisContextPack.phase` 来自合法 `MarketPhaseContext`，且 `quote`、`daily_bars` 或 `technical` 存在 degraded 状态时，Prompt 只补充当前阶段下数据质量如何限制盘中判断、开盘计划或保守分析；它不替代 P5 的 confidence/safety 规则，也不复述 `market_phase_context` 的 phase-only 文案。`pack.phase` 缺失、非 dict 或包含非法 phase 时 fail-open，仅保留 P5 通用数据限制。

overview 只扩展现有公开面：`analysis_context_pack_overview.data_quality` 白名单包含 `overall_score`、`level`、`block_scores`、`limitations`，不重复公开 `warnings`。`render_analysis_context_pack_overview()` 与 `extract_analysis_context_pack_overview()` / persisted sanitizer 都会清洗该对象；旧 overview 缺少 `data_quality` 时仍正常读取。`details.context_snapshot` 继续剥离顶层 `analysis_context_pack_overview`，不公开完整 pack。

## P6 告警、持仓、历史和回测联动

#1386 P6 不新增 pack 版本，也不把完整 pack 暴露到更多公共面。它只复用 P4/P5 已定义的 `analysis_context_pack_overview` 和 #1386 已定义的 `market_phase_summary`：

- 告警触发记录仍写入现有 `alert_triggers.diagnostics` 文本字段；当 diagnostics 可 JSON 化时，worker 会合并 `analysis_visibility.analysis_context_pack_overview`，来源只允许 evaluator 已带 overview 或最近 30 天历史 snapshot。旧纯文本 diagnostics 不被覆盖，API 派生字段为空且 source 为 `legacy_text`。
- 持仓手动分析通过 API 构造低敏 `portfolio_context` 并传入 pipeline；builder 会在 pack 中加入可选 `portfolio` block。该 block 只包含账户 ID/name、symbol、market、currency、quantity、avg cost、total cost、unrealized PnL、price source/provider/date/stale/available 和 cost method，不包含交易流水、现金流水、新闻正文、Prompt、密钥或 webhook。
- `portfolio` block 是辅助块，`metadata={"auxiliary": true, "quality_weighted": false}`，不改变 P5 固定六块 `quote`、`daily_bars`、`technical`、`news`、`fundamentals`、`chip` 的权重、总分或 limitations 口径。
- `portfolio_context` 只在任务执行内部透传；`TaskInfo.to_dict()`、任务列表、SSE `task_created/task_started/task_completed/task_failed/task_progress` payload 不暴露该对象。
- 历史列表、单股历史、StockBar 和回测结果只读取 `context_snapshot` 顶层的公开 `market_phase_summary`；旧记录、`SAVE_CONTEXT_SNAPSHOT=false` 或解析失败返回 `null` / `unknown`，不失败。
- 回测 phase filter 只基于公开 summary 做 bucket：`premarket` 保持 premarket，`intraday|lunch_break|closing_auction` 归入 intraday，`postmarket` 保持 postmarket，`non_trading|missing|invalid` 归入 unknown。带 phase 过滤时 repository 先按 SQL 条件批量读取结果和 snapshot，服务层 bucket 后再分页和统计，避免 API 层分页后临时过滤。
- 通知摘要只消费 `market_phase_summary` 与 `analysis_context_pack_overview.data_quality`，输出阶段、trigger source、partial-bar warning、质量等级和前两条 limitations；不输出 raw pack、`analysis_context_pack_summary` Prompt 字符串、新闻正文或持仓敏感细节。

## P6 文档、迁移与回滚

P6 不改变 P1-P5 的运行时行为，只把已经落地的契约、可见性、配置、迁移和回滚边界写成稳定文档。它不新增 pack enable/disable feature flag，不升级 `PACK_VERSION = "1.0"`，不新增 API 参数，不改变报告 JSON schema，也不做数据库迁移。

四个数据面必须分开理解：

| 数据面 | 位置 | 可见性 | P6 边界 |
| --- | --- | --- | --- |
| 内部完整 pack | `AnalysisContextPack` / `AnalysisContextBuilder` 产物 | 仅内部运行态使用 | 不作为公共 API，不写入历史，不承诺外部稳定 wire contract。 |
| LLM 低敏摘要 | `analysis_context_pack_summary` | 普通分析、single Agent、multi-agent Prompt | 只包含 subject、pack version、block status/source/warnings/missing reason、新闻结果数和数据限制；不包含 `items.value`、新闻正文、趋势/筹码/基本面 raw payload、secret、token 或 webhook。 |
| 公共低敏 overview | `report.details.analysis_context_pack_overview` | 历史详情、同步分析响应、completed task status、Web 报告页 | 只输出白名单字段和 `data_quality` 低敏评分；不输出完整 pack、Prompt summary 或 raw payload。 |
| 历史上下文快照 | `analysis_history.context_snapshot` | 持久化后供历史/API/Web/诊断读取 | `details.context_snapshot` 经 `sanitize_context_snapshot_for_api()` 剥离 `analysis_context_pack_overview` 和 `market_phase_summary`，避免 raw 面板重复公开稳定摘要。 |

摘要可见性矩阵：

| 消费面 | 暴露内容 | 不暴露内容 |
| --- | --- | --- |
| LLM Prompt | `analysis_context_pack_summary` 低敏状态摘要和数据限制 | 完整 pack、`items.value`、新闻正文、趋势/筹码/基本面 raw payload、secret/token/webhook |
| `GET /api/v1/history/{record_id}` | `report.details.analysis_context_pack_overview` | 完整 pack、Prompt summary、raw `analysis_context_pack_overview` duplicate |
| 同步 `POST /api/v1/analysis/analyze` | `report.details.analysis_context_pack_overview`，前提是本次历史已持久化 `analysis_history.context_snapshot` | 完整 pack、Prompt summary |
| completed `GET /api/v1/analysis/status/{task_id}` | `status.result.report.details.analysis_context_pack_overview` | 完整 pack、Prompt summary |
| Web 报告页 | 默认折叠的 `AnalysisContextSummary`，展示 block 状态、来源、告警、包含影响/建议/诊断码的说明、质量分和限制 | 完整 pack、raw payload、Prompt summary、报告页独立加载的资讯结果状态 |
| raw `details.context_snapshot` | 剥离后的历史快照 | 顶层 `analysis_context_pack_overview`、`market_phase_summary` |
| 通知、Bot、Desktop 专属展示 | P6 不新增专属展示 | 完整 pack、Prompt summary、raw payload |

字段质量状态全集保持为 `available`、`missing`、`not_supported`、`fallback`、`stale`、`estimated`、`partial`、`fetch_failed`。这些状态解释输入数据质量，不表示分析任务、告警、回测或通知投递本身成功或失败。

脱敏边界：

- 完整 `AnalysisContextPack` 不进入公共 API、Web、通知、Bot 或 Desktop 专属展示。
- `AnalysisContextPack.to_safe_dict()` 只作为内部安全序列化 helper；公共 overview 仍必须通过 `render_analysis_context_pack_overview()` 投影。
- `analysis_context_pack_summary` 与 overview 都不得输出 `items.value`、新闻正文、`trend_result`、`chip`、`fundamental_context` 原始 payload、API key、token、cookie、完整 webhook URL、邮箱密码、secret、authorization、sendkey 或 license key。
- 已持久化 overview 再读取时必须经过 `extract_analysis_context_pack_overview()` / persisted sanitizer；API 透明度面板必须继续通过 `sanitize_context_snapshot_for_api()` 剥离顶层稳定摘要。

迁移边界：

- P6 不做 DB migration；旧历史记录缺少 `analysis_context_pack_overview` 或 `data_quality` 时返回空字段，报告仍正常读取。
- `SAVE_CONTEXT_SNAPSHOT=true` 是默认行为，会继续把 `analysis_history.context_snapshot` 作为历史透明度和诊断来源持久化。
- `SAVE_CONTEXT_SNAPSHOT=false` 或 CLI `--no-context-snapshot` 会停止持久化整份 `analysis_history.context_snapshot`；换言之，新历史不持久化整份 `analysis_history.context_snapshot`，包括 `enhanced_context`、`market_phase_summary`、`analysis_context_pack_overview`、`diagnostics`、`realtime_quote_raw` 和其他 raw snapshot 字段。
- 关闭持久化不影响当次 `AnalysisContextPack` 构建、`analysis_context_pack_summary` 注入 Prompt，也不影响内存中的 `result.diagnostic_context_snapshot`。

回滚方式：

| 手段 | 作用 | 不能做什么 |
| --- | --- | --- |
| 发布或代码回滚 P3-P5 相关改动 | 移除 pack prompt summary、overview 和数据质量接入 | - |
| `SAVE_CONTEXT_SNAPSHOT=false` 或 `--no-context-snapshot` | 停止保存新的历史 `context_snapshot`，从而不再从新历史公开 overview / phase summary / raw snapshot | 不能关闭当次 pack 构建或 LLM Prompt 中的低敏 summary |
| 运行时 pack 总开关 | 当前不存在 | 不能通过 env 一键关闭 P3-P5 pack 接入；需要代码回滚或后续单独设计 |

## 字段质量状态

未来 pack 的字段质量状态在 P0 先固定七词；P5 在同一 1.0 umbrella 内追加 `fetch_failed`。它们描述字段或数据块的质量，不描述业务流程是否成功。

| 状态 | 含义 | 示例边界 |
| --- | --- | --- |
| `available` | 字段存在，来源和时间戳可解释，当前路径可正常使用。 | 实时行情返回价格和来源；历史 K 线窗口满足计算需求。 |
| `missing` | 当前路径需要该字段，但实际未取到或为空。 | DB 无最近日线，普通分析进入 `data_missing` 结果。 |
| `not_supported` | 当前市场、数据源或路径不支持该字段，不应误报为错误。 | 某些市场无筹码分布或资金流。 |
| `fallback` | 首选来源不可用，使用了备用来源或旧路径。 | 持仓价格从实时行情 fallback 到历史收盘价。 |
| `stale` | 字段存在，但时间新鲜度不足。 | 持仓估值中的 `price_stale` / `fx_stale`。 |
| `estimated` | 字段是估算值，不应当作完整事实。 | 盘中用实时价补今日 bar 后生成技术估计。 |
| `partial` | 数据块部分可用、部分缺失。 | 大盘红绿灯 `data_quality=partial` 或工具返回 `partial_cache`。 |
| `fetch_failed` | 当前路径确认尝试过抓取，但本次抓取失败。 | `fundamental_context.status == "failed"` 映射为基本面 block 抓取失败。 |

## 现有状态映射

当前仓库已有不少状态词。P0 只建立映射或不映射关系，避免后续把业务结果状态混入字段质量枚举。

| 现有词或字段 | 当前位置 | 建议关系 | 说明 |
| --- | --- | --- | --- |
| `data_missing` | 普通分析缺历史数据结果 | 可映射到 `missing` | 这是核心输入缺失，不是业务成功状态。 |
| `cache_hit` / `partial_cache` | Agent 历史数据工具 | `partial_cache` 可映射到 `partial` | `cache_hit` 是来源/缓存元数据，不是质量状态。 |
| `source` / `data_source` / `realtime_source` | 数据源、告警、上下文快照 | 不映射 | 这些是来源元数据，应与字段质量状态并列保存。 |
| `price_source=missing` | 持仓快照 | 可映射到 `missing` | 表示估值价格不可用。 |
| `price_stale` / `fx_stale` | 持仓快照 | 可映射到 `stale` | 保留原字段作为业务元数据。 |
| `triggered` / `skipped` / `degraded` / `failed` | 告警评估与记录 | 不映射 | 这是规则评估或记录结果，不是字段级质量状态。 |
| `insufficient_data` / `completed` / `error` | 回测服务 | 不映射 | 这是回测执行状态；可在 pack 摘要中解释触发原因。 |
| `sent` / `no_channel` / `partial_failed` / `all_failed` | 通知发送 | 不映射 | 这是通知投递结果，不能反推分析输入质量。 |
| `data_quality=ok/partial/unavailable` | 大盘红绿灯 | `partial` 可映射，`unavailable` 视字段场景映射到 `missing` 或 `not_supported` | P0 不把大盘红绿灯纳入首版单股 pack。 |
| `fetch_failed` | 数据质量细分 | P5 映射为 `fetch_failed` | 只在已有 artifact 明确失败时使用，不代表整次分析失败。 |

## 七路径盘点

### 普通分析

普通分析主链路在 `src/core/pipeline.py` 中组装输入：先读取 `storage.get_analysis_context()`，再按可用性补充实时行情、筹码、趋势分析、新闻、基本面和报告语言，最后交给 `src/analyzer.py` 渲染 prompt。当前重复点主要是实时字段同时存在于 `enhanced_context.realtime`、`realtime_quote_raw` 和报告 meta；命名上存在 `source`、`data_source`、`realtime_source` 等多种来源字段。

首版 pack 可从普通分析路径抽取单股核心身份、行情、日线、技术、新闻、基本面和数据质量摘要；P0 不改变 `_enhance_context()`、`_build_context_snapshot()` 或 analyzer prompt。

### Agent

Agent 有三层需要分开记录的数据面。`src/core/pipeline.py` 的 Agent 路径会构造 `initial_context`，固定包含 `fundamental_context`，并在可用时加入 `trend_result`，最终作为 Agent 路径的 `context_snapshot` 持久化。`AgentExecutor._build_user_message()` 只适用于 `AGENT_ARCH=single`，首轮消息只显式注入 `realtime_quote`、`chip_distribution`、`news_context` 等已取上下文，不显式注入 `fundamental_context` 或 `trend_result`。`AgentOrchestrator._build_context()` 适用于 `AGENT_ARCH=multi`，可预注入 `realtime_quote`、`daily_history`、`chip_distribution`、`trend_result`、`news_context`，这些进入 `AgentContext` 的字段会作为 pre-fetched data 注入 stage agent 消息；但 orchestrator 不预注入 `fundamental_context`。`trend_result` 不是天然存在，取决于 caller 是否传入。

Agent 工具还会独立调用 `get_realtime_quote`、`get_daily_history`、`get_chip_distribution`、`get_analysis_context`、`get_stock_info` 等工具，容易与普通分析前置获取产生重复请求。当前 pack 生成只在 Agent 历史预取后复用 `storage.get_analysis_context()` 的日线可用性状态，不复用或暴露完整工具级 pack cache；P5 再决定是否做更深的数据质量评分与工具缓存复用。

### 告警

告警链路在 `src/services/alert_worker.py` 中评估规则、记录触发历史并分发通知，具体字段语义见 [实时告警中心](alerts.md)。告警状态如 `triggered`、`skipped`、`degraded`、`failed` 是规则评估或记录状态，不能直接写入字段质量枚举。

首版 pack 不把告警规则评估作为输入数据块；告警后续只消费 pack 的字段质量摘要，例如核心行情是否 fallback、是否 stale、是否 partial。

### 持仓

持仓快照在 `src/services/portfolio_service.py` 中聚合账户、仓位、成本、价格、汇率和风险输入，API 输出结构在 `api/v1/schemas/portfolio.py`。当前已有 `price_source`、`price_provider`、`price_date`、`price_stale`、`price_available`、`fx_stale` 等字段。

首版 pack 可记录“是否持仓、账户摘要、成本、数量、仓位、浮盈浮亏、价格/汇率 stale 摘要”，但不纳入交易流水、现金流水、公司行动或完整账户隐私数据。

### 回测

回测服务在 `src/services/backtest_service.py` 和 `src/repositories/backtest_repo.py` 中消费历史分析记录与日线数据。现有 `parse_analysis_date_from_snapshot()` 依赖 `analysis_history.context_snapshot.enhanced_context.date` 解析分析日期。

P0 必须把 `enhanced_context.date` 标为兼容边界。后续 pack 可以新增更清晰的日期字段，但不能无迁移地删除或改名当前历史快照中的日期位置。

### 历史

历史详情在 `src/services/history_service.py`、`api/v1/endpoints/history.py`、`api/v1/schemas/history.py` 中返回 `raw_result`、`news_content`、`context_snapshot` 等字段。同步 analysis/status 响应也会在 `api/v1/endpoints/analysis.py` 中读取 `context_snapshot.enhanced_context`、`realtime_quote_raw` 和基本面 fallback。

P0 只记录历史消费面。完整 pack 不应默认公开到历史详情或公共 API；后续 P4 如需展示，应优先暴露摘要、来源和降级说明。

### 通知

通知链路在 `src/notification.py` 中消费 `AnalysisResult`、dashboard、market snapshot、data_sources 等输出，并记录 `sent`、`no_channel`、`partial_failed`、`all_failed` 等投递状态；渠道配置与边界见 [通知能力基线](notifications.md)。

通知不是事实数据层，不能把投递失败误写成输入质量失败。后续只应在必要时消费 pack 摘要，例如“实时行情已降级”“基本面缺失”“新闻源不足”。

## 源码锚点

| 域 | 锚点 |
| --- | --- |
| 普通分析 | `src/core/pipeline.py`, `src/storage.py`, `src/analyzer.py` |
| Agent | `src/agent/orchestrator.py`, `src/agent/executor.py`, `src/agent/tools/data_tools.py` |
| 告警 | `src/services/alert_worker.py`, `docs/alerts.md` |
| 持仓 | `src/services/portfolio_service.py`, `api/v1/schemas/portfolio.py` |
| 回测 | `src/services/backtest_service.py`, `src/repositories/backtest_repo.py` |
| 历史 | `src/services/history_service.py`, `api/v1/endpoints/history.py`, `api/v1/endpoints/analysis.py`, `api/v1/schemas/history.py` |
| 通知 | `src/notification.py`, `docs/notifications.md` |

## 兼容与安全边界

- `analysis_history.context_snapshot.enhanced_context.date` 是当前回测日期解析兼容点，P1/P2 不能在没有迁移的情况下破坏。
- 完整 pack 不默认公开到历史、API、Web 或通知；P4/P5 只公开 `analysis_context_pack_overview` 低敏摘要、来源、fallback、stale、missing reason、block status count 和 `data_quality` 低敏评分。
- pack、日志、历史快照和 API 响应不得记录 API key、token、cookie、完整 webhook URL、邮箱密码、私有环境变量或其他密钥。
- `source`、`timestamp`、`fallback`、`stale`、`partial` 等质量元数据只用于解释输入限制，不用于阻断分析；除非现有核心路径本来就是 fail-fast。
- #1386 的盘前 / 盘中 phase 感知是后续 `phase` / `data_quality` 字段的重要背景；P0 只记录关系，不接入 runtime。
