"""Taiwan recap contracts from provider results through history and share images."""

import json
import re
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.config import Config
from src.core.market_review import run_market_review
from src.core.trading_calendar import compute_effective_region
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview
from src.services.daily_market_context import (
    DailyMarketContextService,
    format_daily_market_context_prompt_section,
)
from src.share_image import build_share_image_html
from src.storage import AnalysisHistory, DatabaseManager


def _index(code="TWII"):
    return MarketIndex(
        code=code, name="TAIEX" if code == "TWII" else "TPEx",
        current=22000, change=100, change_pct=0.46, prev_close=21900,
    )


def _llm_report(language="en", title="Taiwan Market Recap"):
    summary, indices, news, plan, risks = (
        ("一、盘面总览", "二、指数结构", "五、消息催化", "六、明日交易计划", "七、风险提示")
        if language == "zh" else
        ("Market Summary", "Major Indices", "News Catalysts", "Strategy Plan", "Risk Alerts")
    )
    limits = {"zh": "数据边界", "en": "Data Limits", "ko": "데이터 한계"}[language]
    return f"""## {title}

### {summary}
> Available evidence supports a cautious outlook.
### {indices}
Available index data is listed below.
### {news}
- Semiconductor demand is in focus.
### {plan}
- Wait for confirmation.
### {risks}
- External volatility remains.
### {limits}
- Market breadth is unavailable.
- Sector rankings are unavailable.
- Turnover is unavailable.
- Market breadth is unavailable.
"""


@pytest.fixture
def isolated_db(tmp_path):
    config = Config(database_path=str(tmp_path / "recap.db"), market_review_region="tw")
    DatabaseManager.reset_instance()
    try:
        with patch("src.storage.get_config", return_value=config):
            yield DatabaseManager.get_instance(), config
    finally:
        DatabaseManager.reset_instance()


@pytest.mark.parametrize("language", ["zh", "en", "ko"])
def test_tw_prompt_uses_taiwan_context_and_discloses_partial_coverage(language):
    with patch("src.market_analyzer.DataFetcherManager"):
        analyzer = MarketAnalyzer(region="tw", config=Config(report_language=language))
    prompt = analyzer._build_review_prompt(MarketOverview(date="2026-11-10", indices=[_index()]), [])

    assert analyzer.profile.region == analyzer.strategy.region == "tw"
    assert not analyzer.profile.has_market_stats
    assert not analyzer.profile.has_sector_rankings
    assert "TWOII:" in prompt
    assert "TWII:" not in prompt
    assert "台股" in prompt if language == "zh" else "Taiwan market" in prompt
    assert "北向资金" not in prompt
    assert "两市成交额" not in prompt
    if language == "ko":
        assert "Korean (한국어)" in prompt
    assert analyzer._format_turnover_value(0) == "N/A"
    assert analyzer._format_turnover_value(2_500_000_000) == "2.50"
    assert analyzer._get_turnover_unit_label() == ("十亿新台币" if language == "zh" else "TWD bn")


@pytest.mark.parametrize("language", ["zh", "en", "ko"])
@pytest.mark.parametrize("codes", [[], ["TWII"], ["TWOII"], ["TWII", "TWOII"]])
def test_tw_missing_indices_remain_visible_in_report_payload_and_poster(language, codes):
    with patch("src.market_analyzer.DataFetcherManager"):
        analyzer = MarketAnalyzer(region="tw", config=Config(report_language=language))
    overview = MarketOverview(date="2026-11-10", indices=[_index(code) for code in codes])
    report = analyzer.generate_market_review(overview, [])
    payload = analyzer.build_market_review_payload(overview, [], report)
    html = build_share_image_html(report, structured_payload=payload, generated_on=date(2026, 11, 10))

    assert payload["region"] == "tw"
    assert payload["language"] == language
    assert "market_light" not in payload
    assert "breadth" not in payload
    assert payload["sectors"] == {"top": [], "bottom": []}
    assert payload["markdown_report"] == report
    for code in ("TWII", "TWOII"):
        if code not in codes:
            assert f"{code}:" in report
            assert f"{code}:" in html
    if "TWII" not in codes:
        assert "指数数据不足" in report if language == "zh" else "insufficient index data" in report
    assert "A-share Market Recap" not in report


