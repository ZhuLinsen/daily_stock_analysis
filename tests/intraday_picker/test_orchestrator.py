from datetime import datetime

from src.services.intraday_picker.config import IntradayPickerConfig
from src.services.intraday_picker.models import StrategyHit
from src.services.intraday_picker.orchestrator import IntradayPickerOrchestrator


class FakeStrategy:
    def screen(self, profile, now):
        return [
            StrategyHit(
                stock_code="600000",
                stock_name="A",
                price=10.5,
                change_pct=3.0,
                strategy_id="capital_heat",
                strategy_score=85,
                raw={"量比": 2.0, "MA20": 10.0, "breakout_score": 80},
            ),
            StrategyHit(
                stock_code="600000",
                stock_name="A",
                price=10.5,
                change_pct=3.0,
                strategy_id="volume_breakout",
                strategy_score=82,
                raw={"量比": 2.0},
            ),
        ]


class FakeMarket:
    def get_intraday_context(self, stock_code, now):
        return {
            "price": 10.5,
            "open": 10.0,
            "high": 10.6,
            "low": 9.9,
            "cumulative_amount": 300,
        }


class FakeHistory:
    def get_or_build_baseline(self, stock_code, now, market_gateway):
        return [{"cumulative_amount": 100} for _ in range(10)]


class FakeDsa:
    def __init__(self):
        self.submitted = False

    def submit_or_reuse(self, candidates, now):
        self.submitted = True
        return {candidates[0].stock_code: "task-1"}

    def collect_available(self, candidates, now):
        return {}


class FakeNotify:
    def __init__(self):
        self.preliminary = False

    def send_preliminary(self, run_id, candidates):
        self.preliminary = True

    def send_final(self, run_id, candidates):
        pass


class FakeState:
    def __init__(self):
        self.saved = False

    def is_completed(self, run_id):
        return False

    def save_preliminary(self, run_id, candidates, metadata):
        self.saved = True

    def save_dsa_tasks(self, run_id, refs):
        pass

    def save_final(self, run_id, candidates):
        pass


def test_orchestrator_keeps_integrations_behind_ports():
    dsa = FakeDsa()
    notify = FakeNotify()
    state = FakeState()
    orchestrator = IntradayPickerOrchestrator(
        config=IntradayPickerConfig(enabled=True),
        strategy_gateway=FakeStrategy(),
        market_gateway=FakeMarket(),
        history_repository=FakeHistory(),
        dsa_gateway=dsa,
        notification_gateway=notify,
        run_state=state,
    )
    top = orchestrator.run_preliminary(datetime(2026, 8, 17, 9, 45))
    assert len(top) == 1
    assert top[0].metrics.rvol_time == 3.0
    assert top[0].resonance_score > 0
    assert state.saved
    assert notify.preliminary
    assert dsa.submitted
