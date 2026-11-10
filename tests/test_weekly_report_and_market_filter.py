# -*- coding: utf-8 -*-
"""Tests for ANALYSIS_MARKETS filtering, the weekly accuracy report and alert-on-change."""

from datetime import date
from types import SimpleNamespace
from unittest import mock

from main import _filter_by_analysis_markets
from src.services import alert_on_change
from src.services.backtest_weekly_report import build_weekly_report, maybe_send_weekly_report

CODES = ["AAPL", "MSFT", "SAN.MC", "ITX.MC", "7203.T"]
FRIDAY = date(2026, 11, 13)


def test_market_filter_empty_spec_keeps_everything():
    assert _filter_by_analysis_markets(CODES, "") == CODES
    assert _filter_by_analysis_markets(CODES, None) == CODES


def test_market_filter_include_spain_only():
    assert _filter_by_analysis_markets(CODES, "es") == ["SAN.MC", "ITX.MC"]


def test_market_filter_exclude_spain():
    assert _filter_by_analysis_markets(CODES, "-es") == ["AAPL", "MSFT", "7203.T"]


def test_market_filter_include_multiple():
    assert _filter_by_analysis_markets(CODES, "us, jp") == ["AAPL", "MSFT", "7203.T"]


def _summary(completed, accuracy=60.0, win=55.0):
    return {
        "completed_count": completed,
        "eval_window_days": 10,
        "direction_accuracy_pct": accuracy,
        "win_rate_pct": win,
        "avg_stock_return_pct": 1.2,
        "avg_simulated_return_pct": 0.8,
    }


def test_weekly_report_none_without_evaluations():
    assert build_weekly_report(None, {}, today=FRIDAY) is None
    assert build_weekly_report(_summary(0), {}, today=FRIDAY) is None


def test_weekly_report_renders_overall_and_stock_rows():
    content = build_weekly_report(
        _summary(12), {"AAPL": _summary(5, 80.0, 60.0), "SAN.MC": None}, today=FRIDAY
    )
    assert "Direction accuracy:** 60.0%" in content
    assert "| AAPL | 5 | 80.0% | 60.0% |" in content
    assert "SAN.MC" not in content


def _service():
    return SimpleNamespace(get_summary=lambda scope, code: _summary(3))


def test_weekly_report_sent_once_per_week(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKTEST_WEEKLY_REPORT_ENABLED", raising=False)
    notifier = mock.MagicMock()
    notifier.is_available.return_value = True
    notifier.send.return_value = True

    first = maybe_send_weekly_report(_service(), ["AAPL"], today=FRIDAY, data_dir=tmp_path, notifier=notifier)
    second = maybe_send_weekly_report(_service(), ["AAPL"], today=FRIDAY, data_dir=tmp_path, notifier=notifier)

    assert first is True
    assert second is False
    assert notifier.send.call_count == 1


def test_weekly_report_skipped_on_other_days(tmp_path):
    notifier = mock.MagicMock()
    sent = maybe_send_weekly_report(
        _service(), ["AAPL"], today=date(2026, 11, 10), data_dir=tmp_path, notifier=notifier
    )
    assert sent is False
    notifier.send.assert_not_called()


def test_weekly_report_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_WEEKLY_REPORT_ENABLED", "false")
    notifier = mock.MagicMock()
    assert maybe_send_weekly_report(_service(), [], today=FRIDAY, data_dir=tmp_path, notifier=notifier) is False


def _sig(score, action):
    return {"sentiment_score": score, "action": action}


def test_alert_first_analysis_always_notifies():
    assert alert_on_change.should_alert(_sig(50, "hold"), None, 10) is True


def test_alert_action_change_notifies():
    assert alert_on_change.should_alert(_sig(52, "reduce"), _sig(55, "hold"), 10) is True


def test_alert_large_score_move_notifies():
    assert alert_on_change.should_alert(_sig(70, "hold"), _sig(55, "hold"), 10) is True


def test_alert_small_move_same_action_is_quiet():
    assert alert_on_change.should_alert(_sig(58, "hold"), _sig(55, "hold"), 10) is False


def test_filter_changed_results_uses_history(monkeypatch):
    results = [SimpleNamespace(code="AAPL"), SimpleNamespace(code="MSFT")]
    monkeypatch.setattr(alert_on_change, "_current_signal", lambda r: _sig(60, "hold"))
    history = {"AAPL": _sig(59, "hold"), "MSFT": _sig(40, "reduce")}
    monkeypatch.setattr(alert_on_change, "_previous_signal", lambda r: history[r.code])

    changed = alert_on_change.filter_changed_results(results, 10)

    assert [r.code for r in changed] == ["MSFT"]


# --- Spanish news search ---------------------------------------------------

from src.search_service import SearchService  # noqa: E402


def test_spanish_stock_detection():
    assert SearchService._is_spanish_stock("SAN.MC") is True
    assert SearchService._is_spanish_stock("AAPL") is False
    assert SearchService._is_spanish_stock("600519") is False


def test_spanish_query_name_strips_legal_suffix_and_falls_back_to_ticker():
    assert SearchService._spanish_query_name("SAN.MC", "BANCO SANTANDER S.A.") == "BANCO SANTANDER"
    assert SearchService._spanish_query_name("ITX.MC", "Industria de Diseño Textil, S.A.") == "Industria de Diseño Textil"
    assert SearchService._spanish_query_name("SAN.MC", "") == "SAN"
    assert SearchService._spanish_query_name("SAN.MC", "SAN.MC") == "SAN"


def test_spanish_brave_locale():
    assert SearchService._brave_search_locale("SAN.MC", prefer_chinese=False) == {"search_lang": "es", "country": "ES"}


# --- Regression: Spanish reports with a data source crashed (KeyError: 'es') ---

def test_spanish_reports_render_with_snapshot_source():
    from src.analyzer import AnalysisResult
    from src.notification import NotificationService

    result = AnalysisResult(
        code="SAN.MC", name="Banco Santander", sentiment_score=55,
        trend_prediction="看多", operation_advice="持有",
    )
    result.report_language = "es"
    result.market_snapshot = {
        "close": "11.30", "source": "fallback", "price": "11.30",
        "raw": {"close": 11.3, "prev_close": 10.7, "pct_chg": 5.6, "currency": "EUR"},
    }
    service = NotificationService()

    single = service.generate_single_stock_report(result)
    dashboard = service.generate_dashboard_report([result])

    assert "€11.30" in single
    assert "Fallback" in single
    assert "SAN.MC" in dashboard
