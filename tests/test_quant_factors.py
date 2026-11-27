# -*- coding: utf-8 -*-
"""Offline unit tests for the quantitative multi-factor engine, tools, and quant strategies."""

from datetime import date, timedelta
import math
from unittest import mock
import warnings

import pandas as pd

from src.quant_factors import QuantFactorResult, compute_quant_factors


def _make_ohlcv(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    spread: float = 0.015,
) -> pd.DataFrame:
    start = date(2026, 1, 1)
    n = len(closes)
    vols = volumes if volumes is not None else [1_000_000.0] * n
    rows = []
    for idx, close in enumerate(closes):
        open_px = closes[idx - 1] if idx > 0 else close
        high = max(open_px, close) * (1.0 + spread)
        low = max(0.01, min(open_px, close) * (1.0 - spread))
        rows.append(
            {
                "date": (start + timedelta(days=idx)).isoformat(),
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": vols[idx],
            }
        )
    return pd.DataFrame(rows)


def _assert_json_finite(payload: dict) -> None:
    for key, val in payload.items():
        if isinstance(val, float):
            assert math.isfinite(val), f"{key} is not finite: {val}"


class TestComputeQuantFactors:
    def test_insufficient_data_returns_safe_default(self):
        short_df = _make_ohlcv([10.0 + i * 0.1 for i in range(15)])
        res = compute_quant_factors(short_df, "600519")
        assert isinstance(res, QuantFactorResult)
        assert res.sufficient_data is False
        assert res.bars_analyzed == 15
        assert res.quant_regime == "insufficient_data"
        _assert_json_finite(res.to_dict())

    def test_flat_zero_volume_series_never_produces_nan_or_inf(self):
        flat_df = _make_ohlcv([50.0] * 60, volumes=[0.0] * 60, spread=0.0)
        res = compute_quant_factors(flat_df, "000001")
        assert res.sufficient_data is True
        assert res.boll_bandwidth_pct == 0.0
        assert res.boll_pct_b == 0.5
        assert res.vwap_20 is None
        assert res.mfi_14 is None
        assert res.obv_trend == "flat"
        assert res.max_drawdown_60_pct == 0.0
        assert 0 <= res.quant_composite_score <= 100
        _assert_json_finite(res.to_dict())

    def test_strong_uptrend_with_donchian_breakout_and_no_lookahead(self):
        # 59 oscillating bars capped <= 110, then final bar breaks cleanly above 20d high to 125
        closes = [100.0 + (i % 5) * 1.5 for i in range(59)] + [125.0]
        vols = [1_000_000.0] * 59 + [2_500_000.0]
        df = _make_ohlcv(closes, volumes=vols, spread=0.01)

        res = compute_quant_factors(df, "600519")
        assert res.sufficient_data is True
        assert res.donchian_high_20 is not None and res.donchian_high_20 < 125.0  # prior bars exclude current bar
        assert res.donchian_signal == "breakout_20_high"
        assert res.atr_stop_loss_long < res.current_price < res.atr_take_profit_2r
        assert res.roc_20_pct is not None and res.roc_20_pct > 10.0
        assert res.obv_trend == "rising"
        assert res.vwap_20 is not None and res.vwap_bias_pct is not None and res.vwap_bias_pct > 0
        assert res.mfi_14 is not None and 0.0 <= res.mfi_14 <= 100.0
        assert res.max_drawdown_60_pct is not None and res.max_drawdown_60_pct <= 0.0
        assert res.adx_14 is not None
        assert res.quant_composite_score >= 65
        _assert_json_finite(res.to_dict())

    def test_volatility_squeeze_and_vcp_contraction_detected(self):
        # Wide oscillation first 30 days (+-8%), then tight flat range for last 20 days (+-0.2%)
        wide = [100.0 + ((-1) ** i) * 6.0 for i in range(30)]
        tight = [100.5 + ((-1) ** i) * 0.15 for i in range(20)]
        rows = []
        start = date(2026, 1, 1)
        for idx, c in enumerate(wide + tight):
            spread = 0.03 if idx < 30 else 0.002
            rows.append(
                {
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": c,
                    "high": c * (1.0 + spread),
                    "low": c * (1.0 - spread),
                    "close": c,
                    "volume": 2_000_000.0 if idx < 30 else 600_000.0,
                }
            )
        df = pd.DataFrame(rows)
        res = compute_quant_factors(df, "300750")
        assert res.sufficient_data is True
        assert res.boll_squeeze is True
        assert res.vcp_contraction_ratio is not None and res.vcp_contraction_ratio < 0.5
        assert res.quant_regime == "volatility_squeeze"

    def test_downtrend_triggers_oversold_and_negative_momentum(self):
        closes = [120.0 - i * 1.0 for i in range(60)]
        vols = [1_500_000.0] * 60
        df = _make_ohlcv(closes, volumes=vols, spread=0.01)

        res = compute_quant_factors(df, "688001")
        assert res.sufficient_data is True
        assert res.donchian_signal == "breakdown_20_low"
        assert res.roc_20_pct is not None and res.roc_20_pct < 0
        assert res.max_drawdown_60_pct is not None and res.max_drawdown_60_pct < -15.0
        assert res.kdj_status in ("oversold", "death_cross_high", "death_cross")
        assert res.adx_direction == "bearish"
        assert res.quant_composite_score < 45

    def test_window_sufficiency_gates_short_20d_and_60d_metrics(self):
        # Exactly 20 bars: insufficient for full 20-bar prior Donchian or 60-day risk metrics
        df_20 = _make_ohlcv([100.0 + i * 0.5 for i in range(20)], spread=0.01)
        res_20 = compute_quant_factors(df_20, "600519")
        assert res_20.sufficient_data is True
        assert res_20.donchian_high_20 is None
        assert res_20.donchian_low_20 is None
        assert res_20.donchian_signal != "breakout_20_high"
        assert res_20.max_drawdown_60_pct is None
        assert res_20.dist_from_high_60_pct is None
        assert res_20.sharpe_60 is None

        # 35 bars: enough for 20d Donchian (>=21) and VCP (>=31), NOT enough for 60d risk metrics
        df_35 = _make_ohlcv([100.0 + i * 0.4 for i in range(35)], spread=0.01)
        res_35 = compute_quant_factors(df_35, "600519")
        assert res_35.donchian_high_20 is not None
        assert res_35.vcp_contraction_ratio is not None
        assert res_35.max_drawdown_60_pct is None
        assert res_35.dist_from_high_60_pct is None
        assert res_35.sharpe_60 is None

    def test_chandelier_trailing_stop_detects_post_entry_drawdown_breach(self):
        # 60 flat bars at 100 -> breakout day at 110 -> next day pullback to 104
        # Entry day 2N stop is >104; next-day Chandelier stop anchored to prior peak 110 detects breach.
        closes = [100.0] * 60 + [110.0, 104.0]
        df = _make_ohlcv(closes, spread=0.0)
        res = compute_quant_factors(df, "600519")
        assert res.atr_trailing_stop_long is not None
        assert res.atr_trailing_stop_long > 104.0
        assert res.atr_trailing_stop_breached is True
        assert any("trailing stop breached" in s.lower() for s in res.factor_signals)

    def test_prior_bar_squeeze_and_vcp_preserved_on_breakout_day(self):
        wide = [100.0 + ((-1) ** i) * 6.0 for i in range(30)]
        tight = [100.2 + ((-1) ** i) * 0.1 for i in range(20)]
        rows = []
        start = date(2026, 1, 1)
        for idx, c in enumerate(wide + tight):
            spread = 0.03 if idx < 30 else 0.002
            rows.append(
                {
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": c,
                    "high": c * (1.0 + spread),
                    "low": c * (1.0 - spread),
                    "close": c,
                    "volume": 2_000_000.0 if idx < 30 else 600_000.0,
                }
            )
        # Breakout day expands strongly on high volume -> today's BW widens, prior squeeze & VCP stay True
        rows.append(
            {
                "date": (start + timedelta(days=50)).isoformat(),
                "open": 100.5,
                "high": 112.0,
                "low": 100.5,
                "close": 112.0,
                "volume": 3_000_000.0,
            }
        )
        df = pd.DataFrame(rows)
        res = compute_quant_factors(df, "300750")
        assert res.donchian_signal == "breakout_20_high"
        assert res.prev_boll_bandwidth_pct is not None and res.prev_boll_bandwidth_pct < 6.0
        assert res.boll_squeeze_prior is True
        assert res.boll_squeeze_breakout is True
        assert res.vcp_contraction_ratio is not None and res.vcp_contraction_ratio < 0.70

    def test_missing_zero_low_placeholder_is_sanitized_to_close(self):
        rows = []
        start = date(2026, 1, 1)
        for idx in range(25):
            close = 100.0 if idx < 24 else 95.0
            rows.append(
                {
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": close,
                    "high": close + 1.0,
                    "low": 0.0 if idx == 20 else close - 1.0,  # AlphaVantage missing low=0.0 placeholder
                    "close": close,
                    "volume": 1_000_000.0,
                }
            )
        res = compute_quant_factors(pd.DataFrame(rows), "AAPL")
        assert res.donchian_low_20 is not None
        assert res.donchian_low_20 >= 99.0
        assert res.donchian_signal == "breakdown_20_low"