@pytest.mark.parametrize("language", ["zh", "en", "ko"])
@pytest.mark.parametrize("codes", [[], ["TWII"], ["TWOII"], ["TWII", "TWOII"]])
@pytest.mark.parametrize("merged_limits", [False, True])
def test_tw_llm_report_cannot_omit_missing_index_notice(language, codes, merged_limits):
    llm = MagicMock(generate_text=MagicMock(return_value=_llm_report(language)))
    with patch("src.market_analyzer.DataFetcherManager"):
        analyzer = MarketAnalyzer(region="tw", config=Config(report_language=language), analyzer=llm)
    overview = MarketOverview(date="2026-11-10", indices=[_index(code) for code in codes])
    report = analyzer.generate_market_review(overview, [])
    # Historical reports can have either duplicate headings or one longer list.
    limits = {"zh": "数据边界", "en": "Data Limits", "ko": "데이터 한계"}[language]
    if merged_limits and len(codes) < 2:
        head, _, tail = report.rpartition(f"### {limits}\n")
        report = head + tail
    payload = analyzer.build_market_review_payload(overview, [], report)
    suffix = {"zh": "行情缺失", "en": "data unavailable", "ko": "데이터 없음"}[language]
    for structured_payload in (None, payload):
        html = build_share_image_html(report, structured_payload=structured_payload)
        risk_strip = re.search(r'<section class="poster-section risk-strip">(.*?)</section>', html, re.S).group(1)
        for code in ("TWII", "TWOII"):
            notice = f"{code}: {suffix}"
            assert (notice in report) == (code not in codes)
            assert (notice in risk_strip) == (code not in codes)
        assert "Turnover is unavailable." in risk_strip
        assert risk_strip.count("Market breadth is unavailable.") == 1
        assert "External volatility remains." in risk_strip
        if codes:
            assert '<section class="report-fallback">' not in html


@pytest.mark.parametrize("provider_error", [False, True])
def test_tw_overview_uses_taipei_date_and_never_fetches_cn_stats(provider_error):
    with patch("src.market_analyzer.DataFetcherManager") as manager, patch(
        "src.market_analyzer.get_market_now",
        return_value=datetime(2026, 11, 10, 0, 30, tzinfo=ZoneInfo("Asia/Taipei")),
    ) as market_now:
        if provider_error:
            manager.return_value.get_main_indices.side_effect = RuntimeError("source unavailable")
        else:
            manager.return_value.get_main_indices.return_value = [{**_index().to_dict(), "prev_close": 21900}]
        overview = MarketAnalyzer(region="tw", config=Config()).get_market_overview()
    market_now.assert_called_once_with("tw")
    assert overview.date == "2026-11-10"
    manager.return_value.get_main_indices.assert_called_once_with(region="tw")
    assert [call[0] for call in manager.return_value.method_calls] == ["get_main_indices"]
    assert len(overview.indices) == (0 if provider_error else 1)


@pytest.mark.parametrize(
    "configured,open_markets,expected",
    [
        ("tw", {"tw"}, "tw"),
        ("tw", {"cn"}, ""),
        ("cn,tw", {"tw"}, "tw"),
        ("both", {"tw"}, "tw"),
        ("both", {"cn", "hk", "us", "jp", "kr", "tw"}, "cn,hk,us,jp,kr,tw"),
        ("cn,hk,us,jp,kr", {"tw"}, ""),
    ],
)
def test_tw_trading_day_filter(configured, open_markets, expected):
    assert compute_effective_region(configured, open_markets) == expected


def test_tw_can_run_during_cn_national_day_holiday():
    from src.core.trading_calendar import is_market_open

    day = date(2026, 10, 1)
    assert not is_market_open("cn", day)
    assert is_market_open("tw", day)
    open_markets = {market for market in ("cn", "tw") if is_market_open(market, day)}
    assert compute_effective_region("cn,tw", open_markets) == "tw"


