# -*- coding: utf-8 -*-
"""Tests for backward-compatible config env aliases and TickFlow loading."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC, setup_env


class ConfigEnvCompatibilityTestCase(unittest.TestCase):
    def tearDown(self):
        Config.reset_instance()

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    @patch.object(Config, "_parse_stock_email_groups", return_value=[])
    def test_stock_list_accepts_common_copy_paste_separators(
        self, _mock_parse_stock_email_groups, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519，300750  hk00700;AAPL、7203.T\n005930.KS",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(
            config.stock_list,
            ["600519", "300750", "HK00700", "AAPL", "7203.T", "005930.KS"],
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_reads_tickflow_api_key(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "TICKFLOW_API_KEY": "tf-secret",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.tickflow_api_key, "tf-secret")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_market_review_region_accepts_comma_separated_supported_values(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "MARKET_REVIEW_REGION": "cn,us,jp",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.market_review_region, "cn,us,jp")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_market_review_region_filters_invalid_values_in_comma_subset(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "MARKET_REVIEW_REGION": "cn,eu,us,kr,xx",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.market_review_region, "cn,us,kr")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_market_review_region_falls_back_to_cn_when_no_supported_tokens(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "MARKET_REVIEW_REGION": "eu,apac",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.market_review_region, "cn")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_keeps_default_behavior_without_tickflow_api_key(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertIsNone(config.tickflow_api_key)
        self.assertEqual(
            config.realtime_source_priority,
            "tencent,akshare_sina,efinance,akshare_em",
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_generation_backend_env_defaults_to_litellm_contract(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(os.environ, {"STOCK_LIST": "600519"}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.generation_backend, "litellm")
        self.assertEqual(config.generation_fallback_backend, "litellm")
        self.assertEqual(config.agent_generation_backend, "auto")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_generation_backend_env_accepts_phase2_values(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "GENERATION_BACKEND": " codex_CLI ",
                "GENERATION_FALLBACK_BACKEND": "",
                "GENERATION_BACKEND_TIMEOUT_SECONDS": "300",
                "GENERATION_BACKEND_MAX_OUTPUT_BYTES": "1048576",
                "GENERATION_BACKEND_MAX_CONCURRENCY": "2",
                "LOCAL_CLI_BACKEND_MAX_CONCURRENCY": "1",
                "AGENT_GENERATION_BACKEND": " codex_cli ",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.generation_backend, "codex_cli")
        self.assertEqual(config.generation_fallback_backend, "")
        self.assertEqual(config.generation_backend_timeout_seconds, 300)
        self.assertEqual(config.generation_backend_max_output_bytes, 1048576)
        self.assertEqual(config.generation_backend_max_concurrency, 2)
        self.assertEqual(config.local_cli_backend_max_concurrency, 1)
        self.assertEqual(config.agent_generation_backend, "codex_cli")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_generation_backend_env_clamps_phase2_numeric_maxima(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "GENERATION_BACKEND_TIMEOUT_SECONDS": "999999",
                "GENERATION_BACKEND_MAX_OUTPUT_BYTES": "999999999",
                "GENERATION_BACKEND_MAX_CONCURRENCY": "999",
                "LOCAL_CLI_BACKEND_MAX_CONCURRENCY": "999",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.generation_backend_timeout_seconds, 3600)
        self.assertEqual(config.generation_backend_max_output_bytes, 33554432)
        self.assertEqual(config.generation_backend_max_concurrency, 16)
        self.assertEqual(config.local_cli_backend_max_concurrency, 4)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_prompt_cache_config_defaults_are_safe(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(os.environ, {"STOCK_LIST": "600519"}, clear=True):
            config = Config._load_from_env()

        self.assertTrue(config.llm_prompt_cache_telemetry_enabled)
        self.assertFalse(config.llm_prompt_cache_hints_enabled)
        self.assertEqual(config.llm_prompt_cache_diagnostics_level, "off")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_prompt_cache_config_parses_env_values(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "LLM_PROMPT_CACHE_TELEMETRY_ENABLED": "false",
                "LLM_PROMPT_CACHE_HINTS_ENABLED": "true",
                "LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL": " DEBUG ",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertFalse(config.llm_prompt_cache_telemetry_enabled)
        self.assertTrue(config.llm_prompt_cache_hints_enabled)
        self.assertEqual(config.llm_prompt_cache_diagnostics_level, "debug")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_prompt_cache_invalid_diagnostics_level_falls_back_to_off(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL": "verbose",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.llm_prompt_cache_diagnostics_level, "off")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_uses_stable_fundamental_timeout_defaults(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.fundamental_stage_timeout_seconds, 8.0)
        self.assertEqual(config.fundamental_fetch_timeout_seconds, 3.0)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_schedule_times_parse_dedupe_and_fallback(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "SCHEDULE_TIME": "18:00",
                "SCHEDULE_TIMES": "15:10,09:20,15:10",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.schedule_time, "18:00")
        self.assertEqual(config.schedule_times, ["09:20", "15:10"])

        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "SCHEDULE_TIME": "09:30",
                "SCHEDULE_TIMES": "",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.schedule_times, [config.schedule_time])

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_alphasift_install_spec_defaults_only_when_env_missing(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(os.environ, {"STOCK_LIST": "600519"}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.alphasift_install_spec, DEFAULT_ALPHASIFT_INSTALL_SPEC)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_news_intel_envs_do_not_change_llm_runtime_contract(
        self,
        _mock_parse_litellm_yaml,
        _mock_setup_env,
    ) -> None:
        base_env = {
            "STOCK_LIST": "600519",
            "OPENAI_API_KEYS": "base-key-12345",
            "OPENAI_BASE_URL": "https://openai.example.com/v1",
            "LITELLM_MODEL": "openai/gpt-4.1",
            "OPENAI_MODEL": "gpt-4.1",
        }
        with patch.dict(os.environ, base_env, clear=True):
            Config._instance = None
            baseline = Config._load_from_env()

        news_intel_env = dict(base_env)
        news_intel_env.update({
            "NEWS_INTEL_RETENTION_DAYS": "45",
            "NEWS_INTEL_FETCH_TIMEOUT_SEC": "5.5",
            "NEWS_INTEL_MAX_ITEMS_PER_SOURCE": "25",
            "NEWS_INTEL_AUTO_FETCH_ENABLED": "true",
            "NEWSNOW_BASE_URL": "https://newsnow.example.com/",
        })
        with patch.dict(os.environ, news_intel_env, clear=True):
            Config._instance = None
            with_news_intel = Config._load_from_env()

        self.assertEqual(with_news_intel.litellm_model, baseline.litellm_model)
        self.assertEqual(with_news_intel.litellm_fallback_models, baseline.litellm_fallback_models)
        self.assertEqual(with_news_intel.openai_api_key, baseline.openai_api_key)
        self.assertEqual(with_news_intel.openai_base_url, baseline.openai_base_url)
        self.assertEqual(with_news_intel.news_intel_fetch_timeout_sec, 5.5)
        self.assertEqual(with_news_intel.news_intel_max_items_per_source, 25)
        self.assertEqual(with_news_intel.news_intel_retention_days, 45)
        self.assertTrue(with_news_intel.news_intel_auto_fetch_enabled)
        self.assertEqual(with_news_intel.newsnow_base_url, "https://newsnow.example.com")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_market_review_region_updates_do_not_change_llm_provider_model_contract(
        self,
        _mock_parse_litellm_yaml,
        _mock_setup_env,
    ) -> None:
        base_env = {
            "STOCK_LIST": "600519",
            "MARKET_REVIEW_REGION": "cn",
            "LITELLM_MODEL": "openai/gpt-4.1",
            "OPENAI_MODEL": "gpt-4.1",
            "OPENAI_BASE_URL": "https://openai.example.com/v1",
            "OPENAI_API_KEY": "base-key-12345",
            "LITELLM_FALLBACK_MODELS": "openai/gpt-5.5,openai/gpt-4o-mini",
            "VISION_MODEL": "openai/gpt-4o-mini",
        }
        with patch.dict(os.environ, base_env, clear=True):
            baseline = Config._load_from_env()

        with_jpkr_env = dict(base_env)
        with_jpkr_env["MARKET_REVIEW_REGION"] = "both"
        with patch.dict(os.environ, with_jpkr_env, clear=True):
            with_jpkr = Config._load_from_env()

        self.assertEqual(with_jpkr.litellm_model, baseline.litellm_model)
        self.assertEqual(with_jpkr.litellm_fallback_models, baseline.litellm_fallback_models)
        self.assertEqual(with_jpkr.vision_model, baseline.vision_model)
        self.assertEqual(with_jpkr.openai_model, baseline.openai_model)
        self.assertEqual(with_jpkr.openai_api_key, baseline.openai_api_key)
        self.assertEqual(with_jpkr.openai_base_url, baseline.openai_base_url)

    def test_env_example_alphasift_install_spec_matches_trusted_default(self):
        env_example = Path(__file__).resolve().parents[1] / ".env.example"

        for line in env_example.read_text(encoding="utf-8").splitlines():
            if line.startswith("ALPHASIFT_INSTALL_SPEC="):
                self.assertEqual(
                    line,
                    f"ALPHASIFT_INSTALL_SPEC={DEFAULT_ALPHASIFT_INSTALL_SPEC}",
                )
                break
        else:
            self.fail("ALPHASIFT_INSTALL_SPEC missing from .env.example")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_alphasift_install_spec_honors_explicit_empty(
        self, _mock_parse_litellm_yaml, _mock_setup_env
    ):
        with patch.dict(
            os.environ,
            {"STOCK_LIST": "600519", "ALPHASIFT_INSTALL_SPEC": ""},
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.alphasift_install_spec, "")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_schedule_run_immediately_falls_back_to_legacy_run_immediately(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "RUN_IMMEDIATELY": "false",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertFalse(config.schedule_run_immediately)
        self.assertFalse(config.run_immediately)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_schedule_run_immediately_prefers_schedule_specific_setting(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "RUN_IMMEDIATELY": "false",
            "SCHEDULE_RUN_IMMEDIATELY": "true",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertTrue(config.schedule_run_immediately)
        self.assertFalse(config.run_immediately)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_empty_legacy_run_immediately_stays_false_when_schedule_alias_is_unset(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "RUN_IMMEDIATELY": "",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertFalse(config.schedule_run_immediately)
        self.assertFalse(config.run_immediately)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_empty_schedule_run_immediately_stays_false_without_falling_back(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "RUN_IMMEDIATELY": "true",
            "SCHEDULE_RUN_IMMEDIATELY": "",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertFalse(config.schedule_run_immediately)
        self.assertTrue(config.run_immediately)

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_schedule_run_immediately_ignores_persisted_alias_when_only_legacy_env_is_explicit(
        self,
        _mock_parse_yaml,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519",
                        "RUN_IMMEDIATELY=true",
                        "SCHEDULE_RUN_IMMEDIATELY=true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "RUN_IMMEDIATELY": "false",
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertFalse(config.run_immediately)
        self.assertFalse(config.schedule_run_immediately)

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_blank_schedule_time_falls_back_to_default(
        self,
        _mock_parse_yaml,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519",
                        "SCHEDULE_TIME=",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(config.schedule_time, "18:00")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_news_intel_env_vars_do_not_affect_llm_layer(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "600519",
                "LITELLM_MODEL": "openai/gpt-5.5",
                "OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENAI_BASE_URL": "https://openai.example/v1",
                "NEWS_INTEL_RETENTION_DAYS": "14",
                "NEWS_INTEL_FETCH_TIMEOUT_SEC": "12",
                "NEWS_INTEL_MAX_ITEMS_PER_SOURCE": "75",
                "NEWS_INTEL_AUTO_FETCH_ENABLED": "yes",
                "NEWSNOW_BASE_URL": "https://newsnow.example.com/base/",
            },
            clear=True,
        ):
            config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "openai/gpt-5.5")
        self.assertEqual(config.openai_model, "gpt-5.5")
        self.assertEqual(config.openai_base_url, "https://openai.example/v1")
        self.assertEqual(config.news_intel_retention_days, 14)
        self.assertEqual(config.news_intel_fetch_timeout_sec, 12.0)
        self.assertEqual(config.news_intel_max_items_per_source, 75)
        self.assertTrue(config.news_intel_auto_fetch_enabled)
        self.assertEqual(config.newsnow_base_url, "https://newsnow.example.com/base")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_report_language_prefers_preexisting_process_env_over_env_file(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("REPORT_LANGUAGE=zh\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "REPORT_LANGUAGE": "en",
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(config.report_language, "en")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_report_language_uses_env_file_when_process_env_is_absent(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("REPORT_LANGUAGE=en\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(config.report_language, "en")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_report_show_llm_model_defaults_true_and_can_be_disabled(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config._load_from_env()
        self.assertTrue(config.report_show_llm_model)

        with patch.dict(os.environ, {"REPORT_SHOW_LLM_MODEL": "false"}, clear=True):
            config = Config._load_from_env()
        self.assertFalse(config.report_show_llm_model)

        with patch.dict(os.environ, {"REPORT_SHOW_LLM_MODEL": ""}, clear=True):
            config = Config._load_from_env()
        self.assertFalse(config.report_show_llm_model)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_market_review_color_scheme_defaults_and_accepts_red_up(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config._load_from_env()
        self.assertEqual(config.market_review_color_scheme, "green_up")

        with patch.dict(os.environ, {"MARKET_REVIEW_COLOR_SCHEME": "red-up"}, clear=True):
            config = Config._load_from_env()
        self.assertEqual(config.market_review_color_scheme, "red_up")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_daily_market_context_enabled_defaults_on_and_can_disable(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config._load_from_env()
        self.assertTrue(config.daily_market_context_enabled)

        with patch.dict(os.environ, {"DAILY_MARKET_CONTEXT_ENABLED": "false"}, clear=True):
            config = Config._load_from_env()
        self.assertFalse(config.daily_market_context_enabled)

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_runtime_mutable_keys_reload_from_updated_env_file_after_runtime_refresh(
        self,
        _mock_parse_yaml,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519",
                        "SCHEDULE_ENABLED=false",
                        "SCHEDULE_TIME=18:00",
                        "RUN_IMMEDIATELY=true",
                        "SCHEDULE_RUN_IMMEDIATELY=false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "STOCK_LIST": "600519",
                    "SCHEDULE_ENABLED": "false",
                    "SCHEDULE_TIME": "18:00",
                    "RUN_IMMEDIATELY": "true",
                    "SCHEDULE_RUN_IMMEDIATELY": "false",
                },
                clear=True,
            ):
                Config._load_from_env()
                env_path.write_text(
                    "\n".join(
                        [
                            "STOCK_LIST=300750,TSLA",
                            "SCHEDULE_ENABLED=true",
                            "SCHEDULE_TIME=09:30",
                            "RUN_IMMEDIATELY=false",
                            "SCHEDULE_RUN_IMMEDIATELY=true",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                Config.reset_instance()
                setup_env(override=True)
                config = Config._load_from_env()

        self.assertEqual(config.stock_list, ["300750", "TSLA"])
        self.assertTrue(config.schedule_enabled)
        self.assertEqual(config.schedule_time, "09:30")
        self.assertFalse(config.run_immediately)
        self.assertTrue(config.schedule_run_immediately)

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_runtime_mutable_keys_prefer_process_env_when_values_differ(
        self,
        _mock_parse_yaml,
    ) -> None:
        """When process env explicitly sets a WEBUI-mutable key to a value
        that differs from .env (e.g. via docker-compose ``environment:``),
        the process env must win because ``_capture_bootstrap_runtime_env_overrides``
        runs before dotenv loads and the mismatch proves an intentional override.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=300750,TSLA",
                        "SCHEDULE_ENABLED=true",
                        "SCHEDULE_TIME=09:30",
                        "RUN_IMMEDIATELY=false",
                        "SCHEDULE_RUN_IMMEDIATELY=true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "STOCK_LIST": "600519,000001",
                    "SCHEDULE_ENABLED": "false",
                    "SCHEDULE_TIME": "18:00",
                    "RUN_IMMEDIATELY": "true",
                    "SCHEDULE_RUN_IMMEDIATELY": "false",
                },
                clear=True,
            ):
                config = Config._load_from_env()

        # Explicit process env overrides win when values differ from .env
        self.assertEqual(config.stock_list, ["600519", "000001"])
        self.assertFalse(config.schedule_enabled)
        self.assertEqual(config.schedule_time, "18:00")
        self.assertTrue(config.run_immediately)
        self.assertFalse(config.schedule_run_immediately)

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_runtime_mutable_keys_use_process_env_when_absent_from_file(
        self,
        _mock_parse_yaml,
    ) -> None:
        """When a WEBUI-mutable key exists only in process env (not in .env),
        it IS a genuine explicit override and must be honoured.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            # .env has no STOCK_LIST or SCHEDULE_* keys at all
            env_path.write_text("LOG_LEVEL=INFO\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "STOCK_LIST": "600519,000001",
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(config.stock_list, ["600519", "000001"])

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_custom_webhook_template_unescapes_compose_saved_placeholders(
        self,
        _mock_parse_yaml,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                'CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$$title_json,"content":$$content_json}\n',
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                    "CUSTOM_WEBHOOK_BODY_TEMPLATE": '{"title":$$title_json,"content":$$content_json}',
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(
            config.custom_webhook_body_template,
            '{"title":$title_json,"content":$content_json}',
        )

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_custom_webhook_template_unescapes_compose_saved_braced_placeholders(
        self,
        _mock_parse_yaml,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$${content_json}}\n',
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ENV_FILE": str(env_path)},
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(
            config.custom_webhook_body_template,
            '{"content":${content_json}}',
        )

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_custom_webhook_template_does_not_affect_llm_contract(
        self,
        _mock_parse_litellm_yaml: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519",
                        "LITELLM_MODEL=openai/gpt-5.5",
                        "OPENAI_MODEL=gpt-5.5",
                        "OPENAI_API_KEY=runtime-openai-key",
                        "OPENAI_BASE_URL=https://openai.example/v1",
                        "CUSTOM_WEBHOOK_BODY_TEMPLATE={\"title\":$$title_json,\"content\":$$content_json}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(env_path),
                },
                clear=True,
            ):
                config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "openai/gpt-5.5")
        self.assertEqual(config.openai_model, "gpt-5.5")
        self.assertEqual(config.openai_api_key, "runtime-openai-key")
        self.assertEqual(config.openai_base_url, "https://openai.example/v1")
        self.assertEqual(
            config.custom_webhook_body_template,
            '{"title":$title_json,"content":$content_json}',
        )

    def test_refresh_stock_list_preserves_empty_required_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("STOCK_LIST=\n", encoding="utf-8")

            config = Config(stock_list=["600519"])
            with patch.dict(os.environ, {"ENV_FILE": str(env_path)}, clear=True):
                config.refresh_stock_list()

        self.assertEqual(config.stock_list, [])
        issues = config.validate_structured()
        self.assertTrue(
            any(issue.severity == "error" and issue.field == "STOCK_LIST" for issue in issues)
        )

    def test_refresh_stock_list_accepts_runtime_env_common_separators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_env_path = Path(temp_dir) / "missing.env"
            config = Config(stock_list=["600519"])
            with patch.dict(
                os.environ,
                {
                    "ENV_FILE": str(missing_env_path),
                    "STOCK_LIST": "600519，300750 AAPL",
                },
                clear=True,
            ):
                config.refresh_stock_list()

        self.assertEqual(config.stock_list, ["600519", "300750", "AAPL"])

    def test_parse_report_language_accepts_known_alias_without_warning(self) -> None:
        with self.assertNoLogs("src.config", level="WARNING"):
            parsed = Config._parse_report_language("zh-cn")

        self.assertEqual(parsed, "zh")

    def test_parse_market_review_region_accepts_jp_kr_values_and_comma_lists(self) -> None:
        self.assertEqual(Config._parse_market_review_region("jp"), "jp")
        self.assertEqual(Config._parse_market_review_region("KR"), "kr")
        self.assertEqual(
            Config._parse_market_review_region("kr,jp,us"),
            "us,jp,kr",
        )
        self.assertEqual(
            Config._parse_market_review_region("cn,eu,us"),
            "cn,us",
        )
        self.assertEqual(
            Config._parse_market_review_region("both"),
            "cn,hk,us,jp,kr",
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_invalid_numeric_env_values_fall_back_to_defaults(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "AGENT_ORCHESTRATOR_TIMEOUT_S": "oops",
            "NEWS_MAX_AGE_DAYS": "bad",
            "MAX_WORKERS": "",
            "WEBUI_PORT": "invalid",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_orchestrator_timeout_s, 600)
        self.assertEqual(config.news_max_age_days, 3)
        self.assertEqual(config.max_workers, 3)
        self.assertEqual(config.webui_port, 8000)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_stock_email_groups_support_case_insensitive_env_names(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "STOCK_LIST": "600519,300750",
            "Stock_Group_1": "600519",
            "Email_Group_1": "user1@example.com",
            "stock_group_2": "300750",
            "email_group_2": "user2@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(
            config.stock_email_groups,
            [
                (["600519"], ["user1@example.com"]),
                (["300750"], ["user2@example.com"]),
            ],
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_stock_email_groups_normalize_codes_at_parse_time(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        """STOCK_GROUP codes are canonicalized at parse time so that
        runtime email routing matches the same equivalence used in
        validate_structured()."""
        env = {
            "STOCK_LIST": "600519,HK00700",
            "STOCK_GROUP_1": "SH600519,1810.HK",
            "EMAIL_GROUP_1": "user@example.com",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        stocks, emails = config.stock_email_groups[0]
        self.assertEqual(stocks, ["600519", "HK01810"])
        self.assertEqual(emails, ["user@example.com"])


if __name__ == "__main__":
    unittest.main()
