from datetime import date, datetime
from unittest.mock import patch

from src.services.screening import snapshot
from src.services.screening.config import DEFAULT_SNAPSHOT_SOURCE_PRIORITY


def test_non_trading_snapshot_context_uses_previous_completed_date() -> None:
    saturday = datetime(2026, 8, 8, 12, 0)
    with patch.object(snapshot, "get_market_now", return_value=saturday), patch.object(
        snapshot,
        "get_effective_trading_date",
        return_value=date(2026, 8, 7),
    ):
        requested, effective, non_trading = snapshot._snapshot_date_context("cn")

    assert requested == "2026-08-08"
    assert effective == "2026-08-07"
    assert non_trading is True


def test_tencent_is_in_snapshot_priority_and_parser_normalizes_quote() -> None:
    fields = [""] * 50
    fields[1] = "平安银行"
    fields[2] = "000001"
    fields[3] = "11.19"
    fields[32] = "-0.71"
    fields[35] = "11.19/100/1000000"
    fields[37] = "100"
    fields[38] = "0.46"
    fields[39] = "5.2"
    fields[44] = "1000"
    fields[45] = "1200"
    fields[46] = "0.7"
    fields[49] = "0.64"
    parsed = snapshot._parse_tencent_snapshot_response(
        'v_sz000001="' + "~".join(fields) + '";'
    )

    assert "tencent" in DEFAULT_SNAPSHOT_SOURCE_PRIORITY
    assert parsed[0]["code"] == "000001"
    assert parsed[0]["price"] == 11.19
    assert parsed[0]["change_pct"] == -0.71
    assert parsed[0]["amount"] == 1000000.0
