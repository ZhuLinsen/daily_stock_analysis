from __future__ import annotations

from datetime import date

from src.core.sentiment_review import SentimentReviewRunner


class Row:
    id = 7
    run_status = "success"
    data_quality = "complete"
    trade_date = date(2026, 6, 26)
    llm_analysis = "行情总结"
    llm_next_day_watch = "观察方向"
    llm_risk_notes = "风险"
    def payload(self): return {"trade_date": "2026-06-26"}


class Repo:
    def __init__(self): self.row = None; self.saved = 0
    def get_daily(self, market, trade_date): return self.row
    def upsert_daily(self, **kwargs): self.saved += 1; self.row = Row(); return self.row
    def replace_stocks(self, daily_id, stocks): self.stocks = stocks


class Service:
    def calculate_for_date(self, trade_date, market="cn"):
        return {
            "structured_payload": {"trade_date": trade_date.isoformat()},
            "stock_evidence": [{"code": "1"}],
            "provider_trace": {"market": "fake"},
            "completeness": {"market": True},
            "quality": "complete",
        }


def test_runner_persists_metrics_and_llm_narrative_once() -> None:
    repo = Repo()
    runner = SentimentReviewRunner(
        repository=repo,
        service=Service(),
        narrative_generator=lambda payload: {
            "analysis": "行情总结", "next_day_watch": "观察方向", "risk_notes": "风险",
        },
    )
    first = runner.run(date(2026, 6, 26))
    second = runner.run(date(2026, 6, 26))
    assert first["status"] == "success"
    assert second["status"] == "existing"
    assert repo.saved == 1
    assert repo.stocks == [{"code": "1"}]


def test_runner_upgrades_imported_record_without_force() -> None:
    repo = Repo()
    repo.row = Row()
    repo.row.data_quality = "imported"
    runner = SentimentReviewRunner(repository=repo, service=Service(), narrative_generator=None)
    result = runner.run(date(2026, 6, 26))
    assert result["status"] == "success"
    assert repo.saved == 1
