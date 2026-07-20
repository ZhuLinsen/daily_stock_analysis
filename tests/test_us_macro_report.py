from datetime import datetime, timezone

from src.core.us_macro import run_us_macro_report
from src.schemas.macro import MacroObservation
from src.services.us_macro_report import USMacroReport, USMacroReportService


class MarketService:
    def fetch(self):
        return ([
            {"indicator": "vix", "symbol": "VIX", "value": 15.0, "change_1d": -1.0, "change_5d": -12.0},
            {"indicator": "sp500", "symbol": "SPX", "value": 6000.0, "above_ma_20": True, "above_ma_50": True},
        ], [])


class FRED:
    def fetch_latest(self, indicator, series_id):
        values = {"treasury_2y": 4.0, "treasury_10y": 4.2}
        if indicator not in values:
            return None
        return MacroObservation(
            region="us", indicator=indicator, series_id=series_id, value=values[indicator], unit="Percent",
            observation_date=datetime(2026, 7, 18, tzinfo=timezone.utc).date(), fetched_at=datetime.now(timezone.utc),
            source_name="FRED", source_url="https://fred.example", frequency="Daily",
        )


def test_us_macro_report_degrades_without_fred_key():
    report = USMacroReportService(market_service=MarketService()).build_report()
    assert report.snapshot.observations == []
    assert "未配置 FRED_API_KEY" in report.markdown
    assert "市场快照" in report.markdown


def test_us_macro_report_renders_rules_and_sources():
    report = USMacroReportService(fred_provider=FRED(), market_service=MarketService()).build_report()
    assert report.assessment["regime"] == "risk_on"
    assert "[FRED](https://fred.example)" in report.markdown
    assert "未来1周：偏多" in report.markdown


def test_runtime_persists_saves_and_can_skip_notification(monkeypatch):
    built = USMacroReportService(fred_provider=FRED(), market_service=MarketService()).build_report()

    class Service:
        def build_report(self):
            return built

    class Notifier:
        def __init__(self):
            self.saved = []
            self.sent = []

        def save_report_to_file(self, content, filename):
            self.saved.append((content, filename))

        def send(self, content, **kwargs):
            self.sent.append((content, kwargs))
            return True

    monkeypatch.setattr("src.core.us_macro._persist_report", lambda report: 42)
    notifier = Notifier()
    report = run_us_macro_report(
        config=object(), service=Service(), notifier=notifier,
        send_notification=False, save_report_file=True, trigger_source="test",
    )
    assert report is built
    assert notifier.saved[0][1] == "us_macro_report.md"
    assert notifier.sent == []


def test_fred_failure_logs_no_request_details(caplog):
    class FailingFRED:
        def fetch_latest(self, indicator, series_id):
            raise RuntimeError("https://example.invalid/?api_key=must-not-appear")

    USMacroReportService(fred_provider=FailingFRED(), market_service=MarketService()).build_report()
    assert "must-not-appear" not in caplog.text
    assert "RuntimeError" in caplog.text
