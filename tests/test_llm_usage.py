# -*- coding: utf-8 -*-
"""Unit tests for LLM usage tracking (storage + analyzer helper)."""

import hashlib
import hmac as py_hmac
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub, remove_litellm_stub

remove_litellm_stub()
try:
    from litellm.types.utils import Usage
except ModuleNotFoundError:
    ensure_litellm_stub()
    from litellm.types.utils import Usage

from src.llm.usage import (
    attach_legacy_message_stability_audit,
    attach_message_hmacs,
    build_message_hmacs,
    extract_usage_payload,
    has_provider_usage_payload,
    normalize_litellm_usage,
    should_persist_usage_telemetry,
    _reset_usage_hmac_secret_cache_for_tests,
)
from src.llm.provider_cache import filter_prompt_cache_telemetry
from src.storage import (
    DatabaseManager,
    LLMUsage,
    persist_llm_usage,
    _LLM_USAGE_TELEMETRY_COLUMN_SQL,
)


def _fresh_db() -> DatabaseManager:
    """Return a DatabaseManager backed by a fresh in-memory SQLite database."""
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url="sqlite:///:memory:")
    return db


class TestExtractUsagePayload(unittest.TestCase):
    def test_extracts_public_usage_before_private_hidden_usage(self):
        top_level_usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), top_level_usage)

    def test_extracts_usage_metadata_before_private_hidden_usage(self):
        usage_metadata = {
            "prompt_token_count": 1,
            "candidates_token_count": 2,
            "total_token_count": 3,
        }
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=None,
            usage_metadata=usage_metadata,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), usage_metadata)

    def test_extracts_usage_metadata_when_public_usage_has_no_signal(self):
        top_level_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        usage_metadata = {
            "prompt_token_count": 1,
            "candidates_token_count": 2,
            "total_token_count": 3,
        }
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=usage_metadata,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), usage_metadata)

    def test_extracts_litellm_private_hidden_usage_from_object_chunk_best_effort(self):
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(usage=None, usage_metadata=None, _hidden_params={"usage": hidden_usage})

        self.assertIs(extract_usage_payload(response), hidden_usage)

    def test_extracts_private_hidden_usage_when_public_usage_is_zero_only(self):
        top_level_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), hidden_usage)

    def test_extracts_private_hidden_usage_object_when_public_object_is_zero_only(self):
        public_usage = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        hidden_usage = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)

        response = SimpleNamespace(
            usage=public_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), hidden_usage)

    def test_keeps_public_usage_when_nested_cache_signal_exists(self):
        top_level_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 500},
        }
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), top_level_usage)

    def test_keeps_invalid_public_usage_instead_of_hidden_usage(self):
        top_level_usage = {"prompt_tokens": True}
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), top_level_usage)

    def test_keeps_blank_public_usage_count_instead_of_hidden_usage(self):
        top_level_usage = {"prompt_tokens": "", "completion_tokens": 2, "total_tokens": 2}
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=None,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), top_level_usage)

    def test_keeps_invalid_public_usage_instead_of_usage_metadata(self):
        top_level_usage = {"prompt_tokens": True}
        usage_metadata = {
            "prompt_token_count": 1,
            "candidates_token_count": 2,
            "total_token_count": 3,
        }
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=usage_metadata,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), top_level_usage)

    def test_keeps_invalid_usage_metadata_instead_of_hidden_usage(self):
        top_level_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        usage_metadata = {"prompt_token_count": True}
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = SimpleNamespace(
            usage=top_level_usage,
            usage_metadata=usage_metadata,
            _hidden_params={"usage": hidden_usage},
        )

        self.assertIs(extract_usage_payload(response), usage_metadata)

    def test_extracts_litellm_private_hidden_usage_from_dict_chunk_best_effort(self):
        hidden_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

        response = {"usage": None, "usage_metadata": None, "_hidden_params": {"usage": hidden_usage}}

        self.assertIs(extract_usage_payload(response), hidden_usage)

    def test_returns_none_when_no_usage_payload_exists(self):
        response = SimpleNamespace(usage=None, usage_metadata=None, _hidden_params={})

        self.assertIsNone(extract_usage_payload(response))


class TestRecordLLMUsage(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()

    def tearDown(self):
        DatabaseManager.reset_instance()

    def test_record_single_row(self):
        self.db.record_llm_usage(
            call_type="analysis",
            model="gemini/gemini-2.5-flash",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            stock_code="600519",
        )
        with self.db.session_scope() as session:
            rows = session.query(LLMUsage).all()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.call_type, "analysis")
            self.assertEqual(row.model, "gemini/gemini-2.5-flash")
            self.assertEqual(row.stock_code, "600519")
            self.assertEqual(row.prompt_tokens, 100)
            self.assertEqual(row.completion_tokens, 200)
            self.assertEqual(row.total_tokens, 300)

    def test_record_without_stock_code(self):
        self.db.record_llm_usage(
            call_type="market_review",
            model="openai/gpt-4o",
            prompt_tokens=50,
            completion_tokens=150,
            total_tokens=200,
        )
        with self.db.session_scope() as session:
            rows = session.query(LLMUsage).all()
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0].stock_code)

    def test_record_multiple_rows(self):
        for i in range(5):
            self.db.record_llm_usage(
                call_type="agent",
                model="gemini/gemini-2.5-flash",
                prompt_tokens=10 * i,
                completion_tokens=20 * i,
                total_tokens=30 * i,
            )
        with self.db.session_scope() as session:
            count = session.query(LLMUsage).count()
            self.assertEqual(count, 5)


