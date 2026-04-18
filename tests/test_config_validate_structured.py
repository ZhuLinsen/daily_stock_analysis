# -*- coding: utf-8 -*-
"""Tests for Config.validate_structured() and backward-compatible validate().

Covers:
- ConfigIssue dataclass basics
- validate_structured() severity classifications
- LLM availability check honours all three config tiers (YAML / channels /
  legacy keys) via llm_model_list
- validate() backward-compat: still returns List[str] with the same messages
"""
import pytest
from unittest.mock import patch

from src.config import Config, ConfigIssue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> Config:
    """Build a minimal Config object with sensible defaults for testing.

    Any keyword argument overrides the corresponding dataclass field so tests
    only have to specify the fields that matter for their scenario.
    """
    defaults = dict(
        stock_list=["600519"],
        tushare_token=None,
        # Populate llm_model_list as the three-tier signal
        llm_model_list=[{"model_name": "gemini/gemini-2.0-flash", "litellm_params": {"model": "gemini/gemini-2.0-flash", "api_key": "sk-test"}}],
        litellm_model="gemini/gemini-2.0-flash",
        gemini_api_keys=[],
        anthropic_api_keys=[],
        openai_api_keys=[],
        deepseek_api_keys=[],
        bocha_api_keys=[],
        tavily_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        searxng_base_urls=[],
        searxng_public_instances_enabled=True,
        wechat_webhook_url="https://example.com/webhook",
        feishu_webhook_url=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        email_sender=None,
        email_password=None,
        pushover_user_key=None,
        pushover_api_token=None,
        pushplus_token=None,
        serverchan3_sendkey=None,
        custom_webhook_urls=[],
        discord_bot_token=None,
        discord_main_channel_id=None,
        discord_webhook_url=None,
        discord_interactions_public_key=None,
        llm_channels=[],
        litellm_config_path=None,
        gemini_api_key=None,
        anthropic_api_key=None,
        openai_api_key=None,
        openai_base_url=None,
        openai_vision_model=None,
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _severities(issues):
    return [i.severity for i in issues]


def _fields(issues):
    return [i.field for i in issues]


# ---------------------------------------------------------------------------
# ConfigIssue basics
# ---------------------------------------------------------------------------

class TestConfigIssue:
    def test_str_equals_message(self):
        issue = ConfigIssue(severity="error", message="something went wrong", field="FOO")
        assert str(issue) == "something went wrong"

    def test_severity_values(self):
        for sev in ("error", "warning", "info"):
            issue = ConfigIssue(severity=sev, message="test", field="F")
            assert issue.severity == sev

    def test_default_field(self):
        issue = ConfigIssue(severity="info", message="hello")
        assert issue.field == ""


# ---------------------------------------------------------------------------
# validate_structured() — happy path (all good)
# ---------------------------------------------------------------------------

class TestValidateStructuredHappyPath:
    def test_no_issues_when_fully_configured(self):
        cfg = _make_config()
        issues = cfg.validate_structured()
        # No errors or warnings; only possible info about tushare / search
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# validate_structured() — stock list
# ---------------------------------------------------------------------------

class TestValidateStructuredStockList:
    def test_empty_stock_list_is_error(self):
        cfg = _make_config(stock_list=[])
        issues = cfg.validate_structured()
        errors = [i for i in issues if i.severity == "error"]
        assert any("STOCK_LIST" in i.field for i in errors)

    def test_configured_stock_list_no_stock_error(self):
        cfg = _make_config(stock_list=["600519", "000001"])
        issues = cfg.validate_structured()
        assert not any(i.field == "STOCK_LIST" for i in issues if i.severity == "error")

    def test_stock_email_groups_outside_stock_list_is_warning(self):
        cfg = _make_config(
            stock_list=["600519"],
            stock_email_groups=[(["600519", "000001"], ["group@example.com"])],
        )
        issues = cfg.validate_structured()
        warning = next(i for i in issues if i.field == "STOCK_GROUP_N")
        assert warning.severity == "warning"
        assert "000001" in warning.message
        assert "邮件路由" in warning.message
        assert "STOCK_LIST" in warning.message

    def test_stock_email_groups_subset_of_stock_list_has_no_warning(self):
        cfg = _make_config(
            stock_list=["600519", "000001"],
            stock_email_groups=[(["600519"], ["group@example.com"])],
        )
        issues = cfg.validate_structured()
        assert not any(i.field == "STOCK_GROUP_N" for i in issues)

    def test_stock_email_groups_canonical_normalization_no_false_warning(self):
        """Equivalent stock code formats (SH600519 vs 600519, 1810.HK vs HK01810)
        should not trigger a subset warning after canonical normalization."""
        cfg = _make_config(
            stock_list=["600519", "HK00700"],
            stock_email_groups=[
                (["SH600519", "1810.HK"], ["group@example.com"]),
            ],
        )
        issues = cfg.validate_structured()
        group_warnings = [i for i in issues if i.field == "STOCK_GROUP_N"]
        # SH600519 normalizes to 600519 (present in stock_list)
        # 1810.HK normalizes to HK01810 (NOT present — HK00700 ≠ HK01810)
        assert len(group_warnings) == 1
        assert "HK01810" in group_warnings[0].message
        assert "600519" not in group_warnings[0].message

    def test_stock_email_groups_warning_normalizes_and_deduplicates_codes(self):
        cfg = _make_config(
            stock_list=["600519"],
            stock_email_groups=[
                (["  aapl ", "AAPL", "aapl", " "], ["group@example.com"]),
            ],
        )
        issues = cfg.validate_structured()
        warning = next(i for i in issues if i.field == "STOCK_GROUP_N")
        assert warning.severity == "warning"
        assert "AAPL" in warning.message
        assert "  aapl " not in warning.message
        assert warning.message.count("AAPL") == 1


# ---------------------------------------------------------------------------
# validate_structured() — LLM availability (three-tier check)
# ---------------------------------------------------------------------------

class TestValidateStructuredLLM:
    def test_no_llm_is_error(self):
        """Empty llm_model_list must produce an error regardless of legacy keys."""
        cfg = _make_config(llm_model_list=[])
        issues = cfg.validate_structured()
        assert any(i.severity == "error" and "AI 模型" in i.message for i in issues)

    def test_llm_channels_only_no_error(self):
        """LLM_CHANNELS populated via llm_model_list must NOT trigger an error.

        This is the primary regression guard: a user who only configures
        LLM_CHANNELS (no legacy *_API_KEY) should not see 'AI 功能不可用'.
        """
        channel_model_list = [
            {"model_name": "openai/gpt-4o-mini", "litellm_params": {"api_key": "sk-chan", "api_base": "https://aihubmix.com/v1"}},
        ]
        cfg = _make_config(
            llm_model_list=channel_model_list,
            litellm_model="openai/gpt-4o-mini",
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=[],
            deepseek_api_keys=[],
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and "LLM" in i.message for i in issues)

    def test_yaml_config_only_no_error(self):
        """LITELLM_CONFIG (YAML) path: populated llm_model_list = no error."""
        yaml_model_list = [
            {"model_name": "gemini/gemini-2.5-flash", "litellm_params": {"api_key": "sk-yaml"}},
        ]
        cfg = _make_config(
            llm_model_list=yaml_model_list,
            litellm_model="gemini/gemini-2.5-flash",
            litellm_config_path="/tmp/litellm.yaml",
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=[],
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and "LLM" in i.message for i in issues)

    def test_legacy_gemini_key_no_error(self):
        """Legacy GEMINI_API_KEY path: llm_model_list populated = no error."""
        model_list = [
            {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "sk-gem"}},
        ]
        cfg = _make_config(llm_model_list=model_list, gemini_api_keys=["sk-gem"])
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and "LLM" in i.message for i in issues)

    def test_deepseek_only_no_error(self):
        """DEEPSEEK_API_KEY path (was missing in old validate()): no error."""
        model_list = [
            {"model_name": "__legacy_deepseek__", "litellm_params": {"model": "__legacy_deepseek__", "api_key": "sk-ds"}},
        ]
        cfg = _make_config(
            llm_model_list=model_list,
            deepseek_api_keys=["sk-ds"],
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=[],
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and "LLM" in i.message for i in issues)

    def test_missing_litellm_model_is_info_not_error(self):
        """llm_model_list present but litellm_model unset = info, not error."""
        cfg = _make_config(litellm_model="")
        issues = cfg.validate_structured()
        llm_issues = [i for i in issues if "LITELLM_MODEL" in i.field]
        assert llm_issues, "Expected an info issue about LITELLM_MODEL"
        assert all(i.severity == "info" for i in llm_issues)
        assert all("LITELLM_MODEL" not in i.message for i in llm_issues)
        assert any("主模型" in i.message for i in llm_issues)

    def test_direct_env_provider_model_without_model_list_no_error(self):
        """Direct LiteLLM env providers should count as configured for runtime."""
        cfg = _make_config(
            llm_model_list=[],
            litellm_model="cohere/command-r-plus",
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and "LLM" in i.message for i in issues)

    def test_configured_primary_model_missing_from_channels_is_error(self):
        cfg = _make_config(
            llm_model_list=[
                {"model_name": "openai/gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test"}},
            ],
            litellm_model="openai/gpt-4o",
        )
        issues = cfg.validate_structured()
        matching_issues = [i for i in issues if i.severity == "error" and i.field == "LITELLM_MODEL"]
        assert matching_issues
        assert all("LITELLM_MODEL" not in i.message for i in matching_issues)
        assert any("主模型" in i.message for i in matching_issues)

    def test_configured_agent_primary_model_missing_from_channels_is_error(self):
        cfg = _make_config(
            llm_model_list=[
                {"model_name": "openai/gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test"}},
            ],
            agent_litellm_model="openai/gpt-4o",
        )
        issues = cfg.validate_structured()
        assert any(i.severity == "error" and i.field == "AGENT_LITELLM_MODEL" for i in issues)

    def test_configured_agent_primary_model_without_runtime_source_is_error(self):
        cfg = _make_config(
            llm_model_list=[],
            litellm_model="cohere/command-r-plus",
            agent_litellm_model="openai/gpt-4o-mini",
            openai_api_keys=[],
        )
        issues = cfg.validate_structured()
        assert any(i.severity == "error" and i.field == "AGENT_LITELLM_MODEL" for i in issues)

    def test_configured_agent_primary_model_matching_yaml_alias_is_allowed(self):
        cfg = _make_config(
            llm_model_list=[
                {"model_name": "gpt4o", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test"}},
            ],
            agent_litellm_model="gpt4o",
        )
        issues = cfg.validate_structured()
        assert not any(i.severity == "error" and i.field == "AGENT_LITELLM_MODEL" for i in issues)

    def test_configured_vision_model_missing_from_channels_is_warning(self):
        cfg = _make_config(
            llm_model_list=[
                {"model_name": "openai/gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test"}},
            ],
            vision_model="openai/gpt-4o",
        )
        issues = cfg.validate_structured()
        assert any(i.severity == "warning" and i.field == "VISION_MODEL" for i in issues)


