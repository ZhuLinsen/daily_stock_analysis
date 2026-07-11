# -*- coding: utf-8 -*-
"""
Unit tests for LongbridgeFetcher integration.

Real API / credentials: use ``tests/longbridge_live_smoke.py`` (not this file).

Verifies:
1. Symbol conversion logic (AAPL -> AAPL.US, HK00700 -> 0700.HK)
2. get_realtime_quote builds correct UnifiedRealtimeQuote with computed fields
3. _supplement_from_longbridge merges missing fields into yfinance quote
4. Graceful degradation when credentials are missing
"""

import os
import base64
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.longbridge_fetcher import (
    LongbridgeFetcher,
    _to_longbridge_symbol,
    _is_us_code,
    _is_hk_code,
)
from data_provider.realtime_types import UnifiedRealtimeQuote, RealtimeSource


class TestSymbolConversion(unittest.TestCase):
    """Test internal stock code -> Longbridge symbol conversion."""

    def test_us_stock(self):
        self.assertEqual(_to_longbridge_symbol("AAPL"), "AAPL.US")
        self.assertEqual(_to_longbridge_symbol("TSLA"), "TSLA.US")
        self.assertEqual(_to_longbridge_symbol("NVDA"), "NVDA.US")
        self.assertEqual(_to_longbridge_symbol("GLD"), "GLD.US")

    def test_us_stock_already_suffixed(self):
        self.assertEqual(_to_longbridge_symbol("AAPL.US"), "AAPL.US")

    def test_hk_stock_with_prefix(self):
        self.assertEqual(_to_longbridge_symbol("HK00700"), "0700.HK")
        self.assertEqual(_to_longbridge_symbol("HK09988"), "9988.HK")
        self.assertEqual(_to_longbridge_symbol("HK01810"), "1810.HK")

    def test_hk_stock_pure_digits(self):
        self.assertEqual(_to_longbridge_symbol("00700"), "0700.HK")
        self.assertEqual(_to_longbridge_symbol("09988"), "9988.HK")

    def test_hk_stock_already_suffixed(self):
        self.assertEqual(_to_longbridge_symbol("0700.HK"), "0700.HK")

    def test_a_share_returns_none(self):
        self.assertIsNone(_to_longbridge_symbol("600519"))
        self.assertIsNone(_to_longbridge_symbol("000001"))

    def test_code_detection(self):
        self.assertTrue(_is_us_code("AAPL"))
        self.assertTrue(_is_us_code("TSLA"))
        self.assertFalse(_is_us_code("600519"))
        self.assertTrue(_is_hk_code("HK00700"))
        self.assertTrue(_is_hk_code("00700"))
        self.assertFalse(_is_hk_code("AAPL"))


class TestLongbridgeFetcherNoCredentials(unittest.TestCase):
    """Verify graceful degradation when credentials are absent."""

    def setUp(self):
        self.fetcher = LongbridgeFetcher()
        self.fetcher._available = False

    def test_returns_none_without_creds(self):
        result = self.fetcher.get_realtime_quote("AAPL")
        self.assertIsNone(result)

    def test_is_available_false(self):
        self.assertFalse(self.fetcher._is_available())


