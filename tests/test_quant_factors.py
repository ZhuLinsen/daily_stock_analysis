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
        flat_df = _make_ohlcv([50.0] * 40, volumes=[0.0] * 40, spread=0.0)
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
        assert res.donchian_high_20 < 125.0  # prior bars exclude current bar
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
        # Wide oscillation first 30 days (+-8%), then tight flat range for last 15 days (+-0.2%)
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
        closes = [120.0 - i * 1.2 for i in range(45)]
        vols = [1_500_000.0] * 45
        df = _make_ohlcv(closes, volumes=vols, spread=0.01)

        res = compute_quant_factors(df, "688001")
        assert res.sufficient_data is True
        assert res.donchian_signal == "breakdown_20_low"
        assert res.roc_20_pct is not None and res.roc_20_pct < 0
        assert res.max_drawdown_60_pct is not None and res.max_drawdown_60_pct < -15.0
        assert res.kdj_status in ("oversold", "death_cross_high", "death_cross")
        assert res.adx_direction == "bearish"
        assert res.quant_composite_score < 45


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

        sample_df = _make_ohlcv([50.0 + i * 0.4 for i in range(50)])
        with mock.patch("src.services.history_loader.load_history_df", return_value=(sample_df, "akshare")) as mock_loader:
            out = _handle_calculate_quant_factors("600519", days=999)

        mock_loader.assert_called_once_with("600519", days=365)
        assert out["sufficient_data"] is True
        assert out["source"] == "akshare"
        assert "atr_stop_loss_long" in out

        with mock.patch("src.services.history_loader.load_history_df", return_value=(pd.DataFrame(), "akshare")):
            err = _handle_calculate_quant_factors("600519")
        assert "error" in err

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