# ---------------------------------------------------------------------------
# validate_structured() — notification & search
# ---------------------------------------------------------------------------

class TestValidateStructuredNotification:
    def test_no_notification_is_warning(self):
        cfg = _make_config(wechat_webhook_url=None)
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.severity == "warning"]
        assert any("通知渠道" in i.message for i in warn)

    def test_notification_configured_no_warning(self):
        cfg = _make_config(wechat_webhook_url="https://example.com/wh")
        issues = cfg.validate_structured()
        assert not any(i.severity == "warning" and "通知渠道" in i.message for i in issues)

    def test_feishu_app_credentials_without_webhook_warns_mode_mismatch(self):
        cfg = _make_config(
            wechat_webhook_url=None,
            feishu_app_id="cli_xxx",
            feishu_app_secret="secret_xxx",
            feishu_webhook_url=None,
            feishu_stream_enabled=False,
        )
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.severity == "warning"]
        assert any("FEISHU_APP_ID / FEISHU_APP_SECRET" in i.message for i in warn)

    def test_feishu_cloud_doc_credentials_without_webhook_no_mode_warning(self):
        cfg = _make_config(
            wechat_webhook_url=None,
            feishu_app_id="cli_xxx",
            feishu_app_secret="secret_xxx",
            feishu_folder_token="folder_xxx",
            feishu_webhook_url=None,
            feishu_stream_enabled=False,
        )
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.severity == "warning"]
        assert not any("FEISHU_APP_ID / FEISHU_APP_SECRET" in i.message for i in warn)

    def test_no_search_engine_is_info(self):
        cfg = _make_config(searxng_public_instances_enabled=False)
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert any("搜索引擎" in i.message for i in info)
        search_issue = next(i for i in info if "搜索引擎" in i.message)
        assert search_issue.field == "BOCHA_API_KEYS"

    def test_searxng_configured_no_search_info(self):
        """When searxng_base_urls is configured, no 'unconfigured search engine' info."""
        cfg = _make_config(searxng_base_urls=["https://searx.example.org"])
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert not any("搜索引擎" in i.message and "未配置" in i.message for i in info)

    def test_public_searxng_enabled_no_search_info(self):
        """Public SearXNG mode also counts as search capability."""
        cfg = _make_config(searxng_public_instances_enabled=True)
        issues = cfg.validate_structured()
        info = [i for i in issues if i.severity == "info"]
        assert not any("搜索引擎" in i.message and "未配置" in i.message for i in info)


