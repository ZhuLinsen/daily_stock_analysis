# -*- coding: utf-8 -*-
"""Env parsing for the screening runtime ``Config.from_env``."""

import os
import unittest
from unittest.mock import patch

from src.services.screening.config import Config as ScreeningPipelineConfig


class ScreeningConfigIntEnvTestCase(unittest.TestCase):
    def _from_env(self, env: dict) -> ScreeningPipelineConfig:
        with patch.dict(os.environ, env, clear=True):
            return ScreeningPipelineConfig.from_env()

    def test_blank_int_env_uses_default(self) -> None:
        # ``LLM_MAX_TOKENS=`` in a dotenv / docker env_file reaches os.environ as "".
        config = self._from_env(
            {
                "LLM_MAX_TOKENS": "",
                "LLM_MAX_RETRIES": "  ",
                "DAILY_LOOKBACK_DAYS": "",
                "DSA_TIMEOUT_SEC": "",
                "POST_ANALYZER_TIMEOUT_SEC": "",
            }
        )

        self.assertEqual(config.llm_max_tokens, 2048)
        self.assertEqual(config.llm_max_retries, 1)
        self.assertEqual(config.daily_lookback_days, 120)
        self.assertEqual(config.dsa_timeout_sec, 120.0)
        self.assertEqual(config.post_analyzer_timeout_sec, 120.0)

    def test_invalid_int_env_warns_and_uses_default(self) -> None:
        with self.assertLogs("src.config", level="WARNING") as logs:
            config = self._from_env({"LLM_MAX_TOKENS": "4k"})

        self.assertEqual(config.llm_max_tokens, 2048)
        self.assertIn("LLM_MAX_TOKENS", "\n".join(logs.output))

    def test_valid_int_env_and_minimum_clamp_unchanged(self) -> None:
        config = self._from_env({"LLM_MAX_TOKENS": "4096", "LLM_CONTEXT_MAX_CHARS": "100"})

        self.assertEqual(config.llm_max_tokens, 4096)
        self.assertEqual(config.llm_context_max_chars, 500)

    def test_blank_post_analysis_max_picks_falls_back_to_dsa_max_picks(self) -> None:
        config = self._from_env({"POST_ANALYSIS_MAX_PICKS": "", "DSA_MAX_PICKS": "5"})

        self.assertEqual(config.post_analysis_max_picks, 5)


if __name__ == "__main__":
    unittest.main()