class TestStockAnalyzerIntegration:
    def test_trend_analyzer_attaches_quant_factors_without_breaking_legacy_signal(self):
        from src.stock_analyzer import StockTrendAnalyzer

        closes = [100.0 + i * 0.6 for i in range(45)]
        df = _make_ohlcv(closes)
        analyzer = StockTrendAnalyzer()
        result = analyzer.analyze(df, "600519")

        assert result.quant_factors is not None
        assert result.quant_factors["sufficient_data"] is True
        payload = result.to_dict()
        assert "quant_factors" in payload
        assert payload["signal_score"] == result.signal_score
        formatted = analyzer.format_analysis(result)
        assert "量化多因子指标" in formatted
        assert "BOLL(20,2)" in formatted


class TestQuantAgentToolAndStrategies:
    def test_calculate_quant_factors_tool_registered_and_runs_offline(self):
        from src.agent.agents.technical_agent import TechnicalAgent
        from src.agent.factory import get_tool_registry
        from src.agent.tools.analysis_tools import _handle_calculate_quant_factors

        assert "calculate_quant_factors" in TechnicalAgent.tool_names
        registry = get_tool_registry()
        td = registry.resolve("calculate_quant_factors")
        assert td is not None
        assert td.category == "analysis"

        sample_df = _make_ohlcv([50.0 + i * 0.4 for i in range(65)])
        with mock.patch("src.services.history_loader.load_history_df", return_value=(sample_df, "akshare")) as mock_loader:
            out = _handle_calculate_quant_factors("600519", days=999)

        mock_loader.assert_called_once_with("600519", days=365, min_records=61)
        assert out["sufficient_data"] is True
        assert out["source"] == "akshare"
        assert "atr_stop_loss_long" in out

        # Verify days truncation slices returned buffered frame to requested lookback window
        with mock.patch("src.services.history_loader.load_history_df", return_value=(sample_df, "db_cache")):
            out_30 = _handle_calculate_quant_factors("600519", days=30)
        assert out_30["bars_analyzed"] == 30
        assert out_30["max_drawdown_60_pct"] is None

        # Verify frozen date cutoff defensively drops post-freeze rows
        from src.services.history_loader import reset_frozen_target_date, set_frozen_target_date

        frozen = date(2026, 2, 15)
        token = set_frozen_target_date(frozen)
        try:
            post_row_df = sample_df.copy()
            post_row_df.loc[len(post_row_df)] = {
                "date": "2026-03-30",
                "open": 130.0,
                "high": 130.0,
                "low": 130.0,
                "close": 130.0,
                "volume": 2_000_000.0,
            }
            with mock.patch("src.services.history_loader.load_history_df", return_value=(post_row_df, "akshare")):
                out_frozen = _handle_calculate_quant_factors("600519", days=60)
            assert out_frozen["current_price"] < 120.0
        finally:
            reset_frozen_target_date(token)

        with mock.patch("src.services.history_loader.load_history_df", return_value=(pd.DataFrame(), "akshare")):
            err = _handle_calculate_quant_factors("600519")
        assert "error" in err

    def test_normal_analysis_prompt_receives_precomputed_quant_factors_when_available(self):
        from src.analyzer import _format_quant_factors_prompt_section
        from src.stock_analyzer import StockTrendAnalyzer

        df = _make_ohlcv([100.0 + i * 0.5 for i in range(65)])
        trend_res = StockTrendAnalyzer().analyze(df, "600519")
        assert trend_res.quant_factors is not None

        zh_block = _format_quant_factors_prompt_section(trend_res.quant_factors, english=False)
        en_block = _format_quant_factors_prompt_section(trend_res.quant_factors, english=True)
        assert "量化多因子指标" in zh_block
        assert "atr_trailing_stop_long=" in zh_block
        assert "atr_trailing_stop_breached=" in zh_block
        assert "boll_squeeze_prior=" in zh_block
        assert "sharpe_60=" in zh_block
        assert "Quantitative Multi-Factor Indicators" in en_block
        assert "sharpe_60=" in en_block

    def test_five_new_quant_strategies_load_group_and_localize(self):
        from src.agent.skills.base import SkillManager
        from src.report_language import localize_strategy_skill

        expected_quant_ids = [
            "bollinger_squeeze",
            "rsi_mean_reversion",
            "turtle_donchian",
            "momentum_quality",
            "vcp_breakout",
        ]

        manager = SkillManager()
        loaded_count = manager.load_builtin_strategies()
        assert loaded_count >= 20

        skills_by_id = {skill.name: skill for skill in manager.list_skills()}
        for sid in expected_quant_ids:
            assert sid in skills_by_id
            assert skills_by_id[sid].category == "quant"
            assert "calculate_quant_factors" in skills_by_id[sid].required_tools
            assert localize_strategy_skill(sid, "zh") == skills_by_id[sid].display_name
            assert localize_strategy_skill(sid, "en") != sid
            assert localize_strategy_skill(sid, "ko") != sid

        manager.activate(expected_quant_ids)
        prompt_text = manager.get_skill_instructions()
        assert "#### 量化因子类技能" in prompt_text
        for sid in expected_quant_ids:
            assert skills_by_id[sid].display_name in prompt_text

    def test_flat_series_emits_no_runtime_warning_and_api_surfaces_quant_metadata(self):
        from api.v1.endpoints.agent import TOOL_DISPLAY_NAMES, _build_skills_response
        from src.agent.runner import _THINKING_TOOL_LABELS
        from src.config import Config

        flat_df = _make_ohlcv([42.0] * 35, volumes=[0.0] * 35, spread=0.0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            res = compute_quant_factors(flat_df, "000001")
        assert res.sufficient_data is True

        assert "calculate_quant_factors" in TOOL_DISPLAY_NAMES
        assert "calculate_quant_factors" in _THINKING_TOOL_LABELS

        payload = _build_skills_response(Config())
        by_id = {item.id: item for item in payload.skills}
        for sid in (
            "bollinger_squeeze",
            "rsi_mean_reversion",
            "turtle_donchian",
            "momentum_quality",
            "vcp_breakout",
        ):
            assert sid in by_id
            assert by_id[sid].category == "quant"

    def test_calculate_quant_factors_requires_61_bars_from_cache_and_fetches_longer_window(self):
        from src.agent.tools.analysis_tools import _handle_calculate_quant_factors
        from src.services.history_loader import reset_frozen_target_date, set_frozen_target_date

        target = date(2026, 4, 24)
        closes_60 = [100.0 + i * 0.2 for i in range(60)]
        db_df = _make_ohlcv(closes_60)
        db_df["date"] = [(target - timedelta(days=59 - i)).isoformat() for i in range(60)]
        db_bars = []
        for row in db_df.to_dict("records"):
            bar = mock.MagicMock()
            bar.to_dict.return_value = row
            bar.date = date.fromisoformat(row["date"])
            db_bars.append(bar)

        closes_65 = [98.0 + i * 0.25 for i in range(65)]
        provider_df = _make_ohlcv(closes_65)
        provider_df["date"] = [(target - timedelta(days=64 - i)).isoformat() for i in range(65)]

        mock_db = mock.MagicMock()
        mock_db.get_data_range.return_value = db_bars
        mock_fm = mock.MagicMock()
        mock_fm.get_daily_data.return_value = (provider_df, "akshare")

        token = set_frozen_target_date(target)
        try:
            with (
                mock.patch("src.storage.get_db", return_value=mock_db),
                mock.patch("src.services.history_loader._get_fetcher_manager", return_value=mock_fm),
            ):
                out_120 = _handle_calculate_quant_factors("600519", days=120)
                out_61 = _handle_calculate_quant_factors("600519", days=61)
        finally:
            reset_frozen_target_date(token)

        assert mock_fm.get_daily_data.call_count == 2
        assert out_120["source"] == "akshare"
        assert out_120["bars_analyzed"] == 65
        assert out_120["roc_60_pct"] is not None
        assert out_61["source"] == "akshare"
        assert out_61["bars_analyzed"] == 61
        assert out_61["roc_60_pct"] is not None

    def test_stale_cache_fallback_attaches_date_and_warning_on_trend_and_quant_tools(self):
        from src.agent.tools.analysis_tools import _handle_analyze_trend, _handle_calculate_quant_factors
        from src.services.history_loader import reset_frozen_target_date, set_frozen_target_date

        stale_end = date(2026, 11, 24)
        frozen_target = date(2026, 11, 25)
        stale_df = _make_ohlcv([100.0 + i * 0.25 for i in range(60)])
        stale_df["date"] = [(stale_end - timedelta(days=59 - i)).isoformat() for i in range(60)]
        stale_bars = []
        for row in stale_df.to_dict("records"):
            bar = mock.MagicMock()
            bar.to_dict.return_value = row
            bar.date = date.fromisoformat(row["date"])
            stale_bars.append(bar)

        mock_db = mock.MagicMock()
        mock_db.get_data_range.return_value = stale_bars
        mock_fm = mock.MagicMock()
        mock_fm.get_daily_data.return_value = (pd.DataFrame(), "AkshareFetcher")

        token = set_frozen_target_date(frozen_target)
        try:
            with (
                mock.patch("src.storage.get_db", return_value=mock_db),
                mock.patch("src.services.history_loader._get_fetcher_manager", return_value=mock_fm),
            ):
                trend_out = _handle_analyze_trend("600519")
                quant_out = _handle_calculate_quant_factors("600519", days=60)
        finally:
            reset_frozen_target_date(token)

        for payload in (trend_out, quant_out):
            assert payload["source"] == "db_cache_stale"
            assert payload["data_date"] == "2026-11-24"
            assert payload["is_stale"] is True
            assert "2026-11-24" in payload["stale_warning"]
            assert "2026-11-25" in payload["stale_warning"]

    def test_slow_steady_drift_during_squeeze_does_not_trigger_boll_squeeze_breakout(self):
        start = date(2026, 1, 1)
        rows = []
        for idx in range(65):
            c = 100.0 + idx * 0.10
            rows.append(
                {
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": c,
                    "high": c + 0.40,
                    "low": c - 0.40,
                    "close": c,
                    "volume": 1_000_000.0,
                }
            )
        res = compute_quant_factors(pd.DataFrame(rows), "600519")
        assert res.donchian_signal == "inside"
        assert res.boll_squeeze_breakout is False

    def test_non_agent_prompt_and_pipeline_context_expose_ma60_volume_ratio_and_rsi6(self):
        from src.analyzer import _format_quant_factors_prompt_section
        from src.config import Config
        from src.core.pipeline import StockAnalysisPipeline
        from src.stock_analyzer import StockTrendAnalyzer

        df_65 = _make_ohlcv([100.0 + i * 0.4 for i in range(65)])
        trend_65 = StockTrendAnalyzer().analyze(df_65, "600519")
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = Config()
        pipeline.search_service = None

        enhanced = pipeline._enhance_context(
            {"code": "600519"},
            None,
            None,
            trend_65,
            stock_name="贵州茅台",
            fundamental_context={},
        )
        ta = enhanced["trend_analysis"]
        for key in ("ma60", "volume_ratio_5d", "rsi_6", "rsi_12", "rsi_24", "rsi_status"):
            assert key in ta

        zh_block = _format_quant_factors_prompt_section(trend_65.quant_factors, english=False, trend=ta)
        en_block = _format_quant_factors_prompt_section(trend_65.quant_factors, english=True, trend=ta)
        for block in (zh_block, en_block):
            assert "MA60=" in block
            assert "MA60=N/A" not in block
            assert "volume_ratio_5d" in block
            assert "1.00" in block
            assert "RSI(6/12/24)=" in block

        df_35 = _make_ohlcv([100.0 + i * 0.4 for i in range(35)])
        trend_35 = StockTrendAnalyzer().analyze(df_35, "600519")
        short_ta = {
            "ma60": trend_35.ma60,
            "volume_ratio_5d": trend_35.volume_ratio_5d,
            "rsi_6": trend_35.rsi_6,
            "rsi_12": trend_35.rsi_12,
            "rsi_24": trend_35.rsi_24,
            "rsi_status": trend_35.rsi_status.value,
        }
        short_block = _format_quant_factors_prompt_section(trend_35.quant_factors, english=True, trend=short_ta)
        assert "MA60=N/A" in short_block
        assert "volume_ratio_5d=" in short_block
        assert "RSI(6/12/24)=" in short_block