# ---------------------------------------------------------------------------
# Deprecated field migration hints
# ---------------------------------------------------------------------------

class TestDeprecatedFieldHints:
    def test_openai_vision_model_deprecation_when_env_set(self):
        """When OPENAI_VISION_MODEL is in env, validate_structured reports deprecation hint."""
        cfg = _make_config()
        with patch.dict("os.environ", {"OPENAI_VISION_MODEL": "openai/gpt-4o"}, clear=False):
            issues = cfg.validate_structured()
        deprec = [i for i in issues if i.field == "OPENAI_VISION_MODEL"]
        assert deprec, "Expected deprecation hint when OPENAI_VISION_MODEL is set"
        assert deprec[0].severity == "info"
        assert "VISION_MODEL" in deprec[0].message

    def test_no_deprecation_when_openai_vision_model_not_in_env(self):
        """When OPENAI_VISION_MODEL is not in env, no deprecation hint."""
        import os
        cfg = _make_config()
        real_getenv = os.getenv

        def mock_getenv(key, default=None):
            if key == "OPENAI_VISION_MODEL":
                return None
            return real_getenv(key, default)

        with patch("src.config.os.getenv", side_effect=mock_getenv):
            issues = cfg.validate_structured()
        deprec = [i for i in issues if i.field == "OPENAI_VISION_MODEL"]
        assert not deprec, "Should not report deprecation when OPENAI_VISION_MODEL is unset"


