# -*- coding: utf-8 -*-
"""Tests for backward-compatible config env aliases and TickFlow loading."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config


class ConfigEnvCompatibilityTestCase(unittest.TestCase):
    def tearDown(self):
        Config.reset_instance()

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

    def test_parse_report_language_accepts_known_alias_without_warning(self) -> None:
        with self.assertNoLogs("src.config", level="WARNING"):
            parsed = Config._parse_report_language("zh-cn")

        self.assertEqual(parsed, "zh")

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


if __name__ == "__main__":
    unittest.main()
