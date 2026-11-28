# -*- coding: utf-8 -*-
"""Tests for structured report ViewModel and channel-native renderers."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import NotificationChannel, StockAnalysisPipeline
from src.enums import ReportType
from src.formatters import utf16_len
from src.notification import NotificationService
from src.notification_noise import reset_notification_noise_state
from src.notification_sender.email_sender import EmailSender
from src.notification_sender.feishu_sender import FeishuSender
from src.notification_sender.telegram_sender import TelegramSender
from src.notification_sender.wechat_sender import WechatSender
from src.services.channel_renderers import (
    render_email_html,
    render_feishu_card_pages,
    render_standalone_html,
    render_telegram_html_chunks,
    render_wechat_digest_chunks,
)
from src.services.report_payload import (
    build_history_report_payload,
    build_notification_report_payload,
    parse_price_number,
)


def _sample_result(
    *,
    code: str = "600519",
    name: str = "贵州茅台",
    score: int = 82,
    advice: str = "买入",
    action: str = "buy",
    trend: str = "看多",
    lang: str = "zh",
    current_price: float = 1520.0,
    change_pct: float = 2.35,
    ideal_buy: str = "1500.00",
    secondary_buy: str = "1460.00",
    stop_loss: str = "1420.00",
    take_profit: str = "1680.00",
    risk_alerts=None,
    catalysts=None,
    checklist=None,
    model_used: str = "gemini/gemini-2.5-flash",
) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=name,
        sentiment_score=score,
        trend_prediction=trend,
        operation_advice=advice,
        action=action,
        report_language=lang,
        current_price=current_price,
        change_pct=change_pct,
        analysis_summary="均线多头排列，业绩稳健增长",
        model_used=model_used,
        data_sources="akshare,tavily",
        dashboard={
            "core_conclusion": {
                "one_sentence": f"{name} 站稳支撑区，具备顺势跟踪条件",
                "time_sensitivity": "本周内有效",
                "position_advice": {
                    "no_position": "分批在理想买点附近低吸，跌破止损退出",
                    "has_position": "沿 5 日线持有，关注目标位分批止盈",
                },
            },
            "intelligence": {
                "sentiment_summary": "机构关注度回升",
                "earnings_outlook": "Q3 业绩符合预期",
                "risk_alerts": list(risk_alerts) if risk_alerts is not None else [],
                "positive_catalysts": (
                    list(catalysts) if catalysts is not None else ["回购方案落地", "渠道库存改善"]
                ),
            },
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": ideal_buy,
                    "secondary_buy": secondary_buy,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
                "position_strategy": {
                    "suggested_position": "20% 仓位",
                },
                "action_checklist": (
                    list(checklist)
                    if checklist is not None
                    else ["✅ 趋势均线多头排列", "⚠️ 注意成交量持续性"]
                ),
            },
            "signal_attribution": {
                "technical_indicators": 40,
                "news_sentiment": 25,
                "fundamentals": 20,
                "market_conditions": 15,
                "strongest_bullish_signal": "放量站上 20 日均线",
                "strongest_bearish_signal": "上方前高存在抛压",
            },
        },
    )


def _mock_response(status_code: int = 200, json_body=None, text: str = ""):
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.text = text or json.dumps(json_body or {}, ensure_ascii=False)
    resp.headers = {}
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


def test_parse_price_number_skips_dates_ratios_ma_periods_and_pct():
    assert parse_price_number("MA20附近 125.40元") == 125.4
    assert parse_price_number("2026-03-21 5% 盈亏比 1:2.5") is None
    assert parse_price_number("现价 100 元，回踩 96.5 元") == 96.5
    assert parse_price_number("5-20日均线附近 $42.50") == 42.5


def test_build_notification_report_payload_sorts_alert_first_and_builds_dynamic_titles():
    buy_high = _sample_result(code="600519", name="贵州茅台", score=88, action="buy", advice="买入")
    hold_warn = _sample_result(
        code="000001",
        name="平安银行",
        score=55,
        action="hold",
        advice="持有",
        risk_alerts=["息差收窄压力"],
    )
    hold_calm = _sample_result(code="000002", name="万科A", score=58, action="hold", advice="观望")
    sell_low = _sample_result(
        code="300750",
        name="宁德时代",
        score=32,
        action="sell",
        advice="卖出",
        risk_alerts=["放量跌破年线支撑", "北向资金连续净流出"],
    )

    payload = build_notification_report_payload(
        [buy_high, hold_warn, hold_calm, sell_low],
        report_date="2026-11-22",
    )

    assert payload.header_tone == "red"
    assert payload.buy_count == 1
    assert payload.hold_count == 2
    assert payload.sell_count == 1
    assert payload.alert_count == 2
    assert "11-22" in payload.dynamic_title
    assert "买1·观2·卖1·预警2" in payload.dynamic_title
    assert [s.code for s in payload.stocks] == ["300750", "000001", "600519", "000002"]
    assert payload.stocks[0].sniper.risk_reward_ratio is None  # Suppressed on sell signal
    assert payload.stocks[2].sniper.risk_reward_ratio == 2.25

    single_en = build_notification_report_payload(
        [_sample_result(code="AAPL", name="Apple", score=80, action="buy", lang="en", risk_alerts=["Minor valuation note"])],
        report_date="2026-11-22",
        single_stock=True,
    )
    assert single_en.dynamic_title.startswith("DSA Brief (11-22) | Apple(AAPL)")
    assert "Alert" not in single_en.dynamic_title

    single_en_urgent = build_notification_report_payload(
        [_sample_result(code="AAPL", name="Apple", score=54, action="hold", advice="观望", lang="en", risk_alerts=["Guidance risk"])],
        report_date="2026-11-22",
        single_stock=True,
    )
    assert "1 Alert(s)" in single_en_urgent.dynamic_title

    single_ko = build_notification_report_payload(
        [_sample_result(code="005930.KS", name="Samsung", score=74, lang="ko", risk_alerts=[])],
        report_date="2026-11-22",
        single_stock=True,
    )
    assert "DSA 브리핑 (11-22)" in single_ko.dynamic_title
    assert "74점" in single_ko.dynamic_title


def test_build_payload_handles_stub_objects_and_history_records():
    stub_payload = build_notification_report_payload([SimpleNamespace(code="000001")], report_date="2026-11-22")
    assert stub_payload.total_count == 1
    assert stub_payload.stocks[0].code == "000001"

    hist_payload = build_history_report_payload(
        {
            "id": 99,
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "report_language": "zh",
            "created_at": "2026-11-22T09:30:00",
            "sentiment_score": 78,
            "operation_advice": "买入",
            "action": "buy",
            "ideal_buy": "1500",
            "stop_loss": "1420",
            "take_profit": "1680",
            "context_snapshot": {"realtime_quote": {"price": 1525.0, "pct_chg": 1.8}},
            "raw_result": {"dashboard": {"intelligence": {"risk_alerts": ["估值波动风险"]}}},
        }
    )
    assert hist_payload.single_stock is True
    assert hist_payload.stocks[0].current_price == 1525.0
    assert hist_payload.stocks[0].risk_alerts == ["估值波动风险"]


def test_render_email_and_standalone_html_escape_xss_and_render_alert_first():
    risky = _sample_result(
        code="300750",
        name="<script>alert(1)</script>宁德时代",
        score=34,
        action="sell",
        advice="卖出",
        risk_alerts=["<img src=x onerror=alert(2)>跌破关键均线"],
    )
    payload = build_notification_report_payload(
        [risky],
        report_date="2026-11-22",
        single_stock=True,
        web_url="https://dsa.example.com/report/1",
    )

    email_html = render_email_html(payload)
    assert "<script>" not in email_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in email_html
    assert "&lt;img src=x onerror=alert(2)&gt;" in email_html
    assert 'role="presentation"' in email_html
    assert "position:" not in email_html
    assert "<!--[if mso]>" in email_html
    assert "Alert-First" in email_html
    assert "打开 Web 控制台" in email_html
    assert "```" not in email_html
    # Single-stock urgent alert should appear in the top Alert-First panel without repeating in the card body.
    assert email_html.count("跌破关键均线") == 1

    standalone_html = render_standalone_html(payload)
    assert "<script>" not in standalone_html
    assert "@media print" in standalone_html
    assert "--bg: #ffffff;" in standalone_html
    assert "Content-Security-Policy" in standalone_html
    assert "多空归因" in standalone_html or "信号归因" in standalone_html

    clear_payload = build_notification_report_payload(
        [_sample_result(risk_alerts=[])],
        report_date="2026-11-22",
        single_stock=True,
    )
    clear_email = render_email_html(clear_payload)
    assert "本期未触发高危风险警报" in clear_email

    no_intel_payload = build_notification_report_payload([SimpleNamespace(code="600519")], report_date="2026-11-22")
    assert no_intel_payload.risk_checked_count == 0
    assert no_intel_payload.stocks[0].sentiment_score is None
    assert no_intel_payload.stocks[0].score_display == "—"
    assert "本期未触发高危风险警报" not in render_email_html(no_intel_payload)
    assert "本期未触发高危风险警报" not in render_standalone_html(no_intel_payload)


def test_feishu_structured_card_pages_webhook_and_app_bot():
    results = [
        _sample_result(code=f"6000{i:02d}", name=f"样本股{i}", score=40 + i * 5, risk_alerts=[f"风险{i}"])
        for i in range(6)
    ]
    payload = build_notification_report_payload(
        results,
        report_date="2026-11-22",
        web_url="https://dsa.example.com",
    )

    pages = render_feishu_card_pages(
        payload,
        keyword="[DSA]",
        max_bytes=2200,
        request_limit=2200,
    )
    assert len(pages) >= 2
    for plain, card in pages:
        assert "[DSA]" in plain
        assert len(json.dumps(card, ensure_ascii=False).encode("utf-8")) <= 2200
        assert card["header"]["template"] == payload.header_tone
        assert any(el.get("tag") == "div" and "fields" in el for el in card["elements"]) or card["elements"]
        first_text = card["elements"][0]["text"]["content"]
        assert first_text == "[DSA]"

    cfg = SimpleNamespace(
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        feishu_webhook_secret="",
        feishu_webhook_keyword="[DSA]",
        feishu_max_bytes=20000,
        feishu_send_as_file=False,
        feishu_app_id=None,
        feishu_app_secret=None,
        feishu_chat_id=None,
        webhook_verify_ssl=True,
    )
    sender = FeishuSender(cfg)
    with mock.patch("requests.post", return_value=_mock_response(200, {"code": 0})) as mock_post:
        ok = sender.send_to_feishu("fallback md", report_payload=payload)
    assert ok is True
    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["msg_type"] == "interactive"
    assert sent_json["card"]["header"]["template"] in {"red", "orange", "green", "blue"}

    # Legacy Markdown call remains untouched when report_payload=None
    with mock.patch("requests.post", return_value=_mock_response(200, {"code": 0})) as mock_post_legacy:
        ok_legacy = sender.send_to_feishu("# 标题\n\n**买入** 测试")
    assert ok_legacy is True
    assert mock_post_legacy.call_args.kwargs["json"]["msg_type"] == "interactive"


def test_telegram_native_html_chunks_budget_and_plain_fallback():
    results = [
        _sample_result(
            code=f"000{i:03d}",
            name=f"测试标的<{i}>",
            score=75 - i * 3,
            risk_alerts=[f"注意 <tag> 风险 {i}"],
        )
        for i in range(10)
    ]
    payload = build_notification_report_payload(results, report_date="2026-11-22", web_url="https://dsa.example.com")
    chunks = render_telegram_html_chunks(payload, max_utf16_units=1200)
    assert len(chunks) >= 2
    for html_chunk, plain_chunk in chunks:
        assert utf16_len(html_chunk) <= 1200
        assert "<blockquote" in html_chunk
        assert "&lt;tag&gt;" in html_chunk
        assert "<blockquote>" not in plain_chunk

    cfg = SimpleNamespace(
        telegram_bot_token="bot-token",
        telegram_chat_id="123456",
        telegram_message_thread_id=None,
    )
    sender = TelegramSender(cfg)
    with mock.patch(
        "requests.post",
        side_effect=[
            _mock_response(200, {"ok": False, "description": "Bad Request: unsupported start tag"}),
            _mock_response(200, {"ok": True}),
        ],
    ) as mock_post:
        ok = sender.send_to_telegram("fallback", report_payload=build_notification_report_payload([results[0]], single_stock=True))

    assert ok is True
    assert mock_post.call_count == 2
    first_payload = mock_post.call_args_list[0].kwargs["json"]
    second_payload = mock_post.call_args_list[1].kwargs["json"]
    assert first_payload["parse_mode"] == "HTML"
    assert "parse_mode" not in second_payload
    assert "<blockquote>" not in second_payload["text"]


def test_wechat_digest_chunks_font_colors_text_mode_and_bytes_budget():
    results = [_sample_result(code=f"601{i:03d}", name=f"企业股{i}", risk_alerts=[f"风险警报{i}"]) for i in range(14)]
    payload = build_notification_report_payload(results, report_date="2026-11-22")

    md_chunks = render_wechat_digest_chunks(payload, msg_type="markdown", max_bytes=3950)
    assert len(md_chunks) >= 2
    assert any('<font color="' in c for c in md_chunks)
    for chunk in md_chunks:
        assert len(chunk.encode("utf-8")) <= 3950

    txt_chunks = render_wechat_digest_chunks(payload, msg_type="text", max_bytes=1950)
    assert len(txt_chunks) >= 2
    for chunk in txt_chunks:
        assert len(chunk.encode("utf-8")) <= 1950
        assert "<font" not in chunk

    cfg = SimpleNamespace(
        wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        wechat_max_bytes=4000,
        wechat_msg_type="markdown",
        webhook_verify_ssl=True,
    )
    sender = WechatSender(cfg)
    with mock.patch("requests.post", return_value=_mock_response(200, {"errcode": 0})) as mock_post:
        ok = sender.send_to_wechat("fallback", report_payload=build_notification_report_payload([results[0]], single_stock=True))
    assert ok is True
    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["msgtype"] == "markdown"
    assert '<font color="' in sent_json["markdown"]["content"]


def test_email_sender_uses_structured_html_and_dynamic_subject():
    payload = build_notification_report_payload(
        [_sample_result(code="600519", name="贵州茅台", score=86)],
        report_date="2026-11-22",
        single_stock=True,
    )
    cfg = SimpleNamespace(
        email_sender="bot@qq.com",
        email_sender_name="DSA",
        email_password="secret",
        email_receivers=["user@example.com"],
        stock_email_groups=[],
    )
    sender = EmailSender(cfg)
    sent_msgs = []
    smtp_inst = mock.MagicMock()
    smtp_inst.send_message.side_effect = lambda msg: sent_msgs.append(msg)

    with mock.patch("smtplib.SMTP_SSL", return_value=smtp_inst):
        ok = sender.send_to_email("legacy md", report_payload=payload)

    assert ok is True
    assert len(sent_msgs) == 1
    msg = sent_msgs[0]
    parts = msg.get_payload()
    html_body = parts[1].get_payload(decode=True).decode("utf-8")
    assert 'role="presentation"' in html_body
    assert "贵州茅台" in html_body


def test_notification_service_and_pipeline_forward_report_payload_safely():
    reset_notification_noise_state()
    result = _sample_result()
    cfg = SimpleNamespace(
        wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        wechat_max_bytes=4000,
        wechat_msg_type="markdown",
        dingtalk_webhook_url=None,
        dingtalk_secret=None,
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        feishu_webhook_secret="",
        feishu_webhook_keyword="",
        feishu_max_bytes=20000,
        feishu_send_as_file=False,
        feishu_app_id=None,
        feishu_app_secret=None,
        feishu_chat_id=None,
        telegram_bot_token="tok",
        telegram_chat_id="123",
        telegram_message_thread_id=None,
        email_sender="bot@qq.com",
        email_password="pw",
        email_receivers=["u@example.com"],
        stock_email_groups=[],
        pushover_user_key=None,
        pushover_api_token=None,
        ntfy_url=None,
        ntfy_token=None,
        gotify_url=None,
        gotify_token=None,
        pushplus_token=None,
        serverchan3_sendkey=None,
        custom_webhook_urls=[],
        custom_webhook_bearer_token=None,
        custom_webhook_body_template=None,
        webhook_verify_ssl=True,
        discord_webhook_url=None,
        discord_bot_token=None,
        discord_main_channel_id=None,
        slack_webhook_url=None,
        slack_bot_token=None,
        slack_channel_id=None,
        astrbot_url=None,
        astrbot_token=None,
        markdown_to_image_channels=[],
        markdown_to_image_max_chars=15000,
        report_summary_only=False,
        report_show_llm_model=True,
        report_language="zh",
        notification_dedup_ttl_seconds=0,
        notification_cooldown_seconds=0,
        notification_quiet_hours=None,
        notification_timezone=None,
        notification_min_severity=None,
    )
    with mock.patch("src.notification.get_config", return_value=cfg):
        notifier = NotificationService()
        payload = notifier.build_report_payload([result], single_stock=True)

        with mock.patch.object(notifier, "send_to_wechat", autospec=True, return_value=True) as m_wc, \
             mock.patch.object(notifier, "send_to_feishu", autospec=True, return_value=True) as m_fs, \
             mock.patch.object(notifier, "send_to_telegram", autospec=True, return_value=True) as m_tg, \
             mock.patch.object(notifier, "send_to_email", autospec=True, return_value=True) as m_em:
            ok = notifier.send("md", report_payload=payload)

    assert ok is True
    assert m_wc.call_args.kwargs["report_payload"] is payload
    assert m_fs.call_args.kwargs["report_payload"] is payload
    assert m_tg.call_args.kwargs["report_payload"] is payload
    assert m_em.call_args.kwargs["report_payload"] is payload

    # Verify pipeline._send_notifications passes batch payload to real methods without breaking mocks
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notifier = notifier
    pipeline.config = SimpleNamespace(stock_email_groups=[])
    with mock.patch.object(notifier, "send_to_wechat", autospec=True, return_value=True) as pm_wc, \
         mock.patch.object(notifier, "send_to_feishu", autospec=True, return_value=True) as pm_fs, \
         mock.patch.object(notifier, "send_to_telegram", autospec=True, return_value=True) as pm_tg, \
         mock.patch.object(notifier, "send_to_email", autospec=True, return_value=True) as pm_em, \
         mock.patch("src.core.pipeline.record_notification_run"), \
         mock.patch.object(pipeline, "_refresh_saved_diagnostic_snapshot"):
        pipeline._send_notifications([result], ReportType.SIMPLE)

    assert pm_wc.call_args.kwargs["report_payload"].total_count == 1
    assert pm_fs.call_args.kwargs["report_payload"].total_count == 1
    assert pm_tg.call_args.kwargs["report_payload"].total_count == 1
    assert pm_em.call_args.kwargs["report_payload"].total_count == 1


def test_review_round2_hardening_contracts(monkeypatch):
    # A1: WEBUI_URL ignored; DSA_WEB_URL honored cleanly by NotificationService
    monkeypatch.setenv("WEBUI_URL", "https://legacy-ignored.example.com")
    monkeypatch.setenv("DSA_WEB_URL", "https://dsa.example.com/workspace")
    direct_payload = build_notification_report_payload([_sample_result()], report_date="2026-11-22")
    assert direct_payload.web_url == ""

    with mock.patch("src.notification.get_config", return_value=SimpleNamespace(report_language="zh")):
        svc = NotificationService.__new__(NotificationService)
        svc._config = SimpleNamespace(report_language="zh", report_show_llm_model=True)
        svc._report_summary_only = False
        svc._report_show_llm_model = True
        built = svc.build_report_payload([_sample_result()], single_stock=True)
        assert built.web_url == "https://dsa.example.com/workspace"

    # A2: summary_only propagates across all 3 IM renderers cleanly
    compact = build_notification_report_payload(
        [_sample_result(code="600519", name="贵州茅台"), _sample_result(code="000001", name="平安银行")],
        report_date="2026-11-22",
        summary_only=True,
    )
    _, compact_card = render_feishu_card_pages(compact)[0]
    assert not any(el.get("tag") == "div" and len(el.get("fields", [])) == 4 and "**理想买点**" in str(el) for el in compact_card["elements"])
    tg_compact_html, _ = render_telegram_html_chunks(compact)[0]
    assert "<blockquote expandable>" not in tg_compact_html
    assert "理想买点" not in tg_compact_html
    wc_compact = render_wechat_digest_chunks(compact)[0]
    assert "空仓应对" not in wc_compact

    # A3 / A4 / A5 / A6 / A7 / B3 / B4 / C1 / D4
    buy_with_minor_note = _sample_result(
        code="600519",
        name="贵州茅台",
        score=82,
        action="buy",
        advice="买入",
        current_price=1380.0,
        ideal_buy="1500.00",
        stop_loss="1420.00",
        take_profit="1680.00",
        risk_alerts=["估值处于历史中枢"],
        checklist=["✅ 无需注意追高风险", "❌ 量能不足"],
    )
    alert_item = _sample_result(
        code="000858",
        name="<at id=all></at>*五粮液*",
        score=54,
        action="alert",
        advice="风险预警",
        risk_alerts=["<at id=all>退市</at>风险提示 1", "风险提示 2", "风险提示 3"],
    )
    mixed = build_notification_report_payload(
        [buy_with_minor_note, alert_item],
        report_date="2026-11-22",
        report_language="en",
    )
    # Only alert_item counts toward urgent alerts; healthy buy's minor note does not inflate banner or alert_count
    assert mixed.alert_count == 1
    assert all(e.stock_code == "000858" for e in mixed.top_risk_alerts)
    assert len(mixed.top_risk_alerts) == 2
    buy_vm = next(s for s in mixed.stocks if s.code == "600519")
    assert buy_vm.sniper.price_zone == "below_stop"
    assert buy_vm.failed_checks == ["❌ 量能不足"]

    # En report uses green for positive change and shows (at entry) + Below Stop
    buy_vm.change_pct = 2.5
    buy_vm.change_display = "+2.50%"
    en_email = render_email_html(mixed)
    assert "at entry" in en_email
    assert "Below Stop" in en_email
    assert "#059669" in en_email

    # Standalone batch includes SVG score distribution & price SVG ruler
    standalone_batch = render_standalone_html(mixed)
    assert '<svg class="dist-svg"' in standalone_batch
    assert '<svg class="ruler-svg"' in standalone_batch
    assert "Below Stop" in standalone_batch

    # C1: Feishu lark_md neutralizes <at> injection in stock name and risk alerts while keeping keyword
    _, sec_card = render_feishu_card_pages(mixed, keyword="[DSA]")[0]
    card_json_str = json.dumps(sec_card, ensure_ascii=False)
    assert "[DSA]" in card_json_str
    assert "<at" not in card_json_str

    # A8: Feishu omits/renames R:R field when risk_reward_ratio is None
    no_rr = build_notification_report_payload(
        [_sample_result(ideal_buy="", stop_loss="", take_profit="", trend="看多")],
        report_date="2026-11-22",
        single_stock=True,
    )
    _, no_rr_card = render_feishu_card_pages(no_rr)[0]
    assert "盈亏比" not in json.dumps(no_rr_card, ensure_ascii=False)

    # C2: WeChat send failure on chunk 2 does NOT fallback to re-sending legacy Markdown
    wc_cfg = SimpleNamespace(
        wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        wechat_max_bytes=4000,
        wechat_msg_type="markdown",
        webhook_verify_ssl=True,
    )
    wc_sender = WechatSender(wc_cfg)
    many_stocks = build_notification_report_payload(
        [_sample_result(code=f"602{i:03d}", name=f"企业{i}") for i in range(16)],
        report_date="2026-11-22",
    )
    with mock.patch.object(wc_sender, "_send_wechat_message", side_effect=[True, False, False, False]) as m_send:
        ok_wc = wc_sender.send_to_wechat("LEGACY_MD_SHOULD_NOT_SEND", report_payload=many_stocks)
    assert ok_wc is False
    assert all("LEGACY_MD_SHOULD_NOT_SEND" not in call.args[0] for call in m_send.call_args_list)

    # C3 & C4: Telegram render error falls back to Markdown; send failure does NOT double-send; disclaimer always preserved
    tg_cfg = SimpleNamespace(telegram_bot_token="tok", telegram_chat_id="123", telegram_message_thread_id=None)
    tg_sender = TelegramSender(tg_cfg)
    with mock.patch("src.notification_sender.telegram_sender.render_telegram_html_chunks", side_effect=RuntimeError("boom")):
        with mock.patch.object(tg_sender, "_send_telegram_message", return_value=True) as m_tg_send:
            assert tg_sender.send_to_telegram("FALLBACK_MD", report_payload=direct_payload) is True
            assert m_tg_send.call_args.args[2] == "FALLBACK_MD"

    small_tg_chunks = render_telegram_html_chunks(
        build_notification_report_payload([_sample_result(code=f"000{i:03d}") for i in range(4)]),
        max_utf16_units=600,
    )
    assert any("投资" in plain or "investment advice" in plain.lower() for _, plain in small_tg_chunks)

    # C6: WeChat balanced <font> tags across chunk pagination
    for wc_chunk in render_wechat_digest_chunks(many_stocks, msg_type="markdown", max_bytes=900):
        assert wc_chunk.count("<font") == wc_chunk.count("</font>")
        assert len(wc_chunk.encode("utf-8")) <= 900


def test_loopback_and_unspecified_web_urls_are_suppressed(monkeypatch):
    from src.services.channel_renderers import (
        is_public_web_url,
        render_email_html,
        render_feishu_card_pages,
        render_telegram_html_chunks,
    )

    assert is_public_web_url("https://dsa.example.com/workspace") is True
    for bad_url in (
        "http://localhost:8000",
        "http://sub.localhost:8000/chat",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "http://0.0.0.0:8000",
        "javascript:alert(1)",
    ):
        assert is_public_web_url(bad_url) is False
        assert FeishuSender._is_web_url(bad_url) is False

        payload = build_notification_report_payload([_sample_result()], report_date="2026-11-22")
        payload.web_url = bad_url
        assert bad_url not in render_email_html(payload)
        _, card = render_feishu_card_pages(payload)[0]
        assert not any(el.get("tag") == "action" for el in card["elements"])
        tg_html, tg_plain = render_telegram_html_chunks(payload)[0]
        assert bad_url not in tg_html
        assert bad_url not in tg_plain

    monkeypatch.setenv("FEISHU_CARD_WEB_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("DSA_WEB_URL", "http://localhost:8000")
    sender = FeishuSender(
        SimpleNamespace(
            feishu_webhook_url="https://feishu.example/hook",
            feishu_max_bytes=20000,
            webhook_verify_ssl=True,
        )
    )
    assert sender._web_url == ""


def test_structured_strategy_synthesis_renders_in_email_and_standalone_html_with_xss_escape():
    res = _sample_result(code="600519", name="贵州茅台", score=80)
    res.dashboard["strategy_synthesis"] = {
        "final_signal": "buy",
        "consensus_level": "medium",
        "conflict_severity": "medium",
        "conflict_count": 1,
        "confidence": 0.78,
        "supporting_skills": [
            {"skill_id": "bull_trend", "signal": "buy", "confidence": 0.85},
            {"skill_id": "<script>alert(1)</script>", "signal": "strong_buy", "confidence": 0.8},
        ],
        "opposing_skills": [
            {"skill_id": "shrink_pullback", "signal": "sell", "confidence": 0.76},
        ],
        "summary_params": {
            "opinion_count": 3,
            "invalid_opinion_count": 1,
        },
        "deliberation": {
            "summary": {"minority_view_preserved": True},
        },
    }

    payload = build_notification_report_payload([res], report_date="2026-11-23", single_stock=True)
    stock = payload.stocks[0]
    assert stock.strategy_synthesis is not None
    assert stock.strategy_synthesis.final_signal_display == "买入"
    assert stock.strategy_synthesis.consensus_display == "中"
    assert stock.strategy_synthesis.conflict_display == "中"
    assert stock.strategy_synthesis.conflict_count == 1
    assert stock.strategy_synthesis.confidence_pct == 78
    assert stock.strategy_synthesis.invalid_opinion_count == 1
    assert stock.strategy_synthesis.minority_view_preserved is True
    assert stock.strategy_synthesis.supporting_skills[0].display_name == "默认多头趋势"
    assert stock.strategy_synthesis.opposing_skills[0].display_name == "缩量回踩"

    email_html = render_email_html(payload)
    standalone_html = render_standalone_html(payload)
    for html_doc in (email_html, standalone_html):
        assert "多策略综合" in html_doc
        assert "综合信号: 买入" in html_doc
        assert "共识度: 中" in html_doc
        assert "冲突: 中 (1)" in html_doc
        assert "置信度: 78%" in html_doc
        assert "默认多头趋势 · 买入 · 85%" in html_doc
        assert "缩量回踩 · 卖出 · 76%" in html_doc
        assert "已保留高置信度少数派异议" in html_doc
        assert "另有 1 个策略未能产出有效信号" in html_doc
        assert "<script>" not in html_doc
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc

    # English rendering + malformed payload guard
    en_res = _sample_result(code="AAPL", name="Apple", score=74, lang="en")
    en_res.dashboard["strategy_synthesis"] = {
        "final_signal": "hold",
        "consensus_level": "high",
        "conflict_severity": "none",
        "conflict_count": 0,
        "confidence": 0.9,
        "supporting_skills": [{"skill_id": "chan_theory", "signal": "hold", "confidence": 0.9}],
        "opposing_skills": [],
    }
    en_payload = build_notification_report_payload([en_res], report_date="2026-11-23", single_stock=True)
    assert "Strategy Synthesis" in render_email_html(en_payload)
    assert "Chan Theory" in render_standalone_html(en_payload)

    bad_res = _sample_result(code="000001", name="平安银行", score=60)
    bad_res.dashboard["strategy_synthesis"] = {
        "final_signal": None,
        "supporting_skills": ["not-a-dict"],
        "deliberation": "bad",
    }
    bad_payload = build_notification_report_payload([bad_res], report_date="2026-11-23", single_stock=True)
    assert bad_payload.stocks[0].strategy_synthesis is None


def test_review_hardening_feishu_limits_and_telegram_empty_stock_utf16_budget():
    import pytest

    res = _sample_result(code="600519", name="贵州茅台", score=82)
    payload = build_notification_report_payload([res], report_date="2026-11-23", single_stock=True)

    # Tight plain-text max_bytes with generous request_limit must NOT drop structured card elements.
    plain_tight, card_tight = render_feishu_card_pages(
        payload,
        max_bytes=200,
        request_limit=20000,
    )[0]
    assert len(plain_tight.encode("utf-8")) <= 200
    assert any(el.get("tag") == "div" and "fields" in el for el in card_tight["elements"])

    # Impossibly small request_limit raises ValueError so FeishuSender falls back cleanly.
    with pytest.raises(ValueError, match="request_limit"):
        render_feishu_card_pages(payload, max_bytes=20000, request_limit=50)

    # Empty stocks with tight Telegram UTF-16 budget still returns well-formed escaped text within budget.
    empty_payload = build_notification_report_payload(
        [],
        report_date="2026-11-23",
        market_status_line="A股收盘休市 <test>",
    )
    tg_chunks = render_telegram_html_chunks(empty_payload, max_utf16_units=60)
    assert len(tg_chunks) == 1
    tg_html, tg_plain = tg_chunks[0]
    assert utf16_len(tg_html) <= 60
    assert "<b>" not in tg_html and "<blockquote" not in tg_html
    assert len(tg_plain) > 0