def test_tw_daily_context_target_date_uses_taiwan_market():
    from main import _resolve_daily_market_context_target_date

    now = datetime(2026, 11, 9, 23, tzinfo=timezone.utc)
    with patch("src.core.trading_calendar.get_effective_trading_date", return_value=date(2026, 11, 9)) as resolve:
        assert _resolve_daily_market_context_target_date("tw", now) == date(2026, 11, 9)
    resolve.assert_called_once_with("tw", current_time=now)


@pytest.mark.parametrize("regions", ["tw", "jp,tw"])
@pytest.mark.parametrize("use_llm", [False, True])
def test_tw_recap_round_trip_through_history_context_and_notification(isolated_db, regions, use_llm):
    db, config = isolated_db
    notifier = MagicMock()
    notifier.is_available.return_value = notifier.send.return_value = True
    llm = MagicMock(generate_text=MagicMock()) if use_llm else None
    if llm:
        llm.generate_text.side_effect = [
            _llm_report("zh", "台股大盘复盘" if region == "tw" else "日股大盘复盘")
            for region in regions.split(",")
        ]
    with patch("src.market_analyzer.DataFetcherManager") as manager:
        manager.return_value.get_main_indices.side_effect = lambda region: [
            {**(_index() if region == "tw" else MarketIndex(code="N225", name="Nikkei 225", current=39000)).to_dict(),
             "prev_close": 21900 if region == "tw" else 39000}
        ]
        result = run_market_review(
            notifier, analyzer=llm, config=config, override_region=regions, query_id="tw-round-trip",
            return_structured=True, save_report_file=False,
        )

    assert result is not None
    assert result.market_review_payload["region"] == regions
    assert "台股大盘复盘" in result.report
    assert "TWOII: 行情缺失" in result.report
    notifier.send.assert_called_once()
    assert "TWOII: 行情缺失" in notifier.send.call_args.args[0]
    with db.get_session() as session:
        row = session.query(AnalysisHistory).filter_by(query_id="tw-round-trip").one()
        snapshot = json.loads(row.context_snapshot)
        assert snapshot["market_review_region"] == regions
        assert snapshot["market_review_payload"] == result.market_review_payload

    for payload in (None, snapshot["market_review_payload"]):
        html = build_share_image_html(result.report, structured_payload=payload)
        risk_strips = re.findall(r'<section class="poster-section risk-strip">(.*?)</section>', html, re.S)
        assert "台股" in html
        assert "TWOII: 行情缺失" in risk_strips[-1]
        assert all("TWOII: 行情缺失" not in strip for strip in risk_strips[:-1])
        if use_llm:
            assert '<section class="report-fallback">' not in html
    if regions == "tw":
        assert "[dsa-market-region]: # (tw)" in notifier.send.call_args.args[0]
        service = DailyMarketContextService(
            db_manager=db, today_fn=lambda: date.fromisoformat(result.market_review_payload["date"]),
        )
        context = service.get_context(
            region="tw", config=config, notifier=notifier, allow_generate=False,
        )
        assert context is not None
        assert context.region == "tw"
        assert "台股（tw）" in format_daily_market_context_prompt_section(context.to_safe_dict(), report_language="zh")
        assert "Taiwan (tw)" in format_daily_market_context_prompt_section(context.to_safe_dict(), report_language="en")
        assert service.get_context(region="cn", config=config, notifier=notifier, allow_generate=False) is None


@pytest.mark.parametrize("heading", ["台股大盘复盘", "Taiwan Market Recap", "대만 시황 리뷰"])
def test_tw_markdown_only_share_image_recognizes_market_heading(heading):
    html = build_share_image_html(f"# {heading}\n\n### Data Limits\n- TWOII: data unavailable")
    assert ("台股市场复盘" if heading == "台股大盘复盘" else heading) in html
    assert 'class="poster market' in html
    assert "TWOII: data unavailable" in html
