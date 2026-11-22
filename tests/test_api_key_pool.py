# -*- coding: utf-8 -*-
"""Unit tests for the shared multi-key pool used by data providers."""

import time
import unittest
from unittest.mock import MagicMock, patch

from data_provider.api_key_pool import ApiKeyPool, is_key_failure, parse_api_keys


class TestParseApiKeys(unittest.TestCase):
    def test_comma_separated_string_is_split_and_deduplicated(self):
        self.assertEqual(
            parse_api_keys(" key-a , key-b ,, key-a "),
            ["key-a", "key-b"],
        )

    def test_json_array_string_is_supported(self):
        self.assertEqual(
            parse_api_keys('["key-a", "key-b"]'),
            ["key-a", "key-b"],
        )

    def test_sequence_is_supported(self):
        self.assertEqual(parse_api_keys(["key-a", "key-b"]), ["key-a", "key-b"])

    def test_empty_values_yield_empty_list(self):
        self.assertEqual(parse_api_keys(None), [])
        self.assertEqual(parse_api_keys(""), [])
        self.assertEqual(parse_api_keys("[]"), [])

    def test_unexpected_object_is_treated_as_not_configured(self):
        self.assertEqual(parse_api_keys(MagicMock()), [])


class TestIsKeyFailure(unittest.TestCase):
    def test_authentication_and_quota_errors_are_key_failures(self):
        self.assertTrue(is_key_failure(RuntimeError("401 Client Error: Unauthorized")))
        self.assertTrue(is_key_failure(RuntimeError("Invalid API key")))
        self.assertTrue(is_key_failure(RuntimeError("daily rate limit reached")))
        self.assertTrue(is_key_failure(RuntimeError("429 Too Many Requests")))

    def test_other_errors_are_not_key_failures(self):
        self.assertFalse(is_key_failure(RuntimeError("connection timeout")))
        self.assertFalse(is_key_failure(RuntimeError("Invalid API call")))
        self.assertFalse(is_key_failure(None))


class TestApiKeyPool(unittest.TestCase):
    def test_call_passes_primary_key(self):
        pool = ApiKeyPool(["key-a", "key-b"])

        result = pool.call(lambda key: f"ok:{key}")

        self.assertEqual(result, "ok:key-a")
        self.assertEqual(pool.error_counts(), {"key-a": 0, "key-b": 0})

    def test_fails_over_to_next_key_on_key_error(self):
        pool = ApiKeyPool(["key-a", "key-b"])

        def call(key):
            if key == "key-a":
                raise RuntimeError("Invalid API key")
            return f"ok:{key}"

        self.assertEqual(pool.call(call), "ok:key-b")
        self.assertEqual(pool.error_counts()["key-a"], 1)

    def test_non_key_error_does_not_switch_key(self):
        pool = ApiKeyPool(["key-a", "key-b"])
        seen = []

        def call(key):
            seen.append(key)
            raise RuntimeError("connection timed out")

        with self.assertRaises(RuntimeError):
            pool.call(call)

        self.assertEqual(seen, ["key-a"])
        self.assertEqual(pool.error_counts()["key-a"], 0)

    def test_key_is_skipped_after_error_threshold_until_cooldown(self):
        pool = ApiKeyPool(["key-a", "key-b"])
        for _ in range(ApiKeyPool.MAX_CONSECUTIVE_ERRORS):
            pool._record_error("key-a")

        attempts = []

        def call(key):
            attempts.append(key)
            return key

        self.assertEqual(pool.call(call), "key-b")
        self.assertNotIn("key-a", attempts)

        # 冷却结束后 key-a 会重新参与轮询
        with patch(
            "data_provider.api_key_pool.time.time",
            return_value=time.time() + ApiKeyPool.COOLDOWN_SECONDS + 1,
        ):
            pool._cursor = 0
            self.assertEqual(pool.call(call), "key-a")
        self.assertEqual(pool.error_counts()["key-a"], 0)

    def test_all_keys_failing_raises_last_error(self):
        pool = ApiKeyPool(["key-a", "key-b"])

        def call(key):
            raise RuntimeError(f"Invalid API key: {key}")

        with self.assertRaises(RuntimeError) as ctx:
            pool.call(call)

        self.assertIn("key-b", str(ctx.exception))

    def test_empty_pool_raises(self):
        with self.assertRaises(RuntimeError):
            ApiKeyPool([]).call(lambda key: key)


if __name__ == "__main__":
    unittest.main()
