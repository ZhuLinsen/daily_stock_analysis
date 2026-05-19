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