# ---------------------------------------------------------------------------
# Vision key validation
# ---------------------------------------------------------------------------

class TestVisionKeyValidation:
    def test_vision_model_set_no_key_is_warning(self):
        cfg = _make_config(
            vision_model="gemini/gemini-2.0-flash",
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=[],
            deepseek_api_keys=[],
        )
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.field == "VISION_MODEL"]
        assert warn and warn[0].severity == "warning"

    def test_vision_model_set_with_key_no_warning(self):
        cfg = _make_config(
            vision_model="gemini/gemini-2.0-flash",
            gemini_api_keys=["sk-gemini-testkey-1234"],
        )
        issues = cfg.validate_structured()
        assert not any(
            i.field == "VISION_MODEL" and i.severity == "warning" for i in issues
        )

    def test_vision_model_set_with_short_key_still_warns(self):
        """Short keys (len < 8) are filtered at runtime; validation should warn."""
        cfg = _make_config(
            vision_model="gemini/gemini-2.0-flash",
            gemini_api_keys=["x"],
            anthropic_api_keys=[],
            openai_api_keys=[],
            deepseek_api_keys=[],
        )
        issues = cfg.validate_structured()
        warn = [i for i in issues if i.field == "VISION_MODEL"]
        assert warn and warn[0].severity == "warning"

    def test_primary_provider_key_sufficient_even_if_not_in_priority(self):
        """Primary model's provider key is checked even when absent from VISION_PROVIDER_PRIORITY."""
        cfg = _make_config(
            llm_model_list=[
                {"model_name": "openai/gpt-4o", "litellm_params": {"model": "openai/gpt-4o", "api_key": "sk-test"}},
            ],
            litellm_model="openai/gpt-4o",
            vision_model="openai/gpt-4o",
            vision_provider_priority="gemini,anthropic",  # openai excluded from priority
            openai_api_keys=["sk-openai-validkey-xyz"],
            gemini_api_keys=[],
            anthropic_api_keys=[],
            deepseek_api_keys=[],
        )
        issues = cfg.validate_structured()
        # Should NOT warn: primary model (openai) has a valid key
        assert not any(i.field == "VISION_MODEL" and i.severity == "warning" for i in issues)

    def test_no_vision_model_no_warning(self):
        """When VISION_MODEL is not set, no Vision key warning is raised."""
        cfg = _make_config(vision_model="", gemini_api_keys=[])
        issues = cfg.validate_structured()
        assert not any(i.field == "VISION_MODEL" for i in issues)


