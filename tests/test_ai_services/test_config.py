# -*- coding: utf-8 -*-
"""AI 服务配置模块测试。"""

from __future__ import annotations

import os

from src.ai_services.config import (
    AIServiceConfig,
    AIServiceSettings,
    HONGDIE_DEFAULT_BASE_URL,
    HONGDIE_DEFAULT_MODEL,
    HONGDIE_HOMEPAGE_URL,
    DEEPSEEK_DEFAULT_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL,
    mask_key,
)


class TestAIServiceSettings:
    """测试 AIServiceSettings。"""

    def test_default_values(self) -> None:
        settings = AIServiceSettings()
        assert settings.enabled is False
        assert settings.api_key == ""
        assert settings.base_url == ""
        assert settings.model == ""
        assert settings.timeout == 30.0
        assert settings.temperature is None
        assert settings.max_tokens is None
        assert settings.extra_params == {}

    def test_is_configured_with_all_requirements(self) -> None:
        settings = AIServiceSettings(enabled=True, api_key="sk-test")
        assert settings.is_configured() is True

    def test_is_configured_disabled(self) -> None:
        settings = AIServiceSettings(enabled=False, api_key="sk-test")
        assert settings.is_configured() is False

    def test_is_configured_no_key(self) -> None:
        settings = AIServiceSettings(enabled=True, api_key="")
        assert settings.is_configured() is False

    def test_custom_values(self) -> None:
        settings = AIServiceSettings(
            enabled=True,
            api_key="sk-test",
            base_url="https://custom.api.com/v1",
            model="test-model",
            timeout=60.0,
            temperature=0.5,
            max_tokens=2048,
        )
        assert settings.base_url == "https://custom.api.com/v1"
        assert settings.model == "test-model"
        assert settings.timeout == 60.0
        assert settings.temperature == 0.5
        assert settings.max_tokens == 2048

    def test_extra_params(self) -> None:
        settings = AIServiceSettings(
            enabled=True,
            api_key="sk-test",
            extra_params={"stop": ["END"], "top_p": 0.9},
        )
        assert settings.extra_params["stop"] == ["END"]
        assert settings.extra_params["top_p"] == 0.9


