# -*- coding: utf-8 -*-
"""Contract checks for the AnalysisContextPack P0/P1 contract doc."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "analysis-context-pack.md"
FULL_GUIDE_PATH = PROJECT_ROOT / "docs" / "full-guide.md"
FULL_GUIDE_EN_PATH = PROJECT_ROOT / "docs" / "full-guide_EN.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section(doc: str, heading: str) -> str:
    marker = f"## {heading}"
    assert marker in doc
    return doc.split(marker, 1)[1].split("\n## ", 1)[0]


def test_analysis_context_pack_doc_has_required_sections() -> None:
    doc = _read_doc()

    for heading in (
        "## 术语与边界",
        "## P0 范围与非目标",
        "## P1 内部契约",
        "## P2 Builder 契约",
        "## P3 Runtime Consumption",
        "## P4 历史记录、任务状态与 Web 可见性",
        "## P5 数据质量评分与 Prompt 数据限制",
        "## P6 文档、迁移与回滚",
        "## 字段质量状态",
        "## 现有状态映射",
        "## 七路径盘点",
        "## 源码锚点",
        "## 兼容与安全边界",
    ):
        assert heading in doc


def test_analysis_context_pack_doc_disambiguates_context_surfaces() -> None:
    section = _section(_read_doc(), "术语与边界")

    for token in (
        "`storage.get_analysis_context()`",
        "`enhanced_context`",
        "`analysis_history.context_snapshot`",
        "Agent executor message context",
        "Agent orchestrator `AgentContext`",
        "`AGENT_ARCH=single`",
        "`AGENT_ARCH=multi`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p0_quality_states() -> None:
    section = _section(_read_doc(), "字段质量状态")

    for state in (
        "`available`",
        "`missing`",
        "`not_supported`",
        "`fallback`",
        "`stale`",
        "`estimated`",
        "`partial`",
        "`fetch_failed`",
    ):
        assert state in section
    assert "P0 先固定七词" in section
    assert "P5 在同一 1.0 umbrella 内追加 `fetch_failed`" in section


def test_analysis_context_pack_doc_covers_seven_paths() -> None:
    section = _section(_read_doc(), "七路径盘点")

    for heading in (
        "### 普通分析",
        "### Agent",
        "### 告警",
        "### 持仓",
        "### 回测",
        "### 历史",
        "### 通知",
    ):
        assert heading in section


def test_analysis_context_pack_doc_records_agent_context_visibility() -> None:
    section = _section(_read_doc(), "七路径盘点")

    for token in (
        "`initial_context`",
        "`fundamental_context`",
        "不显式注入 `fundamental_context` 或 `trend_result`",
        "pre-fetched data",
        "不预注入 `fundamental_context`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_non_goals_and_safety_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "P1 已新增 `AnalysisContextPack` 内部 schema",
        "不新增 builder",
        "不接入 runtime",
        "不公开完整 pack",
        "不 pack 化 `market_review`",
        "`market_light`",
        "P5 已在同一 1.0 umbrella 内追加该状态",
        "`analysis_history.context_snapshot.enhanced_context.date`",
        "完整 pack 不默认公开",
        "API key",
        "token",
        "cookie",
        "完整 webhook URL",
        "邮箱密码",
    ):
        assert token in doc


def test_analysis_context_pack_doc_defines_p1_schema_contract() -> None:
    section = _section(_read_doc(), "P1 内部契约")

    for token in (
        "`src/schemas/analysis_context_pack.py`",
        "`PACK_VERSION = \"1.0\"`",
        "`ContextFieldStatus`",
        "`AnalysisSubject`",
        "`AnalysisContextItem`",
        "`AnalysisContextBlock`",
        "`DataQuality`",
        "`AnalysisContextPack`",
        "`MarketPhaseContext.to_dict()`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_block_catalog() -> None:
    section = _section(_read_doc(), "P1 内部契约")

    for token in (
        "P1 Block Catalog",
        "`quote`",
        "`daily_bars`",
        "`technical`",
        "`fundamentals`",
        "`news`",
        "`portfolio`",
        "`chip` / `capital_flow`",
        "`events` / `market_context`",
        "不重复新增 `identity` block",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_time_and_status_semantics() -> None:
    section = _section(_read_doc(), "P1 内部契约")

    for token in (
        "`AnalysisContextPack.created_at` 使用 `datetime`",
        "`model_dump(mode=\"json\")` 输出 ISO 8601",
        "`AnalysisContextItem.timestamp`",
        "`AnalysisContextBlock.timestamp`",
        "Optional[str]",
        "构造时校验",
        "date-only",
        "`block.status` 表示整块可用性",
        "`item.status` 表示字段级质量",
        "不实现 `item.status` 到 `block.status` 的自动聚合推导",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_redaction_contract() -> None:
    section = _section(_read_doc(), "P1 内部契约")

    for token in (
        "`AnalysisContextPack.to_safe_dict()`",
        "`redact_sensitive_mapping()`",
        "`api_key`",
        "`access_token`",
        "`authorization_header`",
        "`webhook_url`",
        "`license_key`",
        "[REDACTED]",
        "`data_api`",
        "不扫描普通字符串值",
        "不做 URL 正则脱敏",
    ):
        assert token in section


def test_analysis_context_pack_doc_keeps_later_phases_out_of_p1() -> None:
    section = _section(_read_doc(), "P1 内部契约")

    for token in (
        "不填充运行时数据",
        "不新增 fetcher",
        "不改变 Prompt",
        "不写入 history/task/report metadata",
        "不把完整 pack 暴露到 API、Web、Bot、Desktop 或通知",
        "P2 builder",
        "P3 runtime",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p2_builder_boundaries() -> None:
    section = _section(_read_doc(), "P2 Builder 契约")

    for token in (
        "`AnalysisContextBuilder`",
        "assembler",
        "pipeline 已 fetch",
        "zero-fetch",
        "`PipelineAnalysisArtifacts`",
        "`code`、`stock_name`、`market`",
        "`price_stale`",
        "`quote_stale`",
        "`intraday_realtime_overlay`",
        "`fetch_failed`",
        "P3 runtime",
        "不改变 Prompt",
        "不写入 history/task/report metadata",
    ):
        assert token in section


def test_analysis_context_pack_docs_record_issue_1386_p3_quality_boundaries() -> None:
    section = _section(_read_doc(), "P2 Builder 契约")

    for token in (
        "`fetched_at`",
        "`provider_timestamp`",
        "`is_stale`",
        "`stale_seconds`",
        "`fallback_from`",
        "`STALE > FALLBACK > AVAILABLE`",
        "builder 只映射上游 artifact，不做质量评分",
        "`is_partial_bar`、`is_estimated`、`estimated_fields`",
        "`daily_bars` 不承载 partial/estimated",
    ):
        assert token in section

    full_guide = FULL_GUIDE_PATH.read_text(encoding="utf-8")
    full_guide_en = FULL_GUIDE_EN_PATH.read_text(encoding="utf-8")
    assert "盘中数据包与实时质量控制（Issue #1386 P3）" in full_guide
    assert "source` 保留实际成功的数据源 token" in full_guide
    assert "`AnalysisContextBuilder` 只映射这些上游 artifact" in full_guide
    assert "daily_bars` block 仍表示 storage 中完整日线窗口" in full_guide
    assert "Intraday Data Packet and Realtime Quality Control (Issue #1386 P3)" in full_guide_en
    assert "source` keeps the actual successful provider token" in full_guide_en


def test_analysis_context_pack_doc_defines_p3_runtime_consumption_boundaries() -> None:
    section = _section(_read_doc(), "P3 Runtime Consumption")

    for token in (
        "`StockAnalysisPipeline` 是 summary 的唯一生产者",
        "`PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()`",
        "`format_analysis_context_pack_prompt_section()`",
        "`analysis_context_pack_summary`",
        "基础信息 -> #1386 `market_phase_context` 渲染区块 -> `analysis_context_pack_summary`",
        "`news.content`、`trend_result`、`chip`、`fundamental_context` 等原始 payload",
        "`AgentExecutor._build_user_message()`",
        "`AgentOrchestrator._build_context()`",
        "`ctx.meta[\"analysis_context_pack_summary\"]`",
        "禁止写入 `ctx.data`",
        "`BaseAgent._build_messages()`",
        "`_inject_cached_data()`",
        "`news` block 为 `missing` 是当前 P3 的预期状态",
        "`analysis_history.context_snapshot`",
        "`analysis_context_pack`",
        "`analysis_context_pack_summary`",
        "Agent 工具级 pack cache 复用",
        "P4 在此基础上新增低敏 overview",
        "P5 继续复用 summary 消费路径",
    ):
        assert token in section

    assert "P3-min" not in section


def test_analysis_context_pack_doc_defines_p4_visibility_contract() -> None:
    section = _section(_read_doc(), "P4 历史记录、任务状态与 Web 可见性")

    for token in (
        "`analysis_context_pack_overview`",
        "专用 renderer",
        "`AnalysisContextPack.to_safe_dict()`",
        "`report.details.analysis_context_pack_overview`",
        "`analysisContextPackOverview`",
        "`GET /api/v1/history/{record_id}`",
        "同步 `POST /api/v1/analysis/analyze`",
        "overview 依赖已持久化的 `analysis_history.context_snapshot`",
        "completed `GET /api/v1/analysis/status/{task_id}`",
        "`sanitize_context_snapshot_for_api()`",
        "`extract_analysis_context_pack_overview()`",
        "`items.value`",
        "`trend_result`",
        "`fundamental_context`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "不持久化整份 `analysis_history.context_snapshot`",
        "`market_phase_summary`",
        "`enhanced_context`",
        "`AnalysisContextSummary`",
        "位置在策略点位和资讯之后、运行诊断之前",
        "默认折叠",
        "非零的其他状态计数",
        "不覆盖 pending/processing TaskPanel",
        "不改通知摘要",
        "质量分/等级",
        "`fetch_failed` 状态",
    ):
        assert token in section

    assert "运行诊断之后、策略点位之前" not in section


def test_analysis_context_pack_doc_defines_p5_data_quality_contract() -> None:
    section = _section(_read_doc(), "P5 数据质量评分与 Prompt 数据限制")

    for token in (
        "`PACK_VERSION`",
        "`fetch_failed`",
        "`fundamental_context.status == \"failed\"`",
        "`overall_score`",
        "`level`",
        "`block_scores`",
        "`limitations`",
        "`quote=25`",
        "`fetch_failed=25`",
        "`Data Limitations`",
        "`confidence_level` 不得为 `高` / `High`",
        "`phase × degraded data`",
        "fail-open",
        "不替代 P5 的 confidence/safety 规则",
        "`analysis_context_pack_overview.data_quality`",
        "`details.context_snapshot`",
        "不新增 fetcher",
        "不改变 LLM 输出 JSON schema",
        "`dashboard.phase_decision`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p6_migration_and_rollback_contract() -> None:
    section = _section(_read_doc(), "P6 文档、迁移与回滚")

    for token in (
        "四个数据面",
        "内部完整 pack",
        "`analysis_context_pack_summary`",
        "`analysis_context_pack_overview`",
        "`analysis_history.context_snapshot`",
        "摘要可见性矩阵",
        "`SAVE_CONTEXT_SNAPSHOT=true`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "`--no-context-snapshot`",
        "不持久化整份 `analysis_history.context_snapshot`",
        "本次历史已持久化 `analysis_history.context_snapshot`",
        "`enhanced_context`",
        "`market_phase_summary`",
        "`diagnostics`",
        "`realtime_quote_raw`",
        "不影响当次 `AnalysisContextPack` 构建",
        "不影响内存中的 `result.diagnostic_context_snapshot`",
        "当前不存在",
        "运行时 pack 总开关",
        "发布或代码回滚",
        "secret",
        "token",
        "webhook",
    ):
        assert token in section


def test_analysis_context_pack_doc_maps_existing_status_terms() -> None:
    section = _section(_read_doc(), "现有状态映射")

    for token in (
        "`degraded`",
        "`insufficient_data`",
        "`partial_failed`",
        "`data_missing`",
        "`price_stale`",
        "`data_quality=ok/partial/unavailable`",
        "不映射",
    ):
        assert token in section


def test_analysis_context_pack_doc_lists_source_anchors() -> None:
    section = _section(_read_doc(), "源码锚点")

    for path in (
        "src/core/pipeline.py",
        "src/storage.py",
        "src/analyzer.py",
        "src/agent/orchestrator.py",
        "src/agent/executor.py",
        "src/agent/tools/data_tools.py",
        "src/services/alert_worker.py",
        "src/services/portfolio_service.py",
        "src/services/backtest_service.py",
        "src/repositories/backtest_repo.py",
        "src/services/history_service.py",
        "api/v1/endpoints/history.py",
        "api/v1/endpoints/analysis.py",
        "api/v1/schemas/history.py",
        "api/v1/schemas/portfolio.py",
        "src/notification.py",
        "docs/alerts.md",
        "docs/notifications.md",
    ):
        assert path in section


def test_analysis_context_pack_doc_updates_indexes_and_changelog() -> None:
    index = (PROJECT_ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    index_en = (PROJECT_ROOT / "docs" / "INDEX_EN.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "[分析上下文包契约、运行态消费与可见性](analysis-context-pack.md)" in index
    assert "P1/P2 内部契约、P3 Prompt 摘要消费、P4 历史/API/Web 低敏可见性、P5 数据质量评分、P6 迁移回滚" in index
    assert "#1386 阶段感知分析、迁移与回滚入口" in index
    assert (
        "[Analysis Context Pack Contract, Runtime Consumption, And Visibility](analysis-context-pack.md) "
        "<sub><sub>![P6 Badge](https://img.shields.io/badge/P6-orange?style=flat)</sub></sub> "
        "(Chinese-only)"
    ) in index_en
    assert "P1/P2 internal contracts, P3 prompt-summary consumption, P4 history/API/Web low-sensitivity visibility, P5 data-quality scoring, and P6 migration/rollback notes" in index_en
    assert "#1386 market-phase analysis, migration, and rollback entry points" in index_en
    assert "新增 AnalysisContextPack P0 上下文盘点" in changelog
    assert "新增 AnalysisContextPack P1 内部契约与脱敏序列化测试" in changelog
    assert "新增 AnalysisContextPack P2 builder" in changelog
    assert "普通分析与 Agent 运行时 Prompt 接入 AnalysisContextPack 低敏摘要" in changelog
    assert "AnalysisContextPack P4 低敏 overview 接入历史详情" in changelog
    assert "AnalysisContextPack P5 增加数据质量评分" in changelog
    assert "明确 AnalysisContextPack P6 文档、迁移与回滚边界" in changelog
    assert "#1386 P7 盘前/盘中/盘后分析的入口、迁移、回滚和用户可见说明" in changelog
    assert "#1386 P5 为个股分析报告新增 `dashboard.phase_decision`" in changelog
    assert "优化 Web 报告详情页信息层级" in changelog


def test_full_guides_cover_issue_1386_p7_user_migration_closeout() -> None:
    guide = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")
    guide_en = (PROJECT_ROOT / "docs" / "full-guide_EN.md").read_text(encoding="utf-8")

    for token in (
        "文档、配置与迁移说明（Issue #1386 P7）",
        "盘前 / 盘中 / 盘后分析",
        "生成开盘计划和观察条件",
        "盘中 / 午间 / 临近收盘",
        "做实时状态判断、风险和机会提醒",
        "`analysis_phase=auto|premarket|intraday|postmarket`",
        "最终报告阶段仍以 `report.meta.market_phase_summary.phase` 为准",
        "Web 主分析 / 重新分析 / 持仓手动分析",
        "当前没有阶段覆盖 selector",
        "进行中任务面板展示请求阶段",
        "最终报告页展示最终阶段标签",
        "Bot / CLI / schedule / 默认 GitHub Actions",
        "只消费公开 `market_phase_summary` 和低敏 `analysis_context_pack_overview`",
        "不公开完整 pack、Prompt summary、新闻正文或持仓敏感明细",
        "旧调用不传 `analysis_phase` 时保持兼容",
        "回测查询支持 `analysis_phase=premarket|intraday|postmarket|unknown`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "不关闭当次 `AnalysisContextPack` 构建",
        "低敏 `analysis_context_pack_summary`",
        "`analysis_phase=postmarket`",
        "需要发布回滚或代码回滚",
    ):
        assert token in guide

    for token in (
        "Documentation, Configuration, And Migration Notes (Issue #1386 P7)",
        "pre-market / intraday / post-market analysis",
        "opening plan and watch conditions",
        "Intraday / lunch break / near close",
        "live state, risk, and opportunity alerts",
        "`analysis_phase=auto|premarket|intraday|postmarket`",
        "final report phase remains `report.meta.market_phase_summary.phase`",
        "Web main analysis / re-analysis / portfolio manual analysis",
        "no phase override selector",
        "the in-progress task panel shows the requested phase",
        "the final report page shows the final phase label",
        "Bot / CLI / schedule / default GitHub Actions",
        "Only consume public `market_phase_summary` and low-sensitivity `analysis_context_pack_overview`",
        "do not expose the full pack, prompt summary, news body text, or sensitive portfolio details",
        "Older callers that omit `analysis_phase` remain compatible",
        "Backtest queries support `analysis_phase=premarket|intraday|postmarket|unknown`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "does not disable current-run `AnalysisContextPack` construction",
        "low-sensitivity `analysis_context_pack_summary`",
        "`analysis_phase=postmarket`",
        "requires a release rollback or code rollback",
    ):
        assert token in guide_en


def test_full_guides_clarify_pack_summary_does_not_replace_legacy_payload_channels() -> None:
    guide = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")
    guide_en = (PROJECT_ROOT / "docs" / "full-guide_EN.md").read_text(encoding="utf-8")

    assert "在这个新增的 pack 摘要区块中" in guide
    assert "不会通过该区块看到完整 `news.content`" in guide
    assert "既有 `news_context`、Agent pre-fetched JSON 和 `enhanced_context` 原始数据通道保持 P3 前行为" in guide
    assert "`report.details.analysis_context_pack_overview`" in guide
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide
    assert "Web 端报告页在“策略点位”和“资讯”之后展示默认折叠的数据块摘要" in guide
    assert "折叠头部展示可用数、缺失数、非零的其他状态计数和触发来源" in guide
    assert "Web 报告页在策略点位和资讯之后默认折叠展示数据块状态" in guide
    assert "`details.context_snapshot` 会剥离顶层 `analysis_context_pack_overview`" in guide
    assert "同步分析响应也会读取本次已落库的 `analysis_history.context_snapshot` 提取 overview" in guide
    assert "`SAVE_CONTEXT_SNAPSHOT=false` 时新记录不保证返回该字段" in guide
    assert "AnalysisContextPack 数据质量评分与 Prompt 数据限制（Issue #1389 P5）" in guide
    assert "盘中决策护栏与质量校验（Issue #1386 P5）" in guide
    assert "`dashboard.phase_decision`" in guide
    assert "`fetch_failed`" in guide
    assert "折叠头部新增质量分/等级" in guide
    assert "`report.meta.market_phase_summary`" in guide
    assert "`details.context_snapshot` 会剥离顶层 `market_phase_summary`" in guide
    assert "AnalysisContextPack 文档、迁移与回滚（Issue #1389 P6）" in guide
    assert "`SAVE_CONTEXT_SNAPSHOT` 是既有环境变量" in guide
    assert "不持久化整份 `analysis_history.context_snapshot`" in guide
    assert "不关闭当次 `AnalysisContextPack` 构建" in guide
    assert "当前没有运行时 pack 总开关" in guide

    assert "in this new pack-summary section" in guide_en
    assert "not full `news.content`" in guide_en
    assert "Existing `news_context`, Agent pre-fetched JSON, and `enhanced_context` raw-payload channels keep their pre-P3 behavior" in guide_en
    assert "`report.details.analysis_context_pack_overview`" in guide_en
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide_en
    assert "The Web report page renders a collapsed data-block summary after Strategy and News" in guide_en
    assert "available/missing counts, non-zero other status counts, and trigger source" in guide_en
    assert "the Web report page shows the data-block summary collapsed after Strategy and News" in guide_en
    assert "API `details.context_snapshot` strips the top-level `analysis_context_pack_overview`" in guide_en
    assert "sync analysis responses also extract the overview from the just-persisted `analysis_history.context_snapshot`" in guide_en
    assert "new records do not guarantee this field when `SAVE_CONTEXT_SNAPSHOT=false`" in guide_en
    assert "AnalysisContextPack Data Quality Scoring and Prompt Limitations (Issue #1389 P5)" in guide_en
    assert "Intraday Decision Guardrails and Quality Checks (Issue #1386 P5)" in guide_en
    assert "`dashboard.phase_decision`" in guide_en
    assert "`fetch_failed`" in guide_en
    assert "adds quality score/level to the header" in guide_en
    assert "`report.meta.market_phase_summary`" in guide_en
    assert "API `details.context_snapshot` strips the top-level `market_phase_summary`" in guide_en
    assert "AnalysisContextPack Documentation, Migration, and Rollback (Issue #1389 P6)" in guide_en
    assert "`SAVE_CONTEXT_SNAPSHOT` is an existing environment variable" in guide_en
    assert "the full `analysis_history.context_snapshot` is not persisted" in guide_en
    assert "does not disable current-run `AnalysisContextPack` construction" in guide_en
    assert "There is no runtime pack master switch" in guide_en
