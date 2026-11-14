# -*- coding: utf-8 -*-
"""
Issue #234 盘中实时技术指标的单元测试。

覆盖范围：
- _augment_historical_with_realtime：追加/更新逻辑和防护条件
- _compute_ma_status：均线排列文案
- _enhance_context：使用 realtime + trend_result 覆盖 today
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.realtime_types import UnifiedRealtimeQuote, RealtimeSource
from data_provider.akshare_fetcher import AkshareFetcher, _hk_realtime_cache
from data_provider.base import DataFetcherManager
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.analyzer import GeminiAnalyzer
from src.core.trading_calendar import build_market_phase_context
from src.services.analysis_context_builder import AnalysisContextBuilder, PipelineAnalysisArtifacts
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, TrendStatus
from src.core.pipeline import StockAnalysisPipeline


def _make_realtime_quote(
    price: float = 15.72,
    open_price: float = 15.62,
    high: float = 16.29,
    low: float = 15.55,
    volume: int = 13995600,
    amount: float = None,
    change_pct: float = 0.96,
    **overrides,
) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.TENCENT,
        price=price,
        open_price=open_price,
        high=high,
        low=low,
        volume=volume,
        amount=amount,
        change_pct=change_pct,
        **overrides,
    )


def _make_historical_df(days: int = 25, last_date: date = None) -> pd.DataFrame:
    """构造历史 OHLCV DataFrame。"""
    if last_date is None:
        last_date = date.today() - timedelta(days=1)
    dates = [last_date - timedelta(days=i) for i in range(days - 1, -1, -1)]
    base = 100.0
    data = []
    for i, d in enumerate(dates):
        close = base + i * 0.5
        data.append({
            "code": "600519",
            "date": d,
            "open": close - 0.2,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000000 + i * 10000,
            "amount": close * (1000000 + i * 10000),
            "pct_chg": 0.5,
            "ma5": close,
            "ma10": close - 0.1,
            "ma20": close - 0.2,
            "volume_ratio": 1.0,
        })
    return pd.DataFrame(data)


class _HistoryBackedFastInfo:
    """Model yfinance FastInfo properties backed by its daily history."""

    def __init__(self, history: pd.DataFrame) -> None:
        self._today = history.iloc[-1]
        self._previous = history.iloc[-2]
        self.marketCap = None

    @property
    def lastPrice(self):
        return self._today["Close"]

    @property
    def previousClose(self):
        return self._previous["Close"]

    @property
    def open(self):
        return self._today["Open"]

    @property
    def dayHigh(self):
        return self._today["High"]

    @property
    def dayLow(self):
        return self._today["Low"]

    @property
    def lastVolume(self):
        return self._today["Volume"]


def _make_yfinance_history(previous_date: str, previous: dict, today_date: str, today: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [previous, today],
        index=pd.DatetimeIndex([previous_date, today_date], tz="Asia/Seoul"),
    )


class TestAugmentHistoricalWithRealtime(unittest.TestCase):
    """_augment_historical_with_realtime 的测试。"""

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)

    def test_returns_unchanged_when_realtime_none(self) -> None:
        df = _make_historical_df()
        result = self.pipeline._augment_historical_with_realtime(df, None, "600519")
        self.assertIs(result, df)
        self.assertEqual(len(result), len(df))

    def test_returns_unchanged_when_price_invalid(self) -> None:
        df = _make_historical_df()
        quote = _make_realtime_quote(price=0)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df))
        quote2 = MagicMock()
        quote2.price = None
        result2 = self.pipeline._augment_historical_with_realtime(df, quote2, "600519")
        self.assertEqual(len(result2), len(df))

    def test_returns_unchanged_when_df_empty(self) -> None:
        df = pd.DataFrame()
        quote = _make_realtime_quote()
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertTrue(result.empty)

    def test_returns_unchanged_when_df_missing_close(self) -> None:
        df = pd.DataFrame({"date": [date.today()], "open": [100]})
        quote = _make_realtime_quote()
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), 1)
        self.assertNotIn("close", result.columns)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_appends_row_when_last_date_before_today(
        self, _mock_market, _mock_open, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟为 UTC 当日，使 pipeline 的 market_today 等于 date.today()，
        # 不受 get_market_now 通常使用的市场时区影响（例如 CST=UTC+8）。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        df = _make_historical_df(last_date=today - timedelta(days=1))
        quote = _make_realtime_quote(price=15.72)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df) + 1)
        last = result.iloc[-1]
        self.assertEqual(last["close"], 15.72)
        self.assertEqual(last["date"], today)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_updates_last_row_when_last_date_is_today(
        self, _mock_market, _mock_open, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟为当日，使 last_date >= market_today，从而更新最后一行而不是追加。
        # 这可以避免 CI 在 CST 收盘后运行时出现日期边界偏移。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        df = _make_historical_df(last_date=today, days=25)
        df.loc[df.index[-1], "date"] = today
        quote = _make_realtime_quote(price=16.0)
        result = self.pipeline._augment_historical_with_realtime(df, quote, "600519")
        self.assertEqual(len(result), len(df))
        self.assertEqual(result.iloc[-1]["close"], 16.0)


class TestComputeMaStatus(unittest.TestCase):
    """_compute_ma_status 的测试。"""

    def test_bullish_alignment(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(11, 10, 9.5, 9)
        self.assertIn("多头", status)

    def test_bearish_alignment(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(8, 9, 9.5, 10)
        self.assertIn("空头", status)

    def test_consolidation(self) -> None:
        status = StockAnalysisPipeline._compute_ma_status(10, 10, 10, 10)
        self.assertIn("震荡", status)


class TestEnhanceContextRealtimeOverride(unittest.TestCase):
    """_enhance_context 使用实时行情和趋势结果覆盖 today 的测试。"""

    def setUp(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "test_issue234.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with patch.dict(os.environ, {"DATABASE_PATH": self._db_path}):
            from src.config import Config
            Config._instance = None
            self.config = Config._load_from_env()
        self.pipeline = StockAnalysisPipeline(config=self.config)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_today_overridden_when_realtime_and_trend_exist(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        # 固定市场时钟，使 _enhance_context 设置 enhanced['date'] == date.today().isoformat()，
        # 不受 get_market_now 通常使用的市场时区影响（例如 CST=UTC+8）。
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {"close": 15.0, "ma5": 14.8, "ma10": 14.5},
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(price=15.72, volume=2000000)
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )
        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.72)
        self.assertEqual(enhanced["today"]["ma5"], 15.5)
        self.assertEqual(enhanced["today"]["ma10"], 15.2)
        self.assertEqual(enhanced["today"]["ma20"], 14.9)
        self.assertIn("多头", enhanced["ma_status"])
        self.assertEqual(enhanced["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["realtime_source"], "tencent")
        self.assertIn("price_change_ratio", enhanced)
        self.assertIn("volume_change_ratio", enhanced)

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_tencent_688691_volume_change_ratio_uses_normalized_share_volume(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "688691",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 128.46,
                "volume": 19512753,
                "amount": 2487341983,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
            },
            "yesterday": {"close": 128.46, "volume": 19512753},
        }
        quote = UnifiedRealtimeQuote(
            code="688691",
            name="灿芯股份",
            source=RealtimeSource.TENCENT,
            price=122.70,
            open_price=120.09,
            high=125.96,
            low=116.20,
            volume=10931723,
            amount=1327404280,
            change_pct=3.40,
        )
        trend = TrendAnalysisResult(
            code="688691",
            trend_status=TrendStatus.BULL,
            ma5=120.014,
            ma10=119.425,
            ma20=115.8305,
        )

        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "灿芯股份"
        )

        self.assertEqual(enhanced["today"]["volume"], 10931723)
        self.assertEqual(enhanced["today"]["amount"], 1327404280)
        self.assertEqual(enhanced["volume_change_ratio"], 0.56)
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["realtime_source"], "tencent")
        self.assertNotIn("dataSource", enhanced["today"])

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_realtime_metadata_and_partial_estimated_fields_are_propagated(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 15.0,
                "amount": 999999,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
            },
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(
            price=15.72,
            amount=None,
            fetched_at="2026-05-31T10:00:05+00:00",
            provider_timestamp="2026-05-31T10:00:00+00:00",
            is_stale=False,
            stale_seconds=5,
            fallback_from="efinance",
        )
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )

        enhanced = self.pipeline._enhance_context(
            context,
            quote,
            None,
            trend,
            "贵州茅台",
            market_phase_context={"is_partial_bar": True},
        )

        self.assertEqual(enhanced["realtime"]["source"], "tencent")
        self.assertEqual(enhanced["realtime"]["fetched_at"], "2026-05-31T10:00:05+00:00")
        self.assertEqual(enhanced["realtime"]["provider_timestamp"], "2026-05-31T10:00:00+00:00")
        self.assertIs(enhanced["realtime"]["is_stale"], False)
        self.assertEqual(enhanced["realtime"]["stale_seconds"], 5)
        self.assertEqual(enhanced["realtime"]["fallback_from"], "efinance")
        self.assertTrue(enhanced["today"]["is_partial_bar"])
        self.assertTrue(enhanced["today"]["is_estimated"])
        self.assertEqual(
            enhanced["today"]["estimated_fields"],
            ["close", "open", "high", "low", "ma5", "ma10", "ma20", "volume", "pct_chg"],
        )
        self.assertEqual(enhanced["today"]["fetched_at"], "2026-05-31T10:00:05+00:00")
        self.assertEqual(enhanced["today"]["provider_timestamp"], "2026-05-31T10:00:00+00:00")
        self.assertEqual(enhanced["today"]["fallback_from"], "efinance")
        self.assertNotIn("amount", enhanced["today"])
        self.assertNotIn("dataSource", enhanced["today"])

    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_realtime_today_does_not_backfill_historical_amount_or_source(
        self, _mock_market, mock_now
    ) -> None:
        today = date.today()
        mock_now.return_value = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc
        )
        context = {
            "code": "600519",
            "date": (today - timedelta(days=1)).isoformat(),
            "today": {
                "close": 15.0,
                "amount": 999999,
                "date": (today - timedelta(days=1)).isoformat(),
                "dataSource": "AkshareFetcher",
                "code": "600519",
            },
            "yesterday": {"close": 14.5, "volume": 1000000},
        }
        quote = _make_realtime_quote(price=15.72, amount=None)
        trend = TrendAnalysisResult(
            code="600519",
            trend_status=TrendStatus.BULL,
            ma5=15.5,
            ma10=15.2,
            ma20=14.9,
        )

        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )

        self.assertNotIn("amount", enhanced["today"])
        self.assertNotIn("dataSource", enhanced["today"])
        self.assertEqual(enhanced["today"]["date"], today.isoformat())
        self.assertEqual(enhanced["today"]["data_source"], "realtime:tencent")
        self.assertEqual(enhanced["today"]["code"], "600519")

    def test_enhance_context_injects_runtime_news_window_days(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        enhanced = self.pipeline._enhance_context(
            context, None, None, None, "贵州茅台"
        )
        self.assertEqual(
            enhanced["news_window_days"],
            self.pipeline.search_service.news_window_days,
        )

    def test_today_not_overridden_when_trend_missing(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        quote = _make_realtime_quote(price=15.72)
        enhanced = self.pipeline._enhance_context(
            context, quote, None, None, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)

    def test_today_not_overridden_when_realtime_missing(self) -> None:
        context = {"code": "600519", "today": {"close": 15.0}}
        trend = TrendAnalysisResult(code="600519", ma5=15.0, ma10=14.8, ma20=14.5)
        enhanced = self.pipeline._enhance_context(
            context, None, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)

    def test_today_not_overridden_when_trend_ma_zero(self) -> None:
        """StockTrendAnalyzer 因数据不足提前返回 ma5=0.0 时，不应覆盖 today。"""
        context = {"code": "600519", "today": {"close": 15.0, "ma5": 14.8}}
        quote = _make_realtime_quote(price=15.72)
        trend = TrendAnalysisResult(code="600519")  # 默认 ma5=ma10=ma20=0.0
        enhanced = self.pipeline._enhance_context(
            context, quote, None, trend, "贵州茅台"
        )
        self.assertEqual(enhanced["today"]["close"], 15.0)
        self.assertEqual(enhanced["today"]["ma5"], 14.8)

    @staticmethod
    def _kr_005930_context(today_date: str = "2026-11-12", yesterday_date: str = "2026-11-11") -> dict:
        return {
            "code": "005930.KS",
            "date": today_date,
            "today": {
                "date": today_date,
                "open": 208500.0,
                "high": 214000.0,
                "low": 206000.0,
                "close": 208000.0,
                "volume": 19721557.0,
            },
            "yesterday": {
                "date": yesterday_date,
                "open": 197100.0,
                "high": 206500.0,
                "low": 196300.0,
                "close": 206000.0,
                "volume": 16238236.0,
            },
        }

    @staticmethod
    def _kr_005930_trend() -> TrendAnalysisResult:
        trend = TrendAnalysisResult(code="005930.KS")
        trend.ma5, trend.ma10, trend.ma20 = 202110.0, 206725.0, 214212.5
        return trend

    @staticmethod
    def _kr_005930_quote(**overrides) -> UnifiedRealtimeQuote:
        payload = {
            "code": "005930.KS",
            "name": "SamsungElec",
            "source": RealtimeSource.FALLBACK,
            "price": 207750.0,
            "change_pct": -0.12,
            "pre_close": 208000.0,
            "open_price": 214000.0,
            "high": 216000.0,
            "low": 205500.0,
            "volume": 8796683,
            "amount": None,
            "provider_timestamp": "2026-11-13T14:28:00+09:00",
        }
        payload.update(overrides)
        return UnifiedRealtimeQuote(**payload)

    def test_intraday_shifts_stored_today_to_yesterday_and_updates_market_snapshot(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        stored_context = self._kr_005930_context()
        quote = self._kr_005930_quote()
        trend = self._kr_005930_trend()

        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced = self.pipeline._enhance_context(
                stored_context,
                quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )

        self.assertEqual(enhanced["yesterday"]["date"], "2026-11-12")
        self.assertEqual(enhanced["yesterday"]["close"], 208000.0)
        self.assertEqual(enhanced["price_change_ratio"], -0.12)
        self.assertEqual(enhanced["volume_change_ratio"], 0.45)

        snapshot = GeminiAnalyzer.__new__(GeminiAnalyzer)._build_market_snapshot(enhanced)
        self.assertEqual(snapshot["prev_close"], "208000.00")
        self.assertEqual(snapshot["change_amount"], "-250.00")
        self.assertEqual(snapshot["amplitude"], "5.05%")

    def test_yfinance_kr_quote_date_reaches_pipeline_through_manager(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        ticker = MagicMock()
        history = _make_yfinance_history(
            "2026-11-12",
            {"Open": 208500.0, "High": 214000.0, "Low": 206000.0, "Close": 208000.0, "Volume": 19721557},
            "2026-11-13",
            {"Open": 214000.0, "High": 216000.0, "Low": 205500.0, "Close": 207750.0, "Volume": 8796683},
        )
        # FastInfo properties in yfinance are derived from the same daily
        # history response; do not model them as an independent payload.
        ticker.fast_info = _HistoryBackedFastInfo(history)
        ticker.history.return_value = history
        ticker.info = {
            "shortName": "SamsungElec",
            "currency": "KRW",
            # An unrelated info response must not determine the quote date.
            "regularMarketPrice": 208000.0,
            "regularMarketTime": int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp()),
        }
        config = SimpleNamespace(enable_realtime_quote=True, realtime_cache_ttl=600)

        with (
            patch("yfinance.Ticker", return_value=ticker),
            patch("src.config.get_config", return_value=config),
            patch.object(DataFetcherManager, "_utc_now_iso", return_value=now.isoformat()),
        ):
            manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
            quote = manager.get_realtime_quote("005930.KS")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 207750.0)
        self.assertEqual(quote.volume, 8796683)
        self.assertIsNone(quote.provider_timestamp)
        self.assertEqual(quote.quote_date, "2026-11-13")
        self.assertIsNone(quote.is_stale)
        self.assertIsNone(quote.stale_seconds)

        pack = AnalysisContextBuilder.build(
            PipelineAnalysisArtifacts(
                code="005930.KS",
                stock_name="SamsungElec",
                market="kr",
                phase=phase,
                base_context=self._kr_005930_context(),
                enhanced_context={},
                realtime_quote=quote,
                trend_result=self._kr_005930_trend(),
                chip_data=None,
                fundamental_context={"status": "not_supported"},
                news_context=None,
                news_result_count=None,
                metadata={},
            )
        )
        quote_block = pack.blocks["quote"]
        self.assertEqual(quote_block.status.value, "fallback")
        self.assertEqual(quote_block.items["quote_date"].value, "2026-11-13")
        self.assertNotIn("quote_stale", quote_block.warnings)
        self.assertNotIn("provider_timestamp", quote_block.metadata)

        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced = self.pipeline._enhance_context(
                self._kr_005930_context(),
                quote,
                None,
                self._kr_005930_trend(),
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )

        self.assertEqual(enhanced["yesterday"]["date"], "2026-11-12")
        self.assertEqual(enhanced["price_change_ratio"], -0.12)
        self.assertEqual(enhanced["volume_change_ratio"], 0.45)
        self.assertEqual(enhanced["today"]["pct_chg"], -0.12)

    def test_yfinance_recomputes_derived_indicators_after_history_override(self) -> None:
        ticker = MagicMock()
        fast_info_history = _make_yfinance_history(
            "2026-11-11",
            {"Open": 197100.0, "High": 206500.0, "Low": 196300.0, "Close": 206000.0, "Volume": 16238236},
            "2026-11-12",
            {"Open": 208500.0, "High": 214000.0, "Low": 206000.0, "Close": 208000.0, "Volume": 19721557},
        )
        history = _make_yfinance_history(
            "2026-11-12",
            {"Open": 208500.0, "High": 214000.0, "Low": 206000.0, "Close": 208000.0, "Volume": 19721557},
            "2026-11-13",
            {"Open": 214000.0, "High": 216000.0, "Low": 205500.0, "Close": 207750.0, "Volume": 8796683},
        )
        ticker.fast_info = _HistoryBackedFastInfo(fast_info_history)
        ticker.history.return_value = history
        ticker.info = {"shortName": "SamsungElec", "currency": "KRW"}
        config = SimpleNamespace(enable_realtime_quote=True, realtime_cache_ttl=600)

        with (
            patch("yfinance.Ticker", return_value=ticker),
            patch("src.config.get_config", return_value=config),
            patch.object(DataFetcherManager, "_utc_now_iso", return_value="2026-11-13T05:28:00+00:00"),
        ):
            manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
            quote = manager.get_realtime_quote("005930.KS")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 207750.0)
        self.assertEqual(quote.pre_close, 208000.0)
        self.assertEqual(quote.change_amount, -250.0)
        self.assertEqual(quote.change_pct, -0.12)
        self.assertEqual(quote.amplitude, 5.05)
        self.assertFalse(ticker.history.call_args.kwargs["auto_adjust"])

    def test_yfinance_history_override_keeps_unadjusted_previous_close(self) -> None:
        ticker = MagicMock()
        adjusted_history = _make_yfinance_history(
            "2026-11-12",
            {"Open": 95.0, "High": 97.0, "Low": 94.0, "Close": 95.0, "Volume": 1000},
            "2026-11-13",
            {"Open": 96.0, "High": 97.0, "Low": 95.0, "Close": 96.0, "Volume": 1200},
        )
        unadjusted_history = adjusted_history.copy()
        unadjusted_history.loc[
            unadjusted_history.index[0], ["Open", "High", "Low", "Close"]
        ] = [100.0, 102.0, 99.0, 100.0]

        ticker.fast_info = SimpleNamespace(
            lastPrice=96.0,
            previousClose=100.0,
            open=96.0,
            dayHigh=97.0,
            dayLow=95.0,
            lastVolume=1200,
            marketCap=None,
        )
        ticker.history.side_effect = lambda **kwargs: (
            unadjusted_history if kwargs.get("auto_adjust") is False else adjusted_history
        )
        ticker.info = {"shortName": "SamsungElec", "currency": "KRW"}
        config = SimpleNamespace(enable_realtime_quote=True, realtime_cache_ttl=600)

        with (
            patch("yfinance.Ticker", return_value=ticker),
            patch("src.config.get_config", return_value=config),
            patch.object(DataFetcherManager, "_utc_now_iso", return_value="2026-11-13T05:28:00+00:00"),
        ):
            manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
            quote = manager.get_realtime_quote("005930.KS")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 96.0)
        self.assertEqual(quote.pre_close, 100.0)
        self.assertEqual(quote.change_amount, -4.0)
        self.assertEqual(quote.change_pct, -4.0)
        self.assertEqual(quote.quote_date, "2026-11-13")
        self.assertTrue(
            all(call.kwargs["auto_adjust"] is False for call in ticker.history.call_args_list)
        )

    def test_yfinance_stale_history_does_not_use_newer_info_timestamp(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        ticker = MagicMock()
        history = _make_yfinance_history(
            "2026-11-11",
            {"Open": 197100.0, "High": 206500.0, "Low": 196300.0, "Close": 206000.0, "Volume": 16238236},
            "2026-11-12",
            {"Open": 208500.0, "High": 214000.0, "Low": 206000.0, "Close": 208000.0, "Volume": 19721557},
        )
        ticker.fast_info = _HistoryBackedFastInfo(history)
        ticker.history.return_value = history
        ticker.info = {
            "shortName": "SamsungElec",
            "currency": "KRW",
            "regularMarketPrice": 207750.0,
            "regularMarketTime": int(now.timestamp()),
        }
        config = SimpleNamespace(enable_realtime_quote=True, realtime_cache_ttl=600)

        with (
            patch("yfinance.Ticker", return_value=ticker),
            patch("src.config.get_config", return_value=config),
            patch.object(DataFetcherManager, "_utc_now_iso", return_value=now.isoformat()),
        ):
            manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
            quote = manager.get_realtime_quote("005930.KS")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 208000.0)
        self.assertEqual(quote.volume, 19721557)
        self.assertIsNone(quote.provider_timestamp)
        self.assertEqual(quote.quote_date, "2026-11-12")
        self.assertIsNone(quote.is_stale)
        self.assertIsNone(quote.stale_seconds)
        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced = self.pipeline._enhance_context(
                self._kr_005930_context(),
                quote,
                None,
                self._kr_005930_trend(),
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )

        self.assertEqual(enhanced["yesterday"]["date"], "2026-11-11")
        self.assertAlmostEqual(enhanced["price_change_ratio"], 0.97, places=2)
        self.assertAlmostEqual(enhanced["volume_change_ratio"], 1.21, places=2)

    def test_session_shift_requires_matching_market_date_evidence(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        cases = [
            (None, False),
            ("unparseable", False),
            ("2026-11-13-not-a-timestamp", False),
            ("2026-11-12T15:30:00+09:00", False),
            ("2026-11-14T15:30:00+09:00", False),
            ("2026-11-13", True),
            (date(2026, 11, 13), True),
            (datetime(2026, 11, 13, 1, tzinfo=timezone.utc), True),
            ("2026-11-12T23:30:00Z", True),
        ]
        for timestamp, shifts in cases:
            with self.subTest(timestamp=timestamp), \
                    patch("src.core.pipeline.get_market_now", return_value=now):
                enhanced = self.pipeline._enhance_context(
                    self._kr_005930_context(),
                    self._kr_005930_quote(provider_timestamp=timestamp),
                    None, self._kr_005930_trend(), "SamsungElec",
                    fundamental_context={"status": "not_supported"},
                    market_phase_context=phase,
                )
                self.assertEqual(enhanced["yesterday"]["date"],
                                 "2026-11-12" if shifts else "2026-11-11")

    def test_intraday_open_fallback_uses_shifted_yesterday_close(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        stored_context = self._kr_005930_context()
        quote = self._kr_005930_quote(open_price=None, pre_close=None)
        trend = self._kr_005930_trend()

        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced = self.pipeline._enhance_context(
                stored_context,
                quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )

        self.assertEqual(enhanced["today"]["open"], 208000.0)
        self.assertEqual(enhanced["yesterday"]["date"], "2026-11-12")

    def test_missing_or_invalid_quote_time_keeps_baseline_despite_price_changes(self) -> None:
        now = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        context = self._kr_005930_context()
        for timestamp in (None, "invalid", "14:28:00"):
            with self.subTest(provider_timestamp=timestamp):
                quote = self._kr_005930_quote(
                    provider_timestamp=timestamp, fetched_at=now.isoformat(),
                )
                with patch("src.core.pipeline.get_market_now", return_value=now):
                    enhanced = self.pipeline._enhance_context(
                        context, quote, None, self._kr_005930_trend(),
                        stock_name="SamsungElec",
                        fundamental_context={"status": "not_supported"},
                        market_phase_context=phase,
                    )
                self.assertEqual(enhanced["yesterday"], context["yesterday"])

    def test_undated_hk_adapter_quotes_preserve_baseline_and_market_snapshot(self) -> None:
        now = datetime(2026, 11, 13, 9, 31, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        cached_rows = pd.DataFrame([{
            "代码": "00700", "名称": "腾讯控股", "最新价": 110.0,
            "涨跌幅": 10.0, "涨跌额": 10.0, "成交量": 1000,
        }])
        context = {
            "code": "HK00700", "date": "2026-11-12",
            "today": {"date": "2026-11-12", "close": 110.0, "volume": 1000},
            "yesterday": {"date": "2026-11-11", "close": 100.0, "volume": 800},
        }
        trend = TrendAnalysisResult(code="HK00700", ma5=105.0, ma10=102.0, ma20=100.0)
        config = SimpleNamespace(
            enable_realtime_quote=True, realtime_source_priority="akshare_em",
            futu_hk_realtime_source_priority="akshare", enable_eastmoney_patch=False,
        )
        for route in ("em_cache", "sina_fallback"):
            with self.subTest(route=route):
                ak = MagicMock()
                ak.stock_hk_spot.return_value = cached_rows
                cache = {
                    "data": cached_rows if route == "em_cache" else None,
                    # The EM cache was populated before the 09:30 open.
                    "timestamp": now.timestamp() - 660 if route == "em_cache" else now.timestamp(),
                    "last_result": "success" if route == "em_cache" else "failure",
                }
                with (
                    patch.dict(sys.modules, {"akshare": ak}),
                    patch.dict(_hk_realtime_cache, cache),
                    patch("data_provider.akshare_fetcher.time.time", return_value=now.timestamp()),
                    patch("data_provider.akshare_fetcher.get_config", return_value=config),
                    patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker") as breaker,
                    patch.object(AkshareFetcher, "_set_random_user_agent"),
                    patch.object(AkshareFetcher, "_enforce_rate_limit"),
                    patch("src.config.get_config", return_value=config),
                    patch.object(DataFetcherManager, "_utc_now_iso", return_value=now.isoformat()),
                ):
                    breaker.return_value.is_available.return_value = True
                    manager = DataFetcherManager(fetchers=[AkshareFetcher()])
                    quote = manager.get_realtime_quote("HK00700")

                self.assertIsNotNone(quote)
                ak.stock_hk_spot_em.assert_not_called()
                self.assertEqual(ak.stock_hk_spot.call_count, int(route == "sina_fallback"))
                self.assertEqual(quote.fetched_at, now.isoformat())
                for field in ("provider_timestamp", "pre_close", "open_price", "high", "low"):
                    self.assertIsNone(getattr(quote, field))

                for session_now in (now, now.replace(hour=17)):
                    phase = build_market_phase_context(market="hk", current_time=session_now).to_dict()
                    with patch("src.core.pipeline.get_market_now", return_value=session_now):
                        enhanced = self.pipeline._enhance_context(
                            context, quote, None, trend, stock_name="腾讯控股",
                            fundamental_context={"status": "not_supported"},
                            market_phase_context=phase,
                        )

                    self.assertEqual(enhanced["yesterday"], context["yesterday"])
                    self.assertEqual(enhanced["price_change_ratio"], 10.0)
                    self.assertEqual(enhanced["volume_change_ratio"], 1.25)
                    snapshot = GeminiAnalyzer.__new__(GeminiAnalyzer)._build_market_snapshot(enhanced)
                    self.assertEqual(snapshot["prev_close"], "100.00")
                    self.assertEqual(snapshot["change_amount"], "10.00")

    def test_postmarket_shifts_yesterday_for_current_session_quote_but_not_stale_prior_session_quote(self) -> None:
        now = datetime(2026, 11, 13, 17, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        phase = build_market_phase_context(market="kr", current_time=now).to_dict()
        trend = self._kr_005930_trend()

        current_quote = self._kr_005930_quote(provider_timestamp="2026-11-13T15:30:00+09:00")
        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced_current = self.pipeline._enhance_context(
                self._kr_005930_context(),
                current_quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )
        self.assertEqual(enhanced_current["yesterday"]["date"], "2026-11-12")
        self.assertEqual(enhanced_current["price_change_ratio"], -0.12)
        self.assertEqual(enhanced_current["volume_change_ratio"], 0.45)

        stale_ts_quote = self._kr_005930_quote(provider_timestamp="2026-11-12T15:30:00+09:00")
        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced_stale_ts = self.pipeline._enhance_context(
                self._kr_005930_context(),
                stale_ts_quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )
        self.assertEqual(enhanced_stale_ts["yesterday"]["date"], "2026-11-11")

        # Fallback quote with no timestamp repeating the 2026-11-12 bar must not shift yesterday to 11-12.
        stale_fallback_quote = UnifiedRealtimeQuote(
            code="005930.KS",
            name="SamsungElec",
            source=RealtimeSource.FALLBACK,
            price=208000.0,
            pre_close=206000.0,
            open_price=208500.0,
            high=214000.0,
            low=206000.0,
            volume=19721557,
            provider_timestamp=None,
        )
        with patch("src.core.pipeline.get_market_now", return_value=now):
            enhanced_stale_fb = self.pipeline._enhance_context(
                self._kr_005930_context(),
                stale_fallback_quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase,
            )
        self.assertEqual(enhanced_stale_fb["yesterday"]["date"], "2026-11-11")

    def test_premarket_non_trading_missing_phase_and_already_stored_current_bar_keep_yesterday(self) -> None:
        trend = self._kr_005930_trend()
        quote = self._kr_005930_quote()

        for now, expected_phase in (
            (datetime(2026, 11, 13, 8, 0, tzinfo=ZoneInfo("Asia/Seoul")), "premarket"),
            (datetime(2026, 11, 14, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")), "non_trading"),
        ):
            phase = build_market_phase_context(market="kr", current_time=now).to_dict()
            self.assertEqual(phase["phase"], expected_phase)
            with patch("src.core.pipeline.get_market_now", return_value=now):
                enhanced = self.pipeline._enhance_context(
                    self._kr_005930_context(),
                    quote,
                    None,
                    trend,
                    stock_name="SamsungElec",
                    fundamental_context={"status": "not_supported"},
                    market_phase_context=phase,
                )
            self.assertEqual(enhanced["yesterday"]["date"], "2026-11-11")

        # Missing market_phase_context preserves existing yesterday baseline.
        now_intraday = datetime(2026, 11, 13, 14, 28, tzinfo=ZoneInfo("Asia/Seoul"))
        with patch("src.core.pipeline.get_market_now", return_value=now_intraday):
            enhanced_no_phase = self.pipeline._enhance_context(
                self._kr_005930_context(),
                quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=None,
            )
        self.assertEqual(enhanced_no_phase["yesterday"]["date"], "2026-11-11")

        # When stored today already belongs to the current session, keep existing yesterday.
        phase_intraday = build_market_phase_context(market="kr", current_time=now_intraday).to_dict()
        already_current_ctx = self._kr_005930_context(
            today_date="2026-11-13",
            yesterday_date="2026-11-12",
        )
        with patch("src.core.pipeline.get_market_now", return_value=now_intraday):
            enhanced_existing = self.pipeline._enhance_context(
                already_current_ctx,
                quote,
                None,
                trend,
                stock_name="SamsungElec",
                fundamental_context={"status": "not_supported"},
                market_phase_context=phase_intraday,
            )
        self.assertEqual(enhanced_existing["yesterday"]["date"], "2026-11-12")


if __name__ == "__main__":
    unittest.main()