class TestAIServiceConfig:
    """测试 AIServiceConfig。"""

    def test_default_config(self) -> None:
        config = AIServiceConfig()
        assert config.deepseek.enabled is False
        assert config.hongdie.enabled is False
        assert config.cache_enabled is True
        assert config.rate_limiter_enabled is True

    def test_from_env_with_custom_values(self) -> None:
        """测试从环境变量加载配置。"""
        env_vars = {
            "DEEPSEEK_ENABLED": "true",
            "DEEPSEEK_API_KEY": "sk-deepseek-test",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_TIMEOUT": "60",
            "DEEPSEEK_TEMPERATURE": "0.3",
            "DEEPSEEK_MAX_TOKENS": "4096",
            "HONGDIE_ENABLED": "true",
            "HONGDIE_API_KEY": "sk-hongdie-test",
            "HONGDIE_MODEL": "gpt-4o",
            "HONGDIE_BASE_URL": "https://tokento.vip/v1",
            "HONGDIE_TIMEOUT": "45",
            "AI_SERVICE_CACHE_ENABLED": "true",
            "AI_SERVICE_CACHE_MAX_SIZE": "1000",
            "AI_SERVICE_CACHE_TTL": "600",
            "AI_SERVICE_RATE_LIMITER_ENABLED": "true",
        }

        for key, value in env_vars.items():
            os.environ[key] = value

        try:
            config = AIServiceConfig.from_env()

            # DeepSeek
            assert config.deepseek.enabled is True
            assert config.deepseek.api_key == "sk-deepseek-test"
            assert config.deepseek.model == "deepseek-v4-flash"
            assert config.deepseek.base_url == "https://api.deepseek.com"
            assert config.deepseek.timeout == 60.0
            assert config.deepseek.temperature == 0.3
            assert config.deepseek.max_tokens == 4096

            # 红蝶AI
            assert config.hongdie.enabled is True
            assert config.hongdie.api_key == "sk-hongdie-test"
            assert config.hongdie.model == "gpt-4o"
            assert config.hongdie.base_url == "https://tokento.vip/v1"
            assert config.hongdie.timeout == 45.0
            assert config.hongdie.temperature is None  # 未设置
            assert config.hongdie.max_tokens is None

            # 缓存
            assert config.cache_enabled is True
            assert config.cache_max_size == 1000
            assert config.cache_ttl_seconds == 600

            # 限流
            assert config.rate_limiter_enabled is True
        finally:
            for key in env_vars:
                os.environ.pop(key, None)

    def test_from_env_with_defaults(self) -> None:
        """测试空环境变量下的默认值。"""
        config = AIServiceConfig.from_env()
        # DeepSeek 默认启用（向后兼容）
        assert config.deepseek.enabled is True
        assert config.deepseek.model == DEEPSEEK_DEFAULT_MODEL
        assert config.deepseek.base_url == DEEPSEEK_DEFAULT_BASE_URL
        assert config.deepseek.timeout == 30.0

        # 红蝶AI 默认禁用
        assert config.hongdie.enabled is False
        assert config.hongdie.model == HONGDIE_DEFAULT_MODEL
        assert config.hongdie.base_url == HONGDIE_DEFAULT_BASE_URL
        assert config.hongdie.timeout == 30.0

    def test_get_enabled_services(self) -> None:
        config = AIServiceConfig()
        assert config.get_enabled_services() == []

        config.deepseek.enabled = True
        assert config.get_enabled_services() == ["deepseek"]

        config.hongdie.enabled = True
        assert config.get_enabled_services() == ["deepseek", "hongdie"]

    def test_to_env_dict(self) -> None:
        """将配置转换为环境变量字典。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-deepseek-test"
        config.deepseek.model = "deepseek-chat"
        config.deepseek.base_url = "https://api.deepseek.com"
        config.deepseek.timeout = 30.0
        config.deepseek.temperature = 0.7

        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-hongdie-test"
        config.hongdie.model = "gpt-4o"
        config.hongdie.base_url = "https://tokento.vip/v1"
        config.hongdie.timeout = 30.0
        config.hongdie.max_tokens = 2048

        env_dict = config.to_env_dict()

        assert env_dict["DEEPSEEK_ENABLED"] == "true"
        assert env_dict["DEEPSEEK_API_KEY"] == "sk-deepseek-test"
        assert env_dict["DEEPSEEK_MODEL"] == "deepseek-chat"
        assert env_dict["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
        assert env_dict["DEEPSEEK_TIMEOUT"] == "30.0"
        assert env_dict["DEEPSEEK_TEMPERATURE"] == "0.7"

        assert env_dict["HONGDIE_ENABLED"] == "true"
        assert env_dict["HONGDIE_API_KEY"] == "sk-hongdie-test"
        assert env_dict["HONGDIE_MODEL"] == "gpt-4o"
        assert env_dict["HONGDIE_BASE_URL"] == "https://tokento.vip/v1"
        assert env_dict["HONGDIE_TIMEOUT"] == "30.0"
        assert env_dict["HONGDIE_MAX_TOKENS"] == "2048"

    def test_to_env_dict_no_keys_when_empty(self) -> None:
        """空的 API Key 不应出现在 env 字典中。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        # api_key is empty

        env_dict = config.to_env_dict()
        assert "DEEPSEEK_API_KEY" not in env_dict

    def test_mask_api_keys(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-test-key-12345678"
        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-hongdie-secret-key"

        masked = config.mask_api_keys()
        assert "****" in masked.deepseek.api_key
        assert "****" in masked.hongdie.api_key
        assert "sk-t" in masked.deepseek.api_key or "sk-" in masked.deepseek.api_key
        assert masked.deepseek.base_url == config.deepseek.base_url  # base_url 不变

    def test_hongdie_constants(self) -> None:
        """验证红蝶AI 常量。"""
        assert HONGDIE_DEFAULT_BASE_URL == "https://tokento.vip/v1"
        assert HONGDIE_DEFAULT_MODEL == "gpt-4o-mini"
        assert HONGDIE_HOMEPAGE_URL == "https://tokento.vip"

    def test_deepseek_constants(self) -> None:
        """验证 DeepSeek 常量。"""
        assert DEEPSEEK_DEFAULT_BASE_URL == "https://api.deepseek.com"
        assert DEEPSEEK_DEFAULT_MODEL == "deepseek-chat"


class TestMaskKey:
    """测试 API Key 掩码。"""

    def test_mask_empty_key(self) -> None:
        assert mask_key("") == ""

    def test_mask_short_key(self) -> None:
        """短 key 返回 ****。"""
        result = mask_key("12345")
        assert "****" in result

    def test_mask_normal_key(self) -> None:
        result = mask_key("sk-test-key-12345678")
        assert result.startswith("sk-t")
        assert result.endswith("5678")
        assert "****" in result

    def test_mask_key_boundary(self) -> None:
        """刚好 visible_chars + 4 个字符。"""
        # Key 长度为 8, visible_chars=4, 所以显示 4 + **** + 4=8
        result = mask_key("12345678", visible_chars=4)
        # 因为 len(key) = 8, 不大于 visible_chars + 4, 走 len(key) > visible_chars + 4 分支
        # 所以是 "1234****5678" (不对, len=8, visible_chars+4=8, not >, so goes to else: "****")
        # Actually let me check the logic again:
        # if len(key) <= visible_chars + 4: 8 <= 8 -> True
        #   return key[:visible_chars] + "****" + key[-4:] if len(key) > visible_chars + 4 else "****"
        #   8 > 8 -> False -> "****"
        assert result == "****"