# ---------------------------------------------------------------------------
# Env alias compatibility
# ---------------------------------------------------------------------------

class TestEnvAliasCompatibility:
    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_discord_channel_id_legacy_alias_is_still_loaded(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ):
        with patch.dict(
            "os.environ",
            {
                "DISCORD_BOT_TOKEN": "token",
                "DISCORD_CHANNEL_ID": "legacy-channel",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        assert config.discord_bot_token == "token"
        assert config.discord_main_channel_id == "legacy-channel"

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_discord_main_channel_id_takes_precedence_over_legacy_alias(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ):
        with patch.dict(
            "os.environ",
            {
                "DISCORD_BOT_TOKEN": "token",
                "DISCORD_CHANNEL_ID": "legacy-channel",
                "DISCORD_MAIN_CHANNEL_ID": "main-channel",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        assert config.discord_main_channel_id == "main-channel"

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_discord_interactions_public_key_is_loaded(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ):
        with patch.dict(
            "os.environ",
            {
                "DISCORD_INTERACTIONS_PUBLIC_KEY": "abcdef123456",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        assert config.discord_interactions_public_key == "abcdef123456"


# ---------------------------------------------------------------------------
# validate() backward compatibility
# ---------------------------------------------------------------------------

class TestValidateBackwardCompat:
    def test_returns_list_of_str(self):
        cfg = _make_config()
        result = cfg.validate()
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_empty_llm_model_list_message_in_validate(self):
        cfg = _make_config(llm_model_list=[])
        messages = cfg.validate()
        assert any("AI 模型" in m for m in messages)

    def test_messages_match_validate_structured(self):
        """validate() strings must be the message field of each ConfigIssue."""
        cfg = _make_config(llm_model_list=[], stock_list=[])
        structured = cfg.validate_structured()
        plain = cfg.validate()
        assert plain == [i.message for i in structured]
