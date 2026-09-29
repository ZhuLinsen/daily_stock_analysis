# -*- coding: utf-8 -*-
"""Tests for FutuFetcher provider timestamp normalization."""

import unittest

from data_provider.futu_fetcher import _hk_provider_timestamp


class TestFutuProviderTimestamp(unittest.TestCase):
    """Futu snapshot update_time is a naive Beijing-time string."""

    def test_naive_string_gets_beijing_offset(self):
        value = _hk_provider_timestamp("2026-08-24 10:30:00")
        self.assertEqual(value, "2026-08-24T10:30:00+08:00")

    def test_empty_and_none_return_none(self):
        self.assertIsNone(_hk_provider_timestamp(None))
        self.assertIsNone(_hk_provider_timestamp(""))
        self.assertIsNone(_hk_provider_timestamp("   "))

    def test_offset_string_is_preserved(self):
        value = _hk_provider_timestamp("2026-08-24T10:30:00+08:00")
        self.assertEqual(value, "2026-08-24T10:30:00+08:00")

    def test_unparsable_text_returns_original(self):
        value = _hk_provider_timestamp("not-a-date")
        self.assertEqual(value, "not-a-date")