class TestLLMUsageNormalizer(unittest.TestCase):
    def test_openai_cached_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 2000,
                "completion_tokens": 100,
                "total_tokens": 2100,
                "prompt_tokens_details": {"cached_tokens": 500},
            },
            model="openai/gpt-4o",
        )

        self.assertEqual(usage["prompt_tokens"], 2000)
        self.assertEqual(usage["normalized_cache_read_tokens"], 500)
        self.assertEqual(usage["provider_reported_cached_tokens"], 500)
        self.assertEqual(usage["provider_min_cache_tokens"], 1024)
        self.assertEqual(usage["cache_eligibility"], "eligible")
        self.assertEqual(usage["cache_observation"], "partial_hit")
        self.assertEqual(usage["normalized_cache_hit_ratio"], 0.25)

    def test_openai_impossible_cache_counts_are_marked_invalid(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 2000,
                "completion_tokens": 10,
                "total_tokens": 2010,
                "prompt_tokens_details": {"cached_tokens": 5000},
            },
            model="openai/gpt-4o",
        )

        self.assertEqual(usage["provider_reported_prompt_tokens"], 2000)
        self.assertEqual(usage["provider_reported_cached_tokens"], 5000)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "invalid_provider_usage")
        self.assertEqual(usage["eligibility_confidence"], "invalid")
        self.assertIsNone(usage["normalized_cache_read_tokens"])
        self.assertIsNone(usage["normalized_uncached_input_tokens"])
        self.assertIsNone(usage["normalized_cache_hit_ratio"])

    def test_invalid_token_counts_are_marked_invalid(self):
        cases = [
            {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
            {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
            {"prompt_tokens": 1.5, "completion_tokens": 2, "total_tokens": 3.5},
            {"prompt_tokens": "", "completion_tokens": 2, "total_tokens": 2},
            {"prompt_tokens": "not-a-count", "completion_tokens": 2, "total_tokens": 3},
            {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": "3.5"},
        ]

        for payload in cases:
            with self.subTest(payload=payload):
                usage = normalize_litellm_usage(payload, model="openai/gpt-4o")

                self.assertEqual(usage["prompt_tokens"], 0)
                self.assertEqual(usage["completion_tokens"], 0)
                self.assertEqual(usage["total_tokens"], 0)
                self.assertIsNone(usage["normalized_prompt_tokens"])
                self.assertIsNone(usage["normalized_completion_tokens"])
                self.assertIsNone(usage["normalized_total_tokens"])
                self.assertEqual(usage["cache_observation"], "invalid_provider_usage")
                self.assertEqual(usage["eligibility_confidence"], "invalid")

    def test_impossible_total_tokens_are_marked_invalid(self):
        usage = normalize_litellm_usage(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 5},
            model="openai/gpt-4o",
        )

        self.assertEqual(usage["prompt_tokens"], 0)
        self.assertEqual(usage["completion_tokens"], 0)
        self.assertEqual(usage["total_tokens"], 0)
        self.assertEqual(usage["provider_reported_prompt_tokens"], 10)
        self.assertEqual(usage["cache_observation"], "invalid_provider_usage")
        self.assertEqual(usage["eligibility_confidence"], "invalid")

    def test_extra_total_tokens_are_not_marked_invalid(self):
        usage = normalize_litellm_usage(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 35},
            model="openai/gpt-4o",
        )

        self.assertEqual(usage["prompt_tokens"], 10)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 35)
        self.assertNotEqual(usage["cache_observation"], "invalid_provider_usage")

    def test_openai_below_threshold_does_not_fake_zero_hit(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
            model="openai/gpt-4o",
        )

        self.assertEqual(usage["cache_eligibility"], "below_threshold")
        self.assertIsNone(usage["normalized_cache_eligible_input_tokens"])
        self.assertEqual(usage["cache_observation"], "unknown")

    def test_openai_compatible_model_without_cache_field_keeps_cache_unknown(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1500,
                "completion_tokens": 1,
                "total_tokens": 1501,
            },
            model="openai/Qwen/Qwen3-235B-A22B-Thinking-2507",
            provider="openai",
        )

        self.assertEqual(usage["prompt_tokens"], 1500)
        self.assertEqual(usage["cache_capability"], "unknown")
        self.assertEqual(usage["cache_eligibility"], "unknown")
        self.assertEqual(usage["cache_observation"], "unknown")
        self.assertIsNone(usage["provider_min_cache_tokens"])
        self.assertIsNone(usage["normalized_cache_eligible_input_tokens"])
        self.assertIsNone(usage["normalized_cache_read_tokens"])

    def test_openai_compatible_cached_tokens_do_not_use_native_openai_threshold(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1500,
                "completion_tokens": 1,
                "total_tokens": 1501,
                "prompt_tokens_details": {"cached_tokens": 1500},
            },
            model="openai/Qwen/Qwen3-235B-A22B-Thinking-2507",
            provider="openai",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 1500)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_eligibility"], "eligible")
        self.assertEqual(usage["cache_observation"], "full_hit")
        self.assertIsNone(usage["provider_min_cache_tokens"])
        self.assertEqual(usage["normalized_cache_eligible_input_tokens"], 1500)

    def test_glm_cached_tokens_use_openai_shape(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1200,
                "completion_tokens": 80,
                "total_tokens": 1280,
                "prompt_tokens_details": {"cached_tokens": 1200},
            },
            model="zhipu/glm-4.5",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 1200)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "full_hit")

    def test_zhipu_provider_alias_uses_glm_cache_shape(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1200,
                "completion_tokens": 80,
                "total_tokens": 1280,
                "prompt_tokens_details": {"cached_tokens": 1200},
            },
            model="zhipu/glm-4.5",
            provider="zhipu",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 1200)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "full_hit")
        self.assertIsNone(usage["provider_min_cache_tokens"])

    def test_qwen_wrapped_openai_model_uses_openai_compatible_cache_shape(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1500,
                "completion_tokens": 200,
                "total_tokens": 1700,
                "prompt_tokens_details": {"cached_tokens": 1200},
            },
            model="openai/qwen-max",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 1200)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "partial_hit")

    def test_kimi_wrapped_openai_model_uses_top_level_cached_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1500,
                "completion_tokens": 200,
                "total_tokens": 1700,
                "cached_tokens": 300,
            },
            model="openai/kimi-k2",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 300)
        self.assertEqual(usage["cache_capability"], "supported")

    def test_openrouter_cache_read_write_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1500,
                "completion_tokens": 200,
                "total_tokens": 1700,
                "cache_read_tokens": 300,
                "cache_write_tokens": 100,
            },
            model="openai/~anthropic/claude-sonnet",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 300)
        self.assertEqual(usage["normalized_cache_write_tokens"], 100)
        self.assertEqual(usage["cache_capability"], "supported")

    def test_anthropic_official_cache_breakdown_sums_total_input(self):
        usage = normalize_litellm_usage(
            {
                "input_tokens": 100,
                "output_tokens": 30,
                "cache_read_input_tokens": 10,
                "cache_creation_input_tokens": 20,
            },
            model="anthropic/claude-3-5-sonnet",
        )

        # Anthropic defines total input as input + cache read + cache creation tokens.
        self.assertEqual(usage["prompt_tokens"], 130)
        self.assertEqual(usage["completion_tokens"], 30)
        self.assertEqual(usage["total_tokens"], 160)
        self.assertEqual(usage["normalized_cache_read_tokens"], 10)
        self.assertEqual(usage["normalized_cache_write_tokens"], 20)
        self.assertEqual(usage["normalized_uncached_input_tokens"], 100)
        self.assertEqual(usage["cache_observation"], "read_and_write")

    def test_anthropic_litellm_normalized_usage_keeps_prompt_tokens_without_input_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            model="anthropic/claude-3-5-sonnet",
        )

        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 120)
        self.assertEqual(usage["normalized_prompt_tokens"], 100)
        self.assertEqual(usage["normalized_cache_read_tokens"], 0)
        self.assertEqual(usage["normalized_cache_write_tokens"], 0)
        self.assertEqual(usage["normalized_uncached_input_tokens"], 100)
        self.assertEqual(usage["cache_observation"], "zero_hit")

    def test_anthropic_litellm_normalized_usage_derives_uncached_tokens_without_input_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 115,
                "completion_tokens": 20,
                "total_tokens": 135,
                "cache_read_input_tokens": 10,
                "cache_creation_input_tokens": 5,
            },
            model="anthropic/claude-3-5-sonnet",
        )

        self.assertEqual(usage["prompt_tokens"], 115)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 135)
        self.assertEqual(usage["normalized_prompt_tokens"], 115)
        self.assertEqual(usage["normalized_cache_read_tokens"], 10)
        self.assertEqual(usage["normalized_cache_write_tokens"], 5)
        self.assertEqual(usage["normalized_uncached_input_tokens"], 100)
        self.assertEqual(usage["cache_observation"], "read_and_write")

    def test_gemini_usage_metadata(self):
        payload = {
            "usage_metadata": {
                "prompt_token_count": 1000,
                "candidates_token_count": 50,
                "total_token_count": 1050,
                "cached_content_token_count": 32,
            }
        }

        usage = normalize_litellm_usage(
            extract_usage_payload(payload),
            model="gemini/gemini-2.5-flash",
        )

        self.assertEqual(usage["prompt_tokens"], 1000)
        self.assertEqual(usage["completion_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 1050)
        self.assertEqual(usage["normalized_cache_read_tokens"], 32)
        self.assertEqual(usage["cache_observation"], "partial_hit")

    def test_gemini_litellm_usage_cache_read_input_tokens(self):
        usage = normalize_litellm_usage(
            Usage(
                prompt_tokens=1000,
                completion_tokens=50,
                total_tokens=1050,
                cache_read_input_tokens=32,
            ),
            model="gemini/gemini-2.5-flash",
        )

        self.assertEqual(usage["prompt_tokens"], 1000)
        self.assertEqual(usage["completion_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 1050)
        self.assertEqual(usage["normalized_cache_read_tokens"], 32)
        self.assertEqual(usage["provider_reported_cached_tokens"], 32)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "partial_hit")
        raw = json.loads(usage["provider_usage_json"])
        self.assertTrue(
            raw.get("cache_read_input_tokens") == 32
            or raw.get("prompt_tokens_details", {}).get("cached_tokens") == 32
        )

    def test_vertex_ai_gemini_usage_uses_gemini_cache_shape(self):
        usage = normalize_litellm_usage(
            Usage(
                prompt_tokens=1000,
                completion_tokens=50,
                total_tokens=1050,
                cache_read_input_tokens=32,
            ),
            model="vertex_ai/gemini-2.5-flash",
            provider="vertex_ai",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 32)
        self.assertEqual(usage["provider_reported_cached_tokens"], 32)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "partial_hit")

    def test_gemini_litellm_usage_zero_cache_hit(self):
        usage = normalize_litellm_usage(
            Usage(
                prompt_tokens=1000,
                completion_tokens=50,
                total_tokens=1050,
                cache_read_input_tokens=0,
            ),
            model="gemini/gemini-2.5-flash",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 0)
        self.assertEqual(usage["provider_reported_cached_tokens"], 0)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "zero_hit")

    def test_gemini_prompt_tokens_details_cached_tokens_fallback(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "total_tokens": 1050,
                "prompt_tokens_details": {"cached_tokens": 32},
            },
            model="gemini/gemini-2.5-flash",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 32)
        self.assertEqual(usage["provider_reported_cached_tokens"], 32)
        self.assertEqual(usage["cache_capability"], "supported")
        self.assertEqual(usage["cache_observation"], "partial_hit")

    def test_deepseek_hit_miss_tokens(self):
        usage = normalize_litellm_usage(
            {
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
            model="deepseek/deepseek-chat",
        )

        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["total_tokens"], 110)
        self.assertEqual(usage["normalized_cache_read_tokens"], 40)
        self.assertEqual(usage["normalized_cache_miss_tokens"], 60)
        self.assertEqual(usage["normalized_uncached_input_tokens"], 60)

    def test_openai_deepseek_hit_miss_tokens_use_payload_shape(self):
        usage = normalize_litellm_usage(
            {
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
            model="openai/deepseek-chat",
        )

        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["total_tokens"], 110)
        self.assertEqual(usage["normalized_cache_read_tokens"], 40)
        self.assertEqual(usage["normalized_cache_miss_tokens"], 60)
        self.assertEqual(usage["normalized_uncached_input_tokens"], 60)
        self.assertEqual(usage["cache_capability"], "supported")

    def test_deepseek_hit_miss_does_not_override_provider_prompt_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "total_tokens": 60,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
            model="openai/deepseek-chat",
        )

        self.assertEqual(usage["cache_observation"], "invalid_provider_usage")
        self.assertEqual(usage["eligibility_confidence"], "invalid")
        self.assertEqual(usage["prompt_tokens"], 0)
        self.assertEqual(usage["completion_tokens"], 0)
        self.assertEqual(usage["total_tokens"], 0)
        self.assertEqual(usage["provider_reported_prompt_tokens"], 50)
        self.assertEqual(usage["provider_reported_cached_tokens"], 40)

    def test_stepfun_top_level_cached_tokens(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 900,
                "completion_tokens": 100,
                "total_tokens": 1000,
                "cached_tokens": 300,
            },
            model="stepfun/step-2",
        )

        self.assertEqual(usage["normalized_cache_read_tokens"], 300)
        self.assertEqual(usage["cache_capability"], "supported")

    def test_unknown_provider_keeps_cache_unknown(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        self.assertEqual(usage["prompt_tokens"], 1000)
        self.assertIsNone(usage["normalized_cache_read_tokens"])
        self.assertIsNone(usage["normalized_cache_miss_tokens"])
        self.assertEqual(usage["cache_capability"], "unknown")
        self.assertEqual(usage["cache_observation"], "unknown")

    def test_has_provider_usage_payload_detects_real_usage_signals(self):
        self.assertTrue(has_provider_usage_payload({"total_tokens": 5}))
        self.assertTrue(has_provider_usage_payload({"normalized_total_tokens": 5}))
        self.assertTrue(has_provider_usage_payload({"provider_usage_json": '{"prompt_tokens":1}'}))
        self.assertTrue(has_provider_usage_payload({"normalized_cache_read_tokens": 5}))
        self.assertTrue(has_provider_usage_payload({"normalized_cache_write_tokens": 5}))
        self.assertTrue(has_provider_usage_payload({"normalized_cache_miss_tokens": 5}))
        self.assertTrue(has_provider_usage_payload({"provider_reported_cached_tokens": 5}))
        self.assertTrue(
            has_provider_usage_payload(
                {"provider_usage_json": '{"prompt_tokens_details":{"cached_tokens":1}}'}
            )
        )
        self.assertTrue(has_provider_usage_payload({"provider_usage_json": '{"cache_read_input_tokens":1}'}))
        self.assertTrue(has_provider_usage_payload({"provider_usage_json": '{"prompt_cache_hit_tokens":1}'}))
        self.assertTrue(
            has_provider_usage_payload(
                {"provider_usage_json": '{"prompt_tokens":1000,"cache_read_input_tokens":0}'}
            )
        )
        self.assertFalse(has_provider_usage_payload({"prompt_tokens": True}))
        self.assertFalse(has_provider_usage_payload({"prompt_tokens": -1}))
        self.assertFalse(has_provider_usage_payload({"provider_usage_json": '{"prompt_tokens":-1}'}))

    def test_has_provider_usage_payload_ignores_empty_hmac_and_cache_metadata(self):
        self.assertFalse(has_provider_usage_payload(None))
        self.assertFalse(has_provider_usage_payload({}))
        self.assertFalse(
            has_provider_usage_payload(
                {
                    "messages_hmac": "a" * 64,
                    "system_message_hmac": None,
                    "user_message_hmac": "b" * 64,
                    "hmac_key_version": "local-v1",
                    "hmac_domain": "prompt_message",
                    "hash_scope": "deployment",
                }
            )
        )
        for provider_usage_json in (
            '{"estimated_prefix_tokens":123}',
            '{"tokenizer_name":"cl100k_base","tokenizer_version":"v1"}',
            '{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}',
            '{"cache_read_input_tokens":0}',
            '{"prompt_tokens_details":{"cached_tokens":0}}',
            '{"_truncated":true,"_original_size_bytes":8192}',
            '{not valid json',
            '["prompt_tokens",1]',
            '"prompt_tokens"',
            "1",
        ):
            self.assertFalse(has_provider_usage_payload({"provider_usage_json": provider_usage_json}))
        self.assertFalse(
            has_provider_usage_payload(
                {
                    "cache_observation": "no_usage",
                    "cache_capability": "unknown",
                    "normalized_cache_read_tokens": None,
                }
            )
        )

    def test_has_provider_usage_payload_ignores_normalized_metadata_only_usage(self):
        usage = normalize_litellm_usage(
            {"estimated_prefix_tokens": 123},
            model="openai/gpt-4o",
        )

        self.assertEqual(json.loads(usage["provider_usage_json"]), {"estimated_prefix_tokens": 123})
        self.assertFalse(has_provider_usage_payload(usage))

    def test_has_provider_usage_payload_ignores_normalized_no_usage_shape(self):
        usage = normalize_litellm_usage(None, model="openai/gpt-4o")

        self.assertEqual(usage["cache_observation"], "no_usage")
        self.assertEqual(usage["total_tokens"], 0)
        self.assertFalse(has_provider_usage_payload(usage))

    def test_should_persist_usage_telemetry_keeps_invalid_diagnostics_only(self):
        invalid_usage = normalize_litellm_usage({"prompt_tokens": -1}, model="openai/gpt-4o")
        no_usage = normalize_litellm_usage(None, model="openai/gpt-4o")
        metadata_only = normalize_litellm_usage(
            {"estimated_prefix_tokens": 123},
            model="openai/gpt-4o",
        )

        self.assertFalse(has_provider_usage_payload(invalid_usage))
        self.assertTrue(should_persist_usage_telemetry(invalid_usage))
        self.assertFalse(should_persist_usage_telemetry(no_usage))
        self.assertFalse(should_persist_usage_telemetry(metadata_only))

    def test_provider_usage_json_preserves_allowlisted_usage_cache_shapes(self):
        cases = [
            (
                "openai",
                {
                    "prompt_tokens": 2000,
                    "completion_tokens": 100,
                    "total_tokens": 2100,
                    "prompt_tokens_details": {"cached_tokens": 500},
                },
                "openai/gpt-4o",
                {"prompt_tokens": 2000, "prompt_tokens_details": {"cached_tokens": 500}},
            ),
            (
                "anthropic",
                {
                    "input_tokens": 100,
                    "output_tokens": 30,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 20,
                },
                "anthropic/claude-3-5-sonnet",
                {
                    "input_tokens": 100,
                    "output_tokens": 30,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 20,
                },
            ),
            (
                "gemini",
                {
                    "prompt_token_count": 1000,
                    "candidates_token_count": 50,
                    "total_token_count": 1050,
                    "cached_content_token_count": 32,
                },
                "gemini/gemini-2.5-flash",
                {
                    "prompt_token_count": 1000,
                    "candidates_token_count": 50,
                    "total_token_count": 1050,
                    "cached_content_token_count": 32,
                },
            ),
            (
                "deepseek",
                {
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                },
                "deepseek/deepseek-chat",
                {
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                },
            ),
            (
                "stepfun",
                {
                    "prompt_tokens": 900,
                    "completion_tokens": 100,
                    "total_tokens": 1000,
                    "cached_tokens": 300,
                },
                "stepfun/step-2",
                {
                    "prompt_tokens": 900,
                    "completion_tokens": 100,
                    "total_tokens": 1000,
                    "cached_tokens": 300,
                },
            ),
        ]

        for name, payload, model, expected_subset in cases:
            with self.subTest(name=name):
                usage = normalize_litellm_usage(payload, model=model)
                raw = usage["provider_usage_json"]
                self.assertIsNotNone(raw)
                parsed = json.loads(raw)
                for key, expected in expected_subset.items():
                    self.assertEqual(parsed[key], expected)

    def test_raw_usage_drops_unmodeled_metadata_before_size_limit(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1,
                "prompt_tokens_details": {"cached_tokens": 1},
                "metadata": {"plain_url": "https://example.test/path?token_count=2"},
                "nested": {"safe_count": 2},
                "headers": {"authorization": "Bearer secret"},
                "large": "x" * 5000,
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed, {"prompt_tokens": 1, "prompt_tokens_details": {"cached_tokens": 1}})
        self.assertNotIn("_truncated", parsed)
        self.assertNotIn("example.test", raw)
        self.assertNotIn("safe_count", raw)
        self.assertNotIn("authorization", raw)
        self.assertNotIn("x" * 100, raw)

    def test_raw_usage_drops_tokenizer_free_text_fields(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "api_key": "sk-secret",
                "headers": {"authorization": "Bearer secret"},
                "raw_prompt": "do not persist this prompt",
                "nested": {"raw_user_input": "do not persist this user input"},
                "tokenizer_name": "cl100k_base prompt fragment",
                "tokenizer_version": "Authorization: Bearer sk-header",
            },
            model="gateway/custom-model",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        self.assertLessEqual(len(raw.encode("utf-8")), 4096)
        self.assertNotIn("sk-secret", raw)
        self.assertNotIn("authorization", raw)
        self.assertNotIn("do not persist this prompt", raw)
        self.assertNotIn("do not persist this user input", raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed, {"completion_tokens": 2, "prompt_tokens": 1, "total_tokens": 3})
        self.assertNotIn("tokenizer_name", parsed)
        self.assertNotIn("tokenizer_version", parsed)

    def test_raw_usage_drops_unmodeled_prompt_message_content_fields(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
                "prompt": "SECRET_PROMPT",
                "messages": [{"role": "user", "content": "SECRET_MESSAGE"}],
                "content": "SECRET_CONTENT",
                "input": "SECRET_INPUT",
                "output": "SECRET_OUTPUT",
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        self.assertNotIn("SECRET_PROMPT", raw)
        self.assertNotIn("SECRET_MESSAGE", raw)
        self.assertNotIn("SECRET_CONTENT", raw)
        self.assertNotIn("SECRET_INPUT", raw)
        self.assertNotIn("SECRET_OUTPUT", raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed, {"completion_tokens": 2, "prompt_tokens": 3, "total_tokens": 5})

    def test_raw_usage_sanitizes_forbidden_key_variants(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1,
                "apiKey": "sk-secret",
                "x-api-key": "sk-secondary",
                "requestBody": "raw request payload",
                "responseText": "raw model response",
                "webhook_url": "https://example.test/hook",
                "nested": {
                    "rawUserInput": "private user input",
                    "safe_count": 2,
                },
            },
            model="gateway/custom-model",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        self.assertNotIn("sk-secret", raw)
        self.assertNotIn("sk-secondary", raw)
        self.assertNotIn("raw request payload", raw)
        self.assertNotIn("raw model response", raw)
        self.assertNotIn("example.test/hook", raw)
        self.assertNotIn("private user input", raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["prompt_tokens"], 1)
        self.assertNotIn("nested", parsed)

    def test_raw_usage_drops_invalid_count_string_values(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1,
                "completion_tokens": "2",
                "total_tokens": "3",
                "cached_tokens": "not-a-count",
                "prompt_tokens_details": {
                    "cached_tokens": "https://hooks.slack.com/services/T000/B000/secret",
                    "audio_tokens": "4",
                },
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        parsed = json.loads(raw)
        self.assertEqual(
            parsed,
            {
                "completion_tokens": 2,
                "prompt_tokens": 1,
                "prompt_tokens_details": {"audio_tokens": 4},
                "total_tokens": 3,
            },
        )
        self.assertNotIn("cached_tokens", parsed)
        self.assertNotIn("hooks.slack.com", raw)

    def test_raw_usage_drops_invalid_nested_count_urls(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 1,
                "prompt_tokens_details": {
                    "cached_tokens": "https://sctapi.ftqq.com/SCTSECRET.send?title=x",
                    "audio_tokens": "https://hooks.internal.example/path/secret",
                    "text_tokens": 5,
                },
                "completion_tokens_details": {
                    "reasoning_tokens": "6",
                },
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        raw = usage["provider_usage_json"]
        self.assertIsNotNone(raw)
        self.assertNotIn("sctapi.ftqq.com", raw)
        self.assertNotIn("hooks.internal.example", raw)
        parsed = json.loads(raw)
        self.assertEqual(
            parsed,
            {
                "completion_tokens_details": {"reasoning_tokens": 6},
                "prompt_tokens": 1,
                "prompt_tokens_details": {"text_tokens": 5},
            },
        )


class TestLLMUsageHMAC(unittest.TestCase):
    def tearDown(self):
        _reset_usage_hmac_secret_cache_for_tests()

    def test_hmac_sha256_is_used_without_raw_prompt_storage(self):
        messages = [
            {"role": "system", "content": "system policy"},
            {"role": "user", "content": "user prompt"},
        ]
        with patch.dict(
            os.environ,
            {
                "LLM_USAGE_HMAC_SECRET": "test-secret",
                "LLM_USAGE_HMAC_KEY_VERSION": "test-v1",
            },
            clear=False,
        ):
            _reset_usage_hmac_secret_cache_for_tests()
            fields = build_message_hmacs(messages, hash_scope="local_debug")

        expected_payload = json.dumps(
            messages,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = py_hmac.new(
            b"test-secret",
            expected_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        self.assertEqual(fields["messages_hmac"], expected)
        self.assertEqual(len(fields["messages_hmac"]), 64)
        self.assertEqual(fields["hmac_key_version"], "test-v1")
        self.assertEqual(fields["hmac_domain"], "prompt_message")
        self.assertEqual(fields["hash_scope"], "local_debug")
        self.assertNotIn("user prompt", json.dumps(fields))

    def test_hmac_covers_tool_and_provider_wire_fields(self):
        first_messages = [
            {
                "role": "assistant",
                "content": "same",
                "_trace_provider": "anthropic",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                        "provider_specific_fields": {"thought_signature": "sig-a"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "same result"},
        ]
        second_messages = [
            {
                "role": "assistant",
                "content": "same",
                "_trace_provider": "anthropic",
                "tool_calls": [
                    {
                        "id": "call_b",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"n":1}'},
                        "provider_specific_fields": {"thought_signature": "sig-b"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_b", "content": "same result"},
        ]
        with patch.dict(os.environ, {"LLM_USAGE_HMAC_SECRET": "tool-secret"}, clear=False):
            first = build_message_hmacs(first_messages)
            first_again = build_message_hmacs(first_messages)
            second = build_message_hmacs(second_messages)

        self.assertEqual(first["messages_hmac"], first_again["messages_hmac"])
        self.assertNotEqual(first["messages_hmac"], second["messages_hmac"])

    def test_hmac_ignores_internal_trace_metadata(self):
        base_messages = [{"role": "assistant", "content": "same"}]
        traced_messages = [
            {
                "role": "assistant",
                "content": "same",
                "_trace_provider": "anthropic",
                "_trace_model": "anthropic/claude-test",
            }
        ]
        with patch.dict(os.environ, {"LLM_USAGE_HMAC_SECRET": "trace-secret"}, clear=False):
            base = build_message_hmacs(base_messages)
            traced = build_message_hmacs(traced_messages)

        self.assertEqual(base["messages_hmac"], traced["messages_hmac"])

    def test_missing_env_uses_generated_local_secret_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "stock_analysis.db"
            secret_path = Path(tmpdir) / ".llm_usage_hmac_secret"
            with patch.dict(os.environ, {"DATABASE_PATH": str(db_path)}, clear=True):
                _reset_usage_hmac_secret_cache_for_tests()
                fields = build_message_hmacs([{"role": "user", "content": "hello"}])

            self.assertTrue(secret_path.exists())
            self.assertEqual(secret_path.stat().st_size, 32)
            self.assertEqual(len(fields["messages_hmac"]), 64)
            self.assertEqual(fields["hmac_key_version"], "local-v1")

    def test_empty_generated_secret_file_is_regenerated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "stock_analysis.db"
            secret_path = Path(tmpdir) / ".llm_usage_hmac_secret"
            secret_path.write_bytes(b"")
            with patch.dict(os.environ, {"DATABASE_PATH": str(db_path)}, clear=True):
                _reset_usage_hmac_secret_cache_for_tests()
                fields = build_message_hmacs([{"role": "user", "content": "hello"}])

            self.assertEqual(secret_path.stat().st_size, 32)
            self.assertEqual(len(fields["messages_hmac"]), 64)
            self.assertEqual(fields["hmac_key_version"], "local-v1")

    def test_key_version_is_part_of_hash_comparability_tuple(self):
        messages = [{"role": "user", "content": "same message"}]
        with patch.dict(
            os.environ,
            {
                "LLM_USAGE_HMAC_SECRET": "same-secret",
                "LLM_USAGE_HMAC_KEY_VERSION": "v1",
            },
            clear=False,
        ):
            first = build_message_hmacs(messages)
        with patch.dict(
            os.environ,
            {
                "LLM_USAGE_HMAC_SECRET": "same-secret",
                "LLM_USAGE_HMAC_KEY_VERSION": "v2",
            },
            clear=False,
        ):
            second = build_message_hmacs(messages)

        self.assertEqual(first["messages_hmac"], second["messages_hmac"])
        self.assertNotEqual(
            (first["hmac_key_version"], first["messages_hmac"]),
            (second["hmac_key_version"], second["messages_hmac"]),
        )


class TestLegacyMessageStabilityAudit(unittest.TestCase):
    def setUp(self):
        self._hmac_secret_patch = patch.dict(
            os.environ,
            {"LLM_USAGE_HMAC_SECRET": "audit-secret"},
            clear=False,
        )
        self._hmac_secret_patch.start()
        _reset_usage_hmac_secret_cache_for_tests()

    def tearDown(self):
        self._hmac_secret_patch.stop()
        _reset_usage_hmac_secret_cache_for_tests()
        DatabaseManager.reset_instance()

    def _messages(self):
        return [
            {"role": "system", "content": "system policy for zh stock analysis"},
            {
                "role": "user",
                "content": (
                    "# 决策仪表盘分析请求\n\n"
                    "## 📊 股票基础信息\n"
                    "| 股票代码 | **600519** |\n"
                    "| 股票名称 | **贵州茅台** |\n"
                    "| 分析日期 | 2026-06-19 |\n\n"
                    "## 📈 技术面数据\n"
                    "收盘价 1500 元\n\n"
                    "## 📰 舆情情报\n"
                    "IMPORTANT_NEWS_TEXT\n"
                ),
            },
        ]

    def _audit_context(self):
        return {
            "language": "zh",
            "market_group": "cn",
            "analysis_mode": "stock_analysis",
            "legacy_prompt_mode": "skill_aware",
            "skill_config": {
                "skill_instructions": "RSI breakout skill raw instructions",
                "default_skill_policy": "Default skill policy raw text",
                "use_legacy_default_prompt": False,
            },
            "provider": "gemini",
            "transport": "litellm",
            "dynamic_markers": [
                {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
                {"marker_name": "stock_name", "message_role": "user", "text": "贵州茅台"},
                {"marker_name": "analysis_date", "message_role": "user", "text": "2026-06-19"},
                {"marker_name": "quote", "message_role": "user", "text": "## 📈 技术面数据"},
                {"marker_name": "news_context", "message_role": "user", "text": "IMPORTANT_NEWS_TEXT"},
                {"marker_name": "raw-header", "message_role": "user", "text": "Authorization: Bearer token"},
            ],
        }

    def test_attaches_hmac_and_internal_audit_fields_without_raw_marker_values(self):
        usage = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            self._audit_context(),
        )

        self.assertEqual(usage["language"], "zh")
        self.assertEqual(usage["market_group"], "cn")
        self.assertEqual(usage["analysis_mode"], "stock_analysis")
        self.assertEqual(usage["legacy_prompt_mode"], "skill_aware")
        self.assertEqual(len(usage["skill_config_hmac"]), 64)
        self.assertEqual(usage["provider"], "gemini")
        self.assertEqual(usage["transport"], "litellm")
        self.assertEqual(usage["message_count"], 2)
        self.assertGreater(usage["estimated_total_prompt_tokens"], 0)
        self.assertIsNotNone(usage["approx_common_prefix_chars"])
        self.assertIsNotNone(usage["approx_common_prefix_tokens"])
        self.assertEqual(usage["eligibility_confidence"], "estimated")
        self.assertEqual(len(usage["messages_hmac"]), 64)
        self.assertEqual(len(usage["system_message_hmac"]), 64)
        self.assertEqual(len(usage["user_message_hmac"]), 64)

        marker_json = usage["known_dynamic_marker_positions"]
        self.assertIsInstance(marker_json, str)
        markers = json.loads(marker_json)
        self.assertEqual(
            {tuple(marker.keys()) for marker in markers},
            {("marker_name", "message_role", "char_offset")},
        )
        self.assertEqual(markers[0]["marker_name"], "stock_code")
        self.assertEqual(markers[0]["message_role"], "user")
        self.assertIsInstance(markers[0]["char_offset"], int)

        serialized = json.dumps(usage, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("600519", marker_json)
        self.assertNotIn("贵州茅台", marker_json)
        self.assertNotIn("2026-06-19", marker_json)
        self.assertNotIn("IMPORTANT_NEWS_TEXT", marker_json)
        self.assertNotIn("RSI breakout skill raw instructions", serialized)
        self.assertNotIn("Default skill policy raw text", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("Bearer", serialized)

    def test_skill_config_hmac_changes_when_resolved_skill_config_changes(self):
        base_context = self._audit_context()
        changed_context = dict(base_context)
        changed_context["skill_config"] = dict(base_context["skill_config"])
        changed_context["skill_config"]["skill_instructions"] = "Different resolved skill instructions"

        first = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            base_context,
        )
        second = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            changed_context,
        )

        self.assertEqual(first["messages_hmac"], second["messages_hmac"])
        self.assertNotEqual(first["skill_config_hmac"], second["skill_config_hmac"])

    def test_common_prefix_estimate_uses_canonical_render_before_first_marker(self):
        messages = self._messages()
        usage = attach_legacy_message_stability_audit(
            {},
            messages,
            self._audit_context(),
        )
        user_content = messages[1]["content"]
        first_marker_offset = user_content.index("600519")

        self.assertGreater(usage["approx_common_prefix_chars"], first_marker_offset)
        self.assertEqual(
            usage["approx_common_prefix_tokens"],
            (usage["approx_common_prefix_chars"] + 2) // 3,
        )

    def test_empty_preferred_marker_list_does_not_fall_back_to_other_marker_keys(self):
        context = dict(self._audit_context())
        context["known_dynamic_markers"] = []
        context["markers"] = [
            {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
        ]

        usage = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            context,
        )

        self.assertEqual(json.loads(usage["known_dynamic_marker_positions"]), [])
        self.assertIsNone(usage["approx_common_prefix_chars"])
        self.assertIsNone(usage["approx_common_prefix_tokens"])

    def test_preserves_exact_and_invalid_provider_usage_confidence(self):
        messages = self._messages()
        exact = attach_legacy_message_stability_audit(
            normalize_litellm_usage({"prompt_tokens": 9}, model="openai/gpt-4o"),
            messages,
            self._audit_context(),
        )
        invalid = attach_legacy_message_stability_audit(
            normalize_litellm_usage({"prompt_tokens": -1}, model="openai/gpt-4o"),
            messages,
            self._audit_context(),
        )

        self.assertEqual(exact["eligibility_confidence"], "exact")
        self.assertEqual(invalid["eligibility_confidence"], "invalid")

    def test_persisted_marker_positions_remain_json_string(self):
        usage = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            self._audit_context(),
        )
        db = _fresh_db()
        persist_llm_usage(usage, "gemini/gemini-test", call_type="analysis", stock_code="600519")

        with db.session_scope() as session:
            row = session.query(LLMUsage).one()
            persisted = {
                "language": row.language,
                "market_group": row.market_group,
                "analysis_mode": row.analysis_mode,
                "legacy_prompt_mode": row.legacy_prompt_mode,
                "skill_config_hmac": row.skill_config_hmac,
                "provider": row.provider,
                "transport": row.transport,
                "message_count": row.message_count,
                "known_dynamic_marker_positions": row.known_dynamic_marker_positions,
            }

        self.assertEqual(persisted["language"], "zh")
        self.assertEqual(persisted["market_group"], "cn")
        self.assertEqual(persisted["analysis_mode"], "stock_analysis")
        self.assertEqual(persisted["legacy_prompt_mode"], "skill_aware")
        self.assertEqual(len(persisted["skill_config_hmac"]), 64)
        self.assertEqual(persisted["provider"], "gemini")
        self.assertEqual(persisted["transport"], "litellm")
        self.assertEqual(persisted["message_count"], 2)
        self.assertIsInstance(persisted["known_dynamic_marker_positions"], str)
        parsed = json.loads(persisted["known_dynamic_marker_positions"])
        self.assertEqual(parsed[0]["marker_name"], "stock_code")
        self.assertNotIn("600519", persisted["known_dynamic_marker_positions"])

    def test_does_not_emit_block_level_p05b_fields(self):
        usage = attach_legacy_message_stability_audit(
            {},
            self._messages(),
            self._audit_context(),
        )

        for field in (
            "block_id",
            "stability_class",
            "static_prefix_hash",
            "dynamic_context_hash",
        ):
            self.assertNotIn(field, usage)


class TestGetLLMUsageSummary(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # 3 analysis calls today
        for _ in range(3):
            row = LLMUsage(
                call_type="analysis",
                model="gemini/gemini-2.5-flash",
                prompt_tokens=100,
                completion_tokens=200,
                total_tokens=300,
                called_at=now,
            )
            with self.db.session_scope() as session:
                session.add(row)

        # 2 agent calls today
        for _ in range(2):
            row = LLMUsage(
                call_type="agent",
                model="openai/gpt-4o",
                prompt_tokens=50,
                completion_tokens=100,
                total_tokens=150,
                called_at=now,
            )
            with self.db.session_scope() as session:
                session.add(row)

        # 1 old call that should be excluded
        old_row = LLMUsage(
            call_type="analysis",
            model="gemini/gemini-2.5-flash",
            prompt_tokens=999,
            completion_tokens=999,
            total_tokens=999,
            called_at=yesterday,
        )
        with self.db.session_scope() as session:
            session.add(old_row)

    def tearDown(self):
        DatabaseManager.reset_instance()

    def _today_range(self):
        now = datetime.now()
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now

    def test_total_calls_and_tokens(self):
        from_dt, to_dt = self._today_range()
        result = self.db.get_llm_usage_summary(from_dt, to_dt)
        self.assertEqual(result["total_calls"], 5)
        # 3*300 + 2*150 = 900 + 300 = 1200
        self.assertEqual(result["total_tokens"], 1200)

    def test_by_call_type(self):
        from_dt, to_dt = self._today_range()
        result = self.db.get_llm_usage_summary(from_dt, to_dt)
        by_type = {r["call_type"]: r for r in result["by_call_type"]}
        self.assertIn("analysis", by_type)
        self.assertIn("agent", by_type)
        self.assertEqual(by_type["analysis"]["calls"], 3)
        self.assertEqual(by_type["analysis"]["total_tokens"], 900)
        self.assertEqual(by_type["agent"]["calls"], 2)
        self.assertEqual(by_type["agent"]["total_tokens"], 300)

    def test_by_model(self):
        from_dt, to_dt = self._today_range()
        result = self.db.get_llm_usage_summary(from_dt, to_dt)
        by_model = {r["model"]: r for r in result["by_model"]}
        self.assertEqual(by_model["gemini/gemini-2.5-flash"]["calls"], 3)
        self.assertEqual(by_model["openai/gpt-4o"]["calls"], 2)


    def test_token_totals_include_prompt_completion_and_model_peak(self):
        from_dt, to_dt = self._today_range()
        result = self.db.get_llm_usage_summary(from_dt, to_dt)
        self.assertEqual(result["total_prompt_tokens"], 400)
        self.assertEqual(result["total_completion_tokens"], 800)
        by_model = {r["model"]: r for r in result["by_model"]}
        self.assertEqual(by_model["gemini/gemini-2.5-flash"]["prompt_tokens"], 300)
        self.assertEqual(by_model["gemini/gemini-2.5-flash"]["completion_tokens"], 600)
        self.assertEqual(by_model["gemini/gemini-2.5-flash"]["max_total_tokens"], 300)

    def test_get_llm_usage_records_returns_recent_rows_with_limit(self):
        from_dt, to_dt = self._today_range()
        rows = self.db.get_llm_usage_records(from_dt, to_dt, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["called_at"] >= from_dt for row in rows))
        self.assertIn(rows[0]["call_type"], {"analysis", "agent"})
        self.assertIn("prompt_tokens", rows[0])
        self.assertIn("completion_tokens", rows[0])

    def test_empty_range_returns_zeros(self):
        future = datetime(2099, 1, 1)
        result = self.db.get_llm_usage_summary(future, future)
        self.assertEqual(result["total_calls"], 0)
        self.assertEqual(result["total_tokens"], 0)
        self.assertEqual(result["by_call_type"], [])
        self.assertEqual(result["by_model"], [])


class TestPersistUsageHelper(unittest.TestCase):
    """Test that _persist_usage swallows exceptions and writes correctly."""

    def setUp(self):
        self.db = _fresh_db()

    def tearDown(self):
        DatabaseManager.reset_instance()

    def test_persist_usage_writes_row(self):
        persist_llm_usage(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "gemini/gemini-2.5-flash",
            call_type="analysis",
            stock_code="000001",
        )
        with self.db.session_scope() as session:
            rows = session.query(LLMUsage).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].total_tokens, 30)

    def test_persist_usage_handles_empty_usage(self):
        # Should not raise even with an empty dict
        persist_llm_usage({}, "unknown", call_type="agent")
        with self.db.session_scope() as session:
            rows = session.query(LLMUsage).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].total_tokens, 0)
            self.assertEqual(rows[0].cache_capability, "unknown")
            self.assertEqual(rows[0].cache_eligibility, "unknown")
            self.assertEqual(rows[0].cache_observation, "no_usage")

    def test_persist_usage_coerces_invalid_token_counts_to_safe_summary_values(self):
        persist_llm_usage(
            {
                "prompt_tokens": -5,
                "completion_tokens": True,
                "total_tokens": "3.5",
                "normalized_prompt_tokens": -5,
                "normalized_completion_tokens": True,
                "normalized_total_tokens": "3.5",
                "cache_observation": "invalid_provider_usage",
            },
            "openai/gpt-4o",
            call_type="analysis",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertEqual(row.prompt_tokens, 0)
            self.assertEqual(row.completion_tokens, 0)
            self.assertEqual(row.total_tokens, 0)
            self.assertEqual(row.normalized_prompt_tokens, 0)
            self.assertEqual(row.normalized_completion_tokens, 0)
            self.assertEqual(row.normalized_total_tokens, 0)
            self.assertEqual(row.cache_observation, "invalid_provider_usage")

    def test_persist_usage_writes_new_telemetry_fields(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 2000,
                "completion_tokens": 100,
                "total_tokens": 2100,
                "prompt_tokens_details": {"cached_tokens": 500},
            },
            model="openai/gpt-4o",
        )
        with patch.dict(
            os.environ,
            {
                "LLM_USAGE_HMAC_SECRET": "persist-secret",
                "LLM_USAGE_HMAC_KEY_VERSION": "persist-v1",
            },
            clear=False,
        ):
            usage = attach_message_hmacs(
                usage,
                [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "user prompt"},
                ],
            )

        persist_llm_usage(
            usage,
            "openai/gpt-4o",
            call_type="analysis",
            stock_code="000001",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertEqual(row.prompt_tokens, 2000)
            self.assertEqual(row.normalized_prompt_tokens, 2000)
            self.assertEqual(row.normalized_cache_read_tokens, 500)
            self.assertEqual(row.cache_capability, "supported")
            self.assertEqual(row.cache_eligibility, "eligible")
            self.assertEqual(row.cache_observation, "partial_hit")
            self.assertEqual(row.hmac_key_version, "persist-v1")
            self.assertEqual(len(row.messages_hmac), 64)
            self.assertNotIn("system prompt", row.provider_usage_json)
            self.assertNotIn("user prompt", row.provider_usage_json)

    def test_prompt_cache_telemetry_disabled_does_not_synthesize_cache_columns(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 2000,
                "completion_tokens": 100,
                "total_tokens": 2100,
                "prompt_tokens_details": {"cached_tokens": 500},
            },
            model="openai/gpt-4o",
        )
        filtered = filter_prompt_cache_telemetry(
            usage,
            SimpleNamespace(llm_prompt_cache_telemetry_enabled=False),
        )

        persist_llm_usage(
            filtered,
            "openai/gpt-4o",
            call_type="analysis",
            stock_code="000001",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertEqual(row.prompt_tokens, 2000)
            self.assertEqual(row.normalized_prompt_tokens, 2000)
            self.assertIsNone(row.provider_usage_json)
            self.assertIsNone(row.normalized_cache_read_tokens)
            self.assertIsNone(row.cache_capability)
            self.assertIsNone(row.cache_eligibility)
            self.assertIsNone(row.cache_observation)

    def test_prompt_cache_telemetry_disabled_no_usage_does_not_synthesize_cache_columns(self):
        filtered = filter_prompt_cache_telemetry(
            {},
            SimpleNamespace(llm_prompt_cache_telemetry_enabled=False),
        )

        persist_llm_usage(
            filtered,
            "openai/gpt-4o",
            call_type="analysis",
            stock_code="000001",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertEqual(row.prompt_tokens, 0)
            self.assertEqual(row.normalized_prompt_tokens, 0)
            self.assertIsNone(row.provider_usage_json)
            self.assertIsNone(row.normalized_cache_read_tokens)
            self.assertIsNone(row.cache_capability)
            self.assertIsNone(row.cache_eligibility)
            self.assertIsNone(row.cache_observation)

    def test_persist_usage_does_not_store_unmodeled_prompt_payload_fields(self):
        usage = normalize_litellm_usage(
            {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
                "prompt": "SECRET_PROMPT",
                "messages": [{"role": "user", "content": "SECRET_MESSAGE"}],
                "content": "SECRET_CONTENT",
            },
            model="gateway/custom-model",
            provider="gateway",
        )

        persist_llm_usage(
            usage,
            "gateway/custom-model",
            call_type="analysis",
            stock_code="000001",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertNotIn("SECRET_PROMPT", row.provider_usage_json)
            self.assertNotIn("SECRET_MESSAGE", row.provider_usage_json)
            self.assertNotIn("SECRET_CONTENT", row.provider_usage_json)
            parsed = json.loads(row.provider_usage_json)
            self.assertEqual(parsed, {"completion_tokens": 2, "prompt_tokens": 3, "total_tokens": 5})

    def test_persist_usage_does_not_store_tokenizer_free_text_columns(self):
        persist_llm_usage(
            {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "tokenizer_name": "cl100k_base prompt fragment",
                "tokenizer_version": "Authorization: Bearer sk-header",
            },
            "gateway/custom-model",
            call_type="analysis",
        )

        with self.db.session_scope() as session:
            row = session.query(LLMUsage).one()
            self.assertIsNone(row.tokenizer_name)
            self.assertIsNone(row.tokenizer_version)

    def test_persist_usage_never_raises(self):
        # Pass a deliberately bad db state by resetting the singleton
        DatabaseManager.reset_instance()
        # Should silently swallow the error, not raise
        try:
            persist_llm_usage({"total_tokens": 5}, "m", call_type="analysis")
        except Exception as exc:
            self.fail(f"persist_llm_usage raised unexpectedly: {exc}")


class TestLLMUsageMigration(unittest.TestCase):
    def tearDown(self):
        DatabaseManager.reset_instance()

    def _create_legacy_usage_db(self, db_path: Path, telemetry_columns=()):
        extra_columns = "".join(
            f",\n                        {column} {_LLM_USAGE_TELEMETRY_COLUMN_SQL[column]}"
            for column in telemetry_columns
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE llm_usage (
                    id INTEGER PRIMARY KEY,
                    call_type VARCHAR(64) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    stock_code VARCHAR(32),
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    called_at DATETIME{extra_columns}
                )
                """
            )
            conn.commit()

    def _usage_columns(self, db_path: Path):
        with sqlite3.connect(db_path) as conn:
            return {
                row[1]
                for row in conn.execute("PRAGMA table_info(llm_usage)").fetchall()
            }

    def _assert_all_telemetry_columns(self, db_path: Path):
        columns = self._usage_columns(db_path)
        missing = set(_LLM_USAGE_TELEMETRY_COLUMN_SQL) - columns
        self.assertFalse(missing, f"Missing telemetry columns: {sorted(missing)}")

    @staticmethod
    def _is_add_column_statement(statement: str, column: str) -> bool:
        return (
            "ALTER TABLE llm_usage ADD COLUMN" in statement
            and f"ADD COLUMN {column} " in statement
        )

    def test_existing_sqlite_table_gets_missing_columns_idempotently(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite"
            self._create_legacy_usage_db(db_path)

            DatabaseManager.reset_instance()
            db = DatabaseManager(db_url=f"sqlite:///{db_path}")
            db._ensure_llm_usage_telemetry_columns()

            self._assert_all_telemetry_columns(db_path)

    def test_existing_sqlite_table_gets_partial_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite"
            self._create_legacy_usage_db(
                db_path,
                telemetry_columns=(
                    "provider_usage_json",
                    "normalized_prompt_tokens",
                    "messages_hmac",
                ),
            )

            DatabaseManager.reset_instance()
            DatabaseManager(db_url=f"sqlite:///{db_path}")

            self._assert_all_telemetry_columns(db_path)

    def test_existing_sqlite_table_with_all_telemetry_columns_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite"
            self._create_legacy_usage_db(
                db_path,
                telemetry_columns=tuple(_LLM_USAGE_TELEMETRY_COLUMN_SQL),
            )

            DatabaseManager.reset_instance()
            DatabaseManager(db_url=f"sqlite:///{db_path}")

            self._assert_all_telemetry_columns(db_path)

    def test_existing_sqlite_table_ignores_concurrent_duplicate_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite"
            self._create_legacy_usage_db(db_path)

            original_exec_driver_sql = Connection.exec_driver_sql
            race_fired = {"value": False}

            def flaky_exec_driver_sql(connection, statement, *args, **kwargs):
                if (
                    not race_fired["value"]
                    and self._is_add_column_statement(statement, "provider_usage_json")
                ):
                    race_fired["value"] = True
                    with sqlite3.connect(db_path) as conn:
                        conn.execute(
                            "ALTER TABLE llm_usage ADD COLUMN provider_usage_json TEXT"
                        )
                        conn.commit()
                    raise OperationalError(
                        statement,
                        {},
                        sqlite3.OperationalError(
                            "duplicate column name: provider_usage_json"
                        ),
                    )
                return original_exec_driver_sql(
                    connection,
                    statement,
                    *args,
                    **kwargs,
                )

            DatabaseManager.reset_instance()
            with patch.object(
                Connection,
                "exec_driver_sql",
                new=flaky_exec_driver_sql,
            ):
                DatabaseManager(db_url=f"sqlite:///{db_path}")

            self.assertTrue(race_fired["value"])
            self._assert_all_telemetry_columns(db_path)

    def test_existing_sqlite_table_retries_locked_column_backfill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite"
            self._create_legacy_usage_db(db_path)

            original_exec_driver_sql = Connection.exec_driver_sql
            lock_fired = {"value": False}

            def flaky_exec_driver_sql(connection, statement, *args, **kwargs):
                if (
                    not lock_fired["value"]
                    and self._is_add_column_statement(statement, "provider_usage_json")
                ):
                    lock_fired["value"] = True
                    raise OperationalError(
                        statement,
                        {},
                        sqlite3.OperationalError("database is locked"),
                    )
                return original_exec_driver_sql(
                    connection,
                    statement,
                    *args,
                    **kwargs,
                )

            DatabaseManager.reset_instance()
            with patch.object(
                Connection,
                "exec_driver_sql",
                new=flaky_exec_driver_sql,
            ), patch("src.storage.time.sleep") as sleep_mock:
                DatabaseManager(db_url=f"sqlite:///{db_path}")

            self.assertTrue(lock_fired["value"])
            storage_retry_sleeps = [
                call_args
                for call_args in sleep_mock.call_args_list
                if call_args.args == (0.1,)
            ]
            self.assertEqual(len(storage_retry_sleeps), 1)
            self._assert_all_telemetry_columns(db_path)


if __name__ == "__main__":
    unittest.main()