class TestLongbridgeAuthSelection(unittest.TestCase):
    """Verify OAuth and Legacy auth selection without real SDK calls."""

    def _install_mock_longbridge(self):
        mock_lb_module = types.ModuleType("longbridge")
        mock_lb_openapi = types.ModuleType("longbridge.openapi")
        mock_config = MagicMock()
        mock_quote_context = MagicMock(return_value="quote-context")
        mock_oauth_builder = MagicMock()

        mock_lb_openapi.Config = mock_config
        mock_lb_openapi.QuoteContext = mock_quote_context
        mock_lb_openapi.OAuthBuilder = mock_oauth_builder
        return mock_lb_module, mock_lb_openapi, mock_config, mock_quote_context, mock_oauth_builder

    def _config(
        self,
        *,
        app_key="",
        app_secret="",
        access_token="",
        oauth_client_id="",
    ):
        return SimpleNamespace(
            longbridge_app_key=app_key,
            longbridge_app_secret=app_secret,
            longbridge_access_token=access_token,
            longbridge_oauth_client_id=oauth_client_id,
        )

    @patch("src.config.get_config")
    def test_is_available_with_oauth_client_id(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")

        fetcher = LongbridgeFetcher()

        self.assertTrue(fetcher._is_available())

    @patch("src.config.get_config")
    def test_oauth_uses_token_cache_without_legacy_fallback(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, mock_quote_context, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.return_value = "oauth-token"
        mock_config.from_oauth.return_value = "oauth-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            token_cache.write_text('{"refresh_token":"valid-token"}', encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertEqual(ctx, "quote-context")
        mock_oauth_builder.assert_called_once_with("client-1")
        mock_config.from_oauth.assert_called_once_with("oauth-token")
        mock_config.from_apikey_env.assert_not_called()
        mock_quote_context.assert_called_once_with("oauth-config")

    @patch("src.config.get_config")
    def test_oauth_uses_app_key_as_client_id_when_access_token_missing(self, mock_get_config):
        mock_get_config.return_value = self._config(app_key="app-key", app_secret="app-secret")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, mock_quote_context, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.return_value = "oauth-token"
        mock_config.from_oauth.return_value = "oauth-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "app-key"
            token_cache.write_text('{"refresh_token":"valid-token"}', encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "",
                    "LONGBRIDGE_APP_KEY": "app-key",
                    "LONGBRIDGE_APP_SECRET": "app-secret",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertEqual(ctx, "quote-context")
        mock_oauth_builder.assert_called_once_with("app-key")
        mock_config.from_oauth.assert_called_once_with("oauth-token")
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()
        mock_quote_context.assert_called_once_with("oauth-config")

    @patch("src.config.get_config")
    def test_oauth_without_cache_does_not_call_legacy_when_legacy_incomplete(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_cache = Path(tmpdir) / "client-1"
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=missing_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertIsNone(ctx)
        mock_oauth_builder.assert_not_called()
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_sdk_without_oauth_api_fails_closed_with_clear_log(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        mock_lb_module = types.ModuleType("longbridge")
        mock_lb_openapi = types.ModuleType("longbridge.openapi")
        mock_config = MagicMock()
        mock_quote_context = MagicMock(return_value="quote-context")
        mock_lb_openapi.Config = mock_config
        mock_lb_openapi.QuoteContext = mock_quote_context

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            token_cache.write_text('{"refresh_token":"valid-token"}', encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ), self.assertLogs("data_provider.longbridge_fetcher", level="WARNING") as logs:
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertIsNone(ctx)
        self.assertIn("不支持 OAuth 2.0", "\n".join(logs.output))
        mock_quote_context.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_invalid_cache_content_skips_oauth_reauth_and_fails_closed(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules

        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_cache = Path(tmpdir) / "client-1"
            invalid_cache.write_text("invalid-json", encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=invalid_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertIsNone(ctx)
        mock_oauth_builder.assert_not_called()
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_overwrites_invalid_cache_from_base64_secret(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.return_value = "oauth-token"
        mock_config.from_oauth.return_value = "oauth-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_cache = Path(tmpdir) / "client-1"
            invalid_cache.write_text("invalid-json", encoding="utf-8")
            encoded_cache = base64.b64encode(b'{"refresh_token":"refreshed"}').decode("ascii")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_OAUTH_TOKEN_CACHE_B64": encoded_cache,
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=invalid_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()
                self.assertEqual(invalid_cache.read_bytes(), b'{"refresh_token":"refreshed"}')

        self.assertEqual(ctx, "quote-context")
        mock_oauth_builder.assert_called_once_with("client-1")
        mock_config.from_oauth.assert_called_once_with("oauth-token")
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_replaces_existing_cache_when_base64_secret_differs(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.return_value = "oauth-token"
        mock_config.from_oauth.return_value = "oauth-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            token_cache.write_text('{"refresh_token":"old-but-json-valid"}', encoding="utf-8")
            encoded_cache = base64.b64encode(b'{"refresh_token":"fresh"}').decode("ascii")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_OAUTH_TOKEN_CACHE_B64": encoded_cache,
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()
                self.assertEqual(token_cache.read_bytes(), b'{"refresh_token":"fresh"}')

        self.assertEqual(ctx, "quote-context")
        mock_config.from_oauth.assert_called_once_with("oauth-token")
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_callback_reauth_request_fails_closed_in_headless(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules

        def _require_oauth_reauth_request(show_url):
            show_url("https://longbridge.oauth/login")
            raise RuntimeError("re-auth requested")
        mock_oauth_builder.return_value.build.side_effect = _require_oauth_reauth_request

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            token_cache.write_text('{"refresh_token":"expired-token"}', encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertIsNone(ctx)
        mock_oauth_builder.assert_called_once_with("client-1")
        mock_config.from_apikey_env.assert_not_called()
        mock_config.from_apikey.assert_not_called()

    @patch("src.config.get_config")
    def test_oauth_restores_token_cache_from_base64_secret(self, mock_get_config):
        mock_get_config.return_value = self._config(oauth_client_id="client-1")
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, _, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.return_value = "oauth-token"
        mock_config.from_oauth.return_value = "oauth-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            encoded_cache = base64.b64encode(b'{"refresh_token":"test"}').decode("ascii")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_OAUTH_TOKEN_CACHE_B64": encoded_cache,
                    "LONGBRIDGE_APP_KEY": "",
                    "LONGBRIDGE_APP_SECRET": "",
                    "LONGBRIDGE_ACCESS_TOKEN": "",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()
                self.assertEqual(token_cache.read_bytes(), b'{"refresh_token":"test"}')

        self.assertEqual(ctx, "quote-context")
        mock_config.from_oauth.assert_called_once_with("oauth-token")

    @patch("src.config.get_config")
    def test_oauth_failure_can_fallback_to_complete_legacy_credentials(self, mock_get_config):
        mock_get_config.return_value = self._config(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            oauth_client_id="client-1",
        )
        modules = self._install_mock_longbridge()
        mock_lb_module, mock_lb_openapi, mock_config, mock_quote_context, mock_oauth_builder = modules
        mock_oauth_builder.return_value.build.side_effect = RuntimeError("bad cache")
        mock_config.from_apikey_env.return_value = "legacy-config"

        with tempfile.TemporaryDirectory() as tmpdir:
            token_cache = Path(tmpdir) / "client-1"
            token_cache.write_text("{}", encoding="utf-8")
            with patch.dict("sys.modules", {"longbridge": mock_lb_module, "longbridge.openapi": mock_lb_openapi}), patch.dict(
                os.environ,
                {
                    "LONGBRIDGE_OAUTH_CLIENT_ID": "client-1",
                    "LONGBRIDGE_APP_KEY": "app-key",
                    "LONGBRIDGE_APP_SECRET": "app-secret",
                    "LONGBRIDGE_ACCESS_TOKEN": "access-token",
                },
            ), patch("data_provider.longbridge_fetcher._longbridge_config_kwargs", return_value={}), patch(
                "data_provider.longbridge_fetcher._oauth_token_cache_path",
                return_value=token_cache,
            ):
                fetcher = LongbridgeFetcher()
                ctx = fetcher._get_ctx()

        self.assertEqual(ctx, "quote-context")
        mock_config.from_apikey_env.assert_called_once()
        mock_quote_context.assert_called_once_with("legacy-config")


class TestLongbridgeFetcherMocked(unittest.TestCase):
    """Test get_realtime_quote with mocked Longbridge SDK."""

    def _make_fetcher_with_mock_ctx(self):
        fetcher = LongbridgeFetcher()
        fetcher._available = True
        mock_ctx = MagicMock()
        fetcher._ctx = mock_ctx
        return fetcher, mock_ctx

    def _make_mock_quote(self, **kwargs):
        q = MagicMock()
        defaults = {
            "last_done": "253.79",
            "prev_close": "246.63",
            "open": "247.91",
            "high": "255.48",
            "low": "247.10",
            "volume": 49549600,
            "turnover": "12575000000",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(q, k, v)
        return q

    def _make_mock_static(self, **kwargs):
        s = MagicMock()
        defaults = {
            "name_cn": "苹果",
            "name_en": "Apple Inc.",
            "circulating_shares": 15000000000,
            "total_shares": 16000000000,
            "eps_ttm": "6.08",
            "bps": "4.40",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(s, k, v)
        return s

    def test_realtime_quote_basic(self):
        """Verify computed fields: turnover_rate, pe_ratio, etc."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        ctx.static_info.return_value = [self._make_mock_static()]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "AAPL")
        self.assertEqual(quote.source, RealtimeSource.LONGBRIDGE)
        self.assertAlmostEqual(quote.price, 253.79, places=2)
        self.assertAlmostEqual(quote.change_pct, 2.90, places=0)
        self.assertEqual(quote.name, "苹果")

        # turnover_rate = volume / circulating_shares * 100
        expected_turnover = 49549600 / 15000000000 * 100
        self.assertAlmostEqual(quote.turnover_rate, expected_turnover, places=3)

        # pe_ratio = price / eps_ttm
        self.assertAlmostEqual(quote.pe_ratio, 253.79 / 6.08, places=1)

        # pb_ratio = price / bps
        self.assertAlmostEqual(quote.pb_ratio, 253.79 / 4.40, places=1)

        # total_mv
        self.assertAlmostEqual(quote.total_mv, 253.79 * 16000000000, places=0)

    def test_turnover_falls_back_to_total_shares_when_circulating_zero(self):
        """US API often reports circulating_shares=0; use total_shares for turnover."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        static = self._make_mock_static()
        static.circulating_shares = 0
        static.total_shares = 16000000000
        ctx.static_info.return_value = [static]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        vol = 49549600
        self.assertAlmostEqual(quote.turnover_rate, vol / 16000000000 * 100, places=3)

    def test_realtime_quote_with_volume_ratio(self):
        """Verify volume_ratio calculation from history."""
        import types
        from datetime import date as dt_date, timedelta

        # Mock longbridge.openapi module so the internal import succeeds
        mock_lb_module = types.ModuleType("longbridge")
        mock_lb_openapi = types.ModuleType("longbridge.openapi")
        mock_lb_openapi.Period = MagicMock()
        mock_lb_openapi.AdjustType = MagicMock()
        with patch.dict("sys.modules", {
            "longbridge": mock_lb_module,
            "longbridge.openapi": mock_lb_openapi,
        }):
            fetcher, ctx = self._make_fetcher_with_mock_ctx()
            ctx.quote.return_value = [self._make_mock_quote(volume=50000000)]
            ctx.static_info.return_value = [self._make_mock_static()]

            base = dt_date.today() - timedelta(days=6)
            mock_candles = []
            for i, vol in enumerate([40000000, 38000000, 42000000, 41000000, 39000000]):
                c = MagicMock()
                c.volume = vol
                past_date = base + timedelta(days=i)
                c.timestamp = MagicMock()
                c.timestamp.date.return_value = past_date
                mock_candles.append(c)
            ctx.history_candlesticks_by_offset.return_value = mock_candles

            quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        avg_vol = (40000000 + 38000000 + 42000000 + 41000000 + 39000000) / 5
        expected_ratio = round(50000000 / avg_vol, 2)
        self.assertEqual(quote.volume_ratio, expected_ratio)

    def test_quote_api_failure_returns_none(self):
        """If ctx.quote() raises, return None gracefully."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.side_effect = Exception("network error")

        result = fetcher.get_realtime_quote("AAPL")
        self.assertIsNone(result)

    def test_connection_error_enters_cooldown_and_skips_immediate_retry(self):
        """Connection-close failures should not trigger reconnect on every stock."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.side_effect = Exception("client is closed")

        with patch("data_provider.longbridge_fetcher._connection_cooldown_seconds", return_value=30):
            first = fetcher.get_realtime_quote("AAPL")
            second = fetcher.get_realtime_quote("AAPL")

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(ctx.quote.call_count, 1)
        self.assertIsNone(fetcher._ctx)
        self.assertGreater(fetcher._cooldown_until, time.time())

    def test_daily_data_skips_request_during_cooldown(self):
        """Daily requests should also respect the connection cooldown."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        fetcher._cooldown_until = time.time() + 30

        with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
            fetcher._fetch_raw_data("AAPL", "2026-05-01", "2026-05-08")

        ctx.history_candlesticks_by_date.assert_not_called()

    def test_hk_stock_symbol(self):
        """HK stock should use .HK suffix."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        ctx.static_info.return_value = [self._make_mock_static(name_cn="腾讯控股")]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("HK00700")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "HK00700")
        ctx.quote.assert_called_with(["0700.HK"])


class TestSupplementFromLongbridge(unittest.TestCase):
    """Test the _supplement_from_longbridge method in DataFetcherManager."""

    def test_merge_fills_missing_fields(self):
        """When yfinance quote is missing volume_ratio/turnover_rate, LB fills them."""
        from data_provider.base import DataFetcherManager

        yf_quote = UnifiedRealtimeQuote(
            code="AAPL",
            name="Apple",
            source=RealtimeSource.FALLBACK,
            price=253.79,
            change_pct=2.9,
            volume=49549600,
            volume_ratio=None,
            turnover_rate=None,
            pe_ratio=None,
        )

        lb_quote = UnifiedRealtimeQuote(
            code="AAPL",
            name="苹果",
            source=RealtimeSource.LONGBRIDGE,
            price=253.79,
            volume_ratio=1.25,
            turnover_rate=0.33,
            pe_ratio=41.7,
            pb_ratio=57.7,
            total_mv=4060640000000.0,
        )

        mock_lb_fetcher = MagicMock()
        mock_lb_fetcher.name = "LongbridgeFetcher"
        mock_lb_fetcher.get_realtime_quote.return_value = lb_quote

        manager = DataFetcherManager(fetchers=[mock_lb_fetcher])

        result = manager._supplement_from_longbridge("AAPL", yf_quote)

        self.assertIsNotNone(result)
        self.assertEqual(result.volume_ratio, 1.25)
        self.assertEqual(result.turnover_rate, 0.33)
        self.assertEqual(result.pe_ratio, 41.7)
        # source should stay as original (yfinance/FALLBACK)
        self.assertEqual(result.source, RealtimeSource.FALLBACK)

    def test_sole_source_when_yfinance_fails(self):
        """When yfinance returns None, LB acts as sole source."""
        from data_provider.base import DataFetcherManager

        lb_quote = UnifiedRealtimeQuote(
            code="AAPL",
            source=RealtimeSource.LONGBRIDGE,
            price=253.79,
            volume_ratio=1.25,
            turnover_rate=0.33,
        )

        mock_lb_fetcher = MagicMock()
        mock_lb_fetcher.name = "LongbridgeFetcher"
        mock_lb_fetcher.get_realtime_quote.return_value = lb_quote

        manager = DataFetcherManager(fetchers=[mock_lb_fetcher])

        result = manager._supplement_from_longbridge("AAPL", None)

        self.assertIsNotNone(result)
        self.assertEqual(result.source, RealtimeSource.LONGBRIDGE)
        self.assertEqual(result.price, 253.79)


if __name__ == "__main__":
    unittest.main()
