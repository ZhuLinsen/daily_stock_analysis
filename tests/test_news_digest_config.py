# -*- coding: utf-8 -*-
"""Wave 2 配置面用例（issue #2184）：7 键三件套 + env 解析语义（计划 D9）。

约定（计划 Wave 2 全局测试约定）：凡读写 ``NEWS_DIGEST_*`` 配置的用例，先
``monkeypatch.delenv/setenv`` 再 ``Config.reset_instance()``，用例结束再次
``reset_instance()``；时间相关断言一律注入固定 datetime。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from src.config import Config
from src.core.config_registry import get_field_definition, get_registered_field_keys
from src.services.news_digest_service import parse_news_digest_topics

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
SETTINGS_HELP_PATH = REPO_ROOT / "apps" / "dsa-web" / "src" / "locales" / "settingsHelp.ts"

NEWS_DIGEST_HELP_KEY = "settings.system.news_digest"

# D9 表：env 键 → config 字段
NEWS_DIGEST_ENV_TO_FIELD = {
    "NEWS_DIGEST_ENABLED": "news_digest_enabled",
    "NEWS_DIGEST_PREMARKET_WINDOW": "news_digest_premarket_window",
    "NEWS_DIGEST_OFFDAY_WINDOW": "news_digest_offday_window",
    "NEWS_DIGEST_TOPICS": "news_digest_topics",
    "NEWS_DIGEST_MAX_NEWS": "news_digest_max_news",
    "NEWS_DIGEST_INTERVAL_MINUTES": "news_digest_interval_minutes",
    "NEWS_DIGEST_REGION": "news_digest_region",
}

DEFAULT_TOPICS_TEXT = "宏观政策,货币宽松,证监会,外围市场,行业利好"


@pytest.fixture
def news_digest_config(monkeypatch):
    """清空 NEWS_DIGEST_* env → 重置 Config 单例；返回可增量设 env 的工厂。

    工厂每次调用都会重置单例并返回新 Config（首次实例化才读 env）；
    fixture 退出时再次重置，避免污染同进程其他用例。
    """
    for env_key in NEWS_DIGEST_ENV_TO_FIELD:
        monkeypatch.delenv(env_key, raising=False)

    def _apply(**env_values):
        for suffix, value in env_values.items():
            env_key = suffix if suffix.startswith("NEWS_DIGEST_") else f"NEWS_DIGEST_{suffix}"
            monkeypatch.setenv(env_key, str(value))
        Config.reset_instance()
        return Config.get_instance()

    Config.reset_instance()
    yield _apply
    Config.reset_instance()


# ---------------------------------------------------------------------------
# 三件套守门（registry / .env.example / settingsHelp 双语）
# ---------------------------------------------------------------------------


def test_registry_contains_all_seven_keys():
    registered = set(get_registered_field_keys())
    for env_key in NEWS_DIGEST_ENV_TO_FIELD:
        assert env_key in registered, f"registry 缺少 {env_key}"
        definition = get_field_definition(env_key)
        assert definition["category"] == "system", env_key
        assert definition["help_key"] == NEWS_DIGEST_HELP_KEY, env_key
        assert definition["examples"], env_key
        assert definition["docs"], env_key


def test_env_example_keys_registered():
    """解析 .env.example 的 ``^NEWS_DIGEST_`` 活动键 ⊆ registry（三件套守门）。"""
    text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    active_keys = set(re.findall(r"^(NEWS_DIGEST_[A-Z0-9_]+)=", text, flags=re.MULTILINE))
    assert active_keys == set(NEWS_DIGEST_ENV_TO_FIELD), (
        ".env.example 应登记全部 7 键（活动赋值），实际: "
        f"{sorted(active_keys)}"
    )
    registered = set(get_registered_field_keys())
    assert active_keys - registered == set()


def test_settings_help_contract_entries():
    """zh map 与 en map 均含 ``settings.system.news_digest`` 条目。"""
    text = SETTINGS_HELP_PATH.read_text(encoding="utf-8")
    occurrences = re.findall(r"'settings\.system\.news_digest'\s*:", text)
    assert len(occurrences) >= 2, (
        "settingsHelp.ts 的 zh/en map 各需一条 settings.system.news_digest，"
        f"实际出现 {len(occurrences)} 次"
    )


# ---------------------------------------------------------------------------
# config 字段默认值（默认关闭 = 存量行为不变）
# ---------------------------------------------------------------------------


def test_config_defaults_when_unset(news_digest_config):
    config = news_digest_config()
    assert config.news_digest_enabled is False
    assert config.news_digest_premarket_window == "08:00-09:15"
    assert config.news_digest_offday_window == "09:00-18:00"
    assert config.news_digest_topics == DEFAULT_TOPICS_TEXT
    assert config.news_digest_max_news == 12
    assert config.news_digest_interval_minutes == 10
    assert config.news_digest_region == "cn"


# ---------------------------------------------------------------------------
# env 解析语义（D9 表逐格 + R9 边界值）
# ---------------------------------------------------------------------------


def test_config_env_parsing(news_digest_config, caplog):
    # 常规解析：各键 → 正确类型与值
    config = news_digest_config(
        ENABLED="true",
        PREMARKET_WINDOW="07:30-09:00",
        OFFDAY_WINDOW="09:30-17:00",
        TOPICS="a,,b",
        MAX_NEWS="20",
        INTERVAL_MINUTES="3",
        REGION="cn",
    )
    assert config.news_digest_enabled is True
    assert config.news_digest_premarket_window == "07:30-09:00"
    assert config.news_digest_offday_window == "09:30-17:00"
    # config 层只存原始 str；list 解析走服务层 parse_news_digest_topics（D9/MINOR-2）
    assert config.news_digest_topics == "a,,b"
    assert parse_news_digest_topics(config.news_digest_topics) == ["a", "b"]
    assert config.news_digest_max_news == 20
    assert config.news_digest_interval_minutes == 3
    assert config.news_digest_region == "cn"

    # 边界：MAX_NEWS=0 → 默认 12 + warning
    with caplog.at_level(logging.WARNING):
        config = news_digest_config(MAX_NEWS="0")
    assert config.news_digest_max_news == 12
    assert any("NEWS_DIGEST_MAX_NEWS" in record.getMessage() for record in caplog.records)

    # 边界：MAX_NEWS=abc（非数字）→ 默认 12
    config = news_digest_config(MAX_NEWS="abc")
    assert config.news_digest_max_news == 12

    # 钳制：超出上限 30 / 低于下限 4
    config = news_digest_config(MAX_NEWS="99")
    assert config.news_digest_max_news == 30
    config = news_digest_config(MAX_NEWS="1")
    assert config.news_digest_max_news == 4

    # 边界：INTERVAL=0 → 默认 10 + warning
    with caplog.at_level(logging.WARNING):
        config = news_digest_config(INTERVAL_MINUTES="0")
    assert config.news_digest_interval_minutes == 10
    assert any(
        "NEWS_DIGEST_INTERVAL_MINUTES" in record.getMessage() for record in caplog.records
    )

    # 边界：INTERVAL=abc（非数字）→ 默认 10
    config = news_digest_config(INTERVAL_MINUTES="abc")
    assert config.news_digest_interval_minutes == 10

    # 边界：REGION=us → P0 仅 cn，告警后按 cn
    with caplog.at_level(logging.WARNING):
        config = news_digest_config(REGION="us")
    assert config.news_digest_region == "cn"
    assert any("NEWS_DIGEST_REGION" in record.getMessage() for record in caplog.records)


def test_max_news_negative_falls_back_to_default(news_digest_config):
    config = news_digest_config(MAX_NEWS="-5")
    assert config.news_digest_max_news == 12


def test_interval_minutes_clamped_to_minimum_one(news_digest_config):
    """有效值 0 以下不存在（回退 10）；min 语义验证用 1 保留为 1 分钟。"""
    config = news_digest_config(INTERVAL_MINUTES="1")
    assert config.news_digest_interval_minutes == 1


def test_topics_empty_string_kept_raw_config_side(news_digest_config):
    """config 层空串保持空串原样（服务层 parse 负责回退默认 topics）。"""
    config = news_digest_config(TOPICS="")
    assert config.news_digest_topics == ""
    assert parse_news_digest_topics(config.news_digest_topics) == [
        "宏观政策",
        "货币宽松",
        "证监会",
        "外围市场",
        "行业利好",
    ]


def test_docs_mention_all_seven_env_keys():
    """双语 full-guide 必须覆盖全部 7 个 NEWS_DIGEST_ 键（计划 R14：文档与 registry 口径防漂移）。"""
    repo_root = Path(__file__).resolve().parents[1]
    expected = {
        "NEWS_DIGEST_ENABLED",
        "NEWS_DIGEST_PREMARKET_WINDOW",
        "NEWS_DIGEST_OFFDAY_WINDOW",
        "NEWS_DIGEST_TOPICS",
        "NEWS_DIGEST_MAX_NEWS",
        "NEWS_DIGEST_INTERVAL_MINUTES",
        "NEWS_DIGEST_REGION",
    }
    for doc in ("docs/full-guide.md", "docs/full-guide_EN.md"):
        text = (repo_root / doc).read_text(encoding="utf-8")
        missing = sorted(key for key in expected if key not in text)
        assert missing == [], f"{doc} missing env keys: {missing}"
