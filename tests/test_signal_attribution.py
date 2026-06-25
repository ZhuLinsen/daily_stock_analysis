# -*- coding: utf-8 -*-
"""Tests for signal_attribution feature (Issue #1742)."""

import pytest
from src.schemas.report_schema import SignalAttribution, Dashboard
from src.report_language import _REPORT_LABELS


class TestSignalAttributionSchema:
    """Test SignalAttribution schema validation and normalization."""

    def test_valid_contributions(self):
        """Test valid contribution weights."""
        attr = SignalAttribution(
            technical_indicators=70,
            news_sentiment=0,
            fundamentals=15,
            market_conditions=15,
            strongest_bullish_signal="MACD金叉",
            strongest_bearish_signal=None
        )
        # Sum should be normalized to 100
        total = sum([
            attr.technical_indicators or 0,
            attr.news_sentiment or 0,
            attr.fundamentals or 0,
            attr.market_conditions or 0
        ])
        assert total == 100

    def test_string_contributions(self):
        """Test string contribution weights are converted to numbers."""
        attr = SignalAttribution(
            technical_indicators="70",
            news_sentiment="0",
            fundamentals="15",
            market_conditions="15"
        )
        assert isinstance(attr.technical_indicators, (int, float))
        assert attr.technical_indicators == 70

    def test_percent_string_contributions(self):
        """Test percent string contribution weights are converted to numbers."""
        attr = SignalAttribution(
            technical_indicators="70%",
            news_sentiment="0%",
            fundamentals="15%",
            market_conditions="15%"
        )
        assert isinstance(attr.technical_indicators, (int, float))
        assert attr.technical_indicators == 70

    def test_na_string_contributions(self):
        """Test N/A string contribution weights are converted to None."""
        attr = SignalAttribution(
            technical_indicators="N/A",
            news_sentiment=0,
            fundamentals=0,
            market_conditions=0
        )
        assert attr.technical_indicators is None

    def test_none_string_contributions(self):
        """Test None string contribution weights are converted to None."""
        attr = SignalAttribution(
            technical_indicators="None",
            news_sentiment=0,
            fundamentals=0,
            market_conditions=0
        )
        assert attr.technical_indicators is None

    def test_negative_contributions(self):
        """Test negative contribution weights are clamped to 0."""
        attr = SignalAttribution(
            technical_indicators=-10,
            news_sentiment=20,
            fundamentals=30,
            market_conditions=60
        )
        assert attr.technical_indicators == 0

    def test_contributions_sum_not_100(self):
        """Test contribution weights are normalized when sum != 100."""
        attr = SignalAttribution(
            technical_indicators=70,
            news_sentiment=10,
            fundamentals=20,
            market_conditions=10
        )
        # Sum is 110, should be normalized to 100
        total = sum([
            attr.technical_indicators or 0,
            attr.news_sentiment or 0,
            attr.fundamentals or 0,
            attr.market_conditions or 0
        ])
        assert total == 100

    def test_contributions_sum_less_than_100(self):
        """Test contribution weights are normalized when sum < 100."""
        attr = SignalAttribution(
            technical_indicators=50,
            news_sentiment=10,
            fundamentals=20,
            market_conditions=10
        )
        # Sum is 90, should be normalized to 100
        total = sum([
            attr.technical_indicators or 0,
            attr.news_sentiment or 0,
            attr.fundamentals or 0,
            attr.market_conditions or 0
        ])
        assert total == 100

    def test_partial_none_contributions(self):
        """Test when some contributions are None."""
        attr = SignalAttribution(
            technical_indicators=70,
            news_sentiment=None,
            fundamentals=30,
            market_conditions=None
        )
        # Only normalize if all four are valid numbers
        # In this case, some are None, so no normalization
        assert attr.technical_indicators == 70
        assert attr.news_sentiment is None

    def test_all_none_contributions(self):
        """Test when all contributions are None."""
        attr = SignalAttribution(
            technical_indicators=None,
            news_sentiment=None,
            fundamentals=None,
            market_conditions=None
        )
        assert attr.technical_indicators is None
        assert attr.news_sentiment is None

    def test_dashboard_with_signal_attribution(self):
        """Test Dashboard model with signal_attribution."""
        dashboard = Dashboard(
            signal_attribution=SignalAttribution(
                technical_indicators=70,
                news_sentiment=0,
                fundamentals=15,
                market_conditions=15,
                strongest_bullish_signal="MACD金叉",
                strongest_bearish_signal=None
            )
        )
        assert dashboard.signal_attribution is not None
        assert dashboard.signal_attribution.technical_indicators == 70

    def test_signal_attribution_optional(self):
        """Test Dashboard model without signal_attribution."""
        dashboard = Dashboard()
        assert dashboard.signal_attribution is None


class TestSignalAttributionLabels:
    """Test signal_attribution internationalization labels."""

    def test_zh_labels_exist(self):
        """Test Chinese labels exist."""
        labels = _REPORT_LABELS["zh"]
        assert "signal_attribution_heading" in labels
        assert "attribution_weights_label" in labels
        assert "technical_indicators_label" in labels
        assert "news_sentiment_label" in labels
        assert "fundamentals_label" in labels
        assert "market_conditions_label" in labels
        assert "strongest_bullish_signal_label" in labels
        assert "strongest_bearish_signal_label" in labels

    def test_en_labels_exist(self):
        """Test English labels exist."""
        labels = _REPORT_LABELS["en"]
        assert "signal_attribution_heading" in labels
        assert "attribution_weights_label" in labels
        assert "technical_indicators_label" in labels
        assert "news_sentiment_label" in labels
        assert "fundamentals_label" in labels
        assert "market_conditions_label" in labels
        assert "strongest_bullish_signal_label" in labels
        assert "strongest_bearish_signal_label" in labels

    def test_zh_labels_content(self):
        """Test Chinese labels content."""
        labels = _REPORT_LABELS["zh"]
        assert labels["signal_attribution_heading"] == "信号归因分析"
        assert labels["technical_indicators_label"] == "技术指标"

    def test_en_labels_content(self):
        """Test English labels content."""
        labels = _REPORT_LABELS["en"]
        assert labels["signal_attribution_heading"] == "Signal Attribution"
        assert labels["technical_indicators_label"] == "Technical Indicators"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
