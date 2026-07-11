# -*- coding: utf-8 -*-
"""Contract checks for the alert-center documentation."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "alerts.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_alerts_doc_exists_and_links_p0_scope() -> None:
    doc = _read_doc()

    assert "Issue #1202" in doc
    assert "AGENT_EVENT_ALERT_RULES_JSON" in doc
    assert "EventMonitor" in doc
    assert "P1 Alert API MVP" in doc
    assert "P0 不做" in doc


def test_alerts_doc_covers_legacy_runtime_rules() -> None:
    doc = _read_doc()

    for token in ("price_cross", "price_change_percent", "volume_spike"):
        assert token in doc
    for token in ("sentiment_shift", "risk_flag", "custom"):
        assert token in doc


def test_alerts_doc_defines_required_contract_entities() -> None:
    doc = _read_doc()

    required_sections = (
        "### `alert_rule`",
        "### `alert_trigger`",
        "### `alert_notification`",
        "### `alert_cooldown`",
    )
    for section in required_sections:
        assert section in doc

    required_fields = (
        "target_scope",
        "parameters",
        "cooldown_policy",
        "notification_policy",
        "observed_value",
        "data_timestamp",
        "trigger_id",
        "latency_ms",
        "cooldown_until",
    )
    for field_name in required_fields:
        assert field_name in doc


def test_alerts_doc_covers_storage_evaluation_and_rollback() -> None:
    doc = _read_doc()

    assert (PROJECT_ROOT / "src" / "storage.py").is_file()

    for token in (
        "## 存储方案评估",
        "src/storage.py",
        "src/repositories/",
        "src/services/",
        "data/stock_analysis.db",
        "幂等初始化",
        "回滚说明",
    ):
        assert token in doc


def test_alerts_doc_keeps_p0_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "P0 阶段不新增 `api/v1/schemas/alerts.py`",
        "P0 阶段不新增 Web 告警中心页面",
        "P0 阶段不新增数据库表",
        "P0 阶段不实现触发历史",
        "P0 阶段不自动迁移、删除或覆盖 `AGENT_EVENT_ALERT_RULES_JSON`",
        "P0 阶段不重写 `NotificationService`",
    ):
        assert token in doc


def test_alerts_doc_defines_p1_api_mvp_scope() -> None:
    doc = _read_doc()

    for token in (
        "api/v1/endpoints/alerts.py",
        "api/v1/schemas/alerts.py",
        "GET /api/v1/alerts/rules",
        "POST /api/v1/alerts/rules",
        "GET /api/v1/alerts/rules/{rule_id}",
        "PATCH /api/v1/alerts/rules/{rule_id}",
        "DELETE /api/v1/alerts/rules/{rule_id}",
        "POST /api/v1/alerts/rules/{rule_id}/enable",
        "POST /api/v1/alerts/rules/{rule_id}/disable",
        "POST /api/v1/alerts/rules/{rule_id}/test",
        "GET /api/v1/alerts/triggers",
        "GET /api/v1/alerts/notifications",
        "price_cross",
        "price_change_percent",
        "volume_spike",
        "unsupported",
        "脱敏",
        "保留字段",
        "不执行冷却或自定义通知语义",
    ):
        assert token in doc


def test_alerts_doc_keeps_p1_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "不新增 Web 告警中心页面",
        "不让 schedule worker 加载持久化 active rules",
        "不实现真实 `alert_trigger` / `alert_notification` 写入",
        "不实现 `alert_cooldown` 执行语义",
        "不实现 MACD、KDJ、CCI、RSI",
        "不自动迁移、删除、覆盖或改写 legacy 配置",
    ):
        assert token in doc


def test_alerts_doc_defines_p2_worker_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P2 告警评估 Worker",
        "src/services/alert_worker.py",
        "agent_event_monitor",
        "持久化 active rules",
        "legacy JSON",
        "`triggered`、`skipped`、`degraded`、`failed`",
        "不写 `alert_notifications`",
        "不执行 `cooldown_policy`",
    ):
        assert token in doc


def test_alerts_doc_describes_p1_rollback_for_created_tables() -> None:
    doc = _read_doc()

    for token in (
        "P1 新增 Alert API 代码",
        "`alert_rules` / `alert_triggers` / `alert_notifications` SQLite 表",
        "Base.metadata.create_all()",
        "SQLite 表与数据不会自动删除",
        "手动删除相关表",
    ):
        assert token in doc


def test_alerts_doc_defines_p4_notification_and_cooldown_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P4 通知结果与持久化冷却",
        "`alert_cooldowns`",
        "`alert_notifications`",
        "`rule_id + target + data_source + data_timestamp`",
        "同一数据点去重",
        "`data_timestamp` 缺失时不做去重",
        "`__cooldown__`",
        "`__cooldown_read_failed__`",
        "`__noise_suppressed__`",
        "notification_noise.py",
        "DB 持久化规则正常路径使用 `alert_cooldowns`",
        "读取持久化冷却状态失败",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 规则继续使用 worker 进程内 fingerprint",
        "不会写入或延长 `alert_cooldowns`",
        "最小回滚方式是 revert P4 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p5_indicator_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P5 技术指标规则",
        "ma_price_cross",
        "rsi_threshold",
        "macd_cross",
        "kdj_cross",
        "cci_threshold",
        "compute_required_bars",
        "requested_days",
        "required_bars > 365",
        "最近两根已收盘日线",
        "prev <= threshold < current",
        "Wilder",
        "SMMA",
        "alpha=1/period",
        "EMA(fast_period)",
        "alpha=1/k_period",
        "0.015 * mean_deviation",
        "服务器本地时区启发式",
        "16:00",
        "日期不可判定都会保守丢弃",
        "legacy JSON 路径",
        "不扩展 `src/agent/events.py`",
        "HTTP 400 + `validation_error`",
        "HTTP 400 + `unsupported_alert_type`",
        "不支持 MACD 柱体放大/收缩",
        "不支持 KDJ 超买/超卖区规则",
        "不支持 MA 与 MA 双均线交叉",
        "不支持分钟线",
        "revert P5 PR",
        "skip unsupported `alert_type`",
    ):
        assert token in doc


def test_alerts_doc_defines_p6_portfolio_and_watchlist_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P6 持仓与自选股联动",
        "P6 scope/type 矩阵",
        "`watchlist`",
        "`portfolio_holdings`",
        "`portfolio_account`",
        "`portfolio_stop_loss`",
        "`portfolio_concentration`",
        "`portfolio_drawdown`",
        "`portfolio_price_stale`",
        "Target Identity Contract",
        "`effective_target`",
        "`RuntimeAlertRule.key`",
        "`{parent_key}|{effective_target}`",
        "dry-run",
        "`degraded_count`",
        "soft cap",
        "cooldown_active",
        "父规则摘要",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 watchlist、portfolio",
        "sector 级集中度",
        "P6 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p7_market_light_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P7 大盘红绿灯结构化告警",
        "MarketLightSnapshot",
        "`target_scope=market`",
        "`market_light_status`",
        "`market_light_score_drop`",
        "`statuses=[\"red\",\"yellow\"]`",
        "`min_drop > 0`",
        "`cn` / `hk` / `us`",
        "双向约束",
        "`context_snapshot.market_light_snapshots`",
        "`data_quality=unavailable`",
        "`partial_comparison=true`",
        "`missing_dimensions`",
        "canonical scorer",
        "thin wrapper",
        "`load_previous_snapshot(region, before_trade_date)`",
        "最大 `snapshot.trade_date`",
        "旧交易日 backfill",
        "`TRADING_DAY_CHECK_ENABLED`",
        "`data_source=market_light`",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON` 不支持 market 规则",
        "revert P7 PR",
    ):
        assert token in doc


def test_alerts_doc_covers_issue_1386_p7_user_visibility_boundary() -> None:
    doc = _read_doc()
    p7_section = doc.split("#1386 P7 的用户边界：", 1)[1].split(
        "\n\n回滚本联动",
        1,
    )[0]

    for token in (
        "触发时已经可公开的阶段和数据质量摘要",
        "不会自动发起轻量 LLM 盘中分析",
        "不会新增告警表、规则类型、环境变量或 migration",
        "分析 API / Web 手动分析入口",
        "告警通知只保留阶段标签、trigger source、partial-bar warning、数据质量等级和前两条 limitations",
    ):
        assert token in p7_section


def test_alerts_doc_defines_p8_user_and_deployment_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "## P8 用户配置与部署边界",
        "`AGENT_EVENT_MONITOR_ENABLED`",
        "`AGENT_EVENT_MONITOR_INTERVAL_MINUTES`",
        "`NOTIFICATION_ALERT_CHANNELS`",
        "`route_type=alert`",
        "Alert API / Web 告警中心持久化规则",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON`",
        "只兼容 `single_symbol`",
        "P5 技术指标、P6 watchlist/portfolio 或 P7 market light",
        "docker/Dockerfile",
        "`python main.py --schedule`",
        "保留 `data/` 数据库卷",
        ".github/workflows/00-daily-analysis.yml",
        "一次性分析 workflow",
        "不运行 `--schedule` 后台 alert worker",
        "没有映射 `AGENT_EVENT_*`",
        "`/alerts`",
        "Desktop 不新增原生告警管理界面",
        "`triggered`、`skipped`、`degraded`、`failed`",
        "`rule_id + target + data_source + data_timestamp`",
        "回滚 P8 只需 revert 文档、配置说明和 Web 文案改动",
    ):
        assert token in doc


def test_changelog_mentions_alert_p6_release_note() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "P6" in changelog
    assert "自选股" in changelog
    assert "持仓" in changelog
    assert "账户联动规则" in changelog


def test_changelog_mentions_alert_p8_docs_closeout() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "补齐告警中心 P8 文档与配置收口说明" in changelog
    assert "GitHub Actions 与 Desktop 边界" in changelog


def test_changelog_unreleased_keeps_flat_entries() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]

    assert "\n### " not in unreleased
