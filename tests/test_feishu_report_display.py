from datetime import date, datetime, timezone
from copy import deepcopy

from src.schemas.macro import MacroObservation, USMacroAIExplanation, USMacroSnapshot
from src.services.feishu_report_display import (
    MACRO_DISCLAIMER,
    STOCK_DISCLAIMER,
    build_stock_feishu_message,
    build_us_macro_feishu_messages,
)


def _macro_snapshot():
    values = {
        "policy_rate_lower": (3.5, "Percent"),
        "policy_rate_upper": (3.75, "Percent"),
        "effective_fed_funds_rate": (3.63, "Percent"),
        "sofr": (3.62, "Percent"),
        "treasury_2y": (4.16, "Percent"),
        "treasury_10y": (4.57, "Percent"),
        "vix": (16.73, "Index"),
    }
    return USMacroSnapshot(
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
        observations=[
            MacroObservation(
                region="us", indicator=indicator, series_id=indicator, value=value, unit=unit,
                observation_date=date(2026, 7, 16), fetched_at=datetime.now(timezone.utc),
                source_name="FRED", source_url="https://fred.example", frequency="Daily",
            )
            for indicator, (value, unit) in values.items()
        ],
        warnings=["缺少市场数据"],
    )


def _assessment():
    return {
        "regime": "neutral",
        "horizons": {
            "下一交易日": {"direction": "neutral", "confidence": "低"},
            "未来1周": {"direction": "neutral", "confidence": "低", "drivers": ["2Y-10Y利差为0.41个百分点"]},
            "未来1个月": {"direction": "neutral", "confidence": "低"},
        },
    }


def test_stock_display_is_dynamic_and_localizes_sources_and_partial():
    raw = {
        "name": "示例公司", "code": "123456", "operation_advice": "观望", "sentiment_score": 54,
        "trend_prediction": "看多", "data_sources": "EfinanceFetcher,TencentFetcher", "news_summary": "暂无新闻",
        "market_snapshot": {"date": "2026-07-17"},
        "dashboard": {"phase_decision": {"watch_conditions": ["观察条件1：等待站上20日均线并出现放量确认"], "data_limitations": ["技术指标为partial状态", "technical: partial"]}},
    }
    context = {"enhanced_context": {"today": {"date": "2026-07-17", "data_source": "EfinanceFetcher"}, "realtime": {"source": "TencentFetcher"}, "chip": {"chip_status": "获利筹码较多"}, "trend_analysis": {"ma_alignment": "多头排列", "bias_ma5": 8.2, "risk_factors": ["量能尚待确认", "不应展示的第四项"]}}}

    message = build_stock_feishu_message(raw, context)

    assert message.startswith("示例公司｜123456｜股票分析")
    assert "趋势判断：偏多" in message
    assert "东方财富｜腾讯财经" in message
    assert "部分技术指标数据不完整" in message
    assert message.count("• ") == 3
    assert "partial" not in message
    assert "EfinanceFetcher" not in message
    assert STOCK_DISCLAIMER in message


def test_stock_display_does_not_invent_reasons_when_structured_indicators_missing():
    message = build_stock_feishu_message({"name": "空数据", "code": "000001", "sentiment_score": 40, "trend_prediction": "震荡"})
    assert "核心依据：" not in message
    assert "关注条件：" not in message


def test_stock_display_neutralizes_directives_and_volume_quality_limitations():
    raw = {
        "name": "风险标的", "code": "000002", "sentiment_score": 25, "trend_prediction": "强烈看空",
        "dashboard": {"phase_decision": {"watch_conditions": ["持仓者需坚决止损离场"], "data_limitations": ["成交量较前日异常放大136.2倍，存在数据失真风险", "技术指标为partial状态", "技术指标为partial状态"]}},
    }
    message = build_stock_feishu_message(raw)

    assert "止损" not in message and "离场" not in message
    assert "当前偏空判断仍然有效" in message
    assert "成交量数据存在异常，相关量价信号已从本次判断中降权或忽略" in message
    assert "136.2倍" not in message
    assert "。；" not in message and "；；" not in message
    assert "数据限制：" in message
    assert "部分技术指标数据不完整" in message


def test_stock_display_does_not_mutate_raw_result_or_context_snapshot():
    raw = {"name": "只读标的", "code": "000003", "sentiment_score": 40, "trend_prediction": "震荡"}
    context = {"enhanced_context": {"trend_analysis": {"ma_alignment": "震荡"}}}
    raw_before, context_before = deepcopy(raw), deepcopy(context)

    build_stock_feishu_message(raw, context)

    assert raw == raw_before
    assert context == context_before


def test_macro_display_uses_three_localized_titles_units_and_curve_basis_points():
    explanation = USMacroAIExplanation(
        core_logic="收益率曲线为正，但市场行情缺失。",
        bullish_factors=["曲线正斜率"], bearish_factors=["交叉验证不足"],
        risks=["市场数据缺失"], invalidation_conditions=["曲线转负"],
    )
    messages = build_us_macro_feishu_messages(_macro_snapshot(), _assessment(), explanation)
    all_text = "\n".join(messages)

    assert len(messages) == 3
    assert messages[0].startswith("美国宏观市场晨报｜核心结论｜2026-07-19")
    assert messages[1].startswith("美国宏观市场晨报｜利率与债券｜2026-07-19")
    assert messages[2].startswith("美国宏观市场晨报｜解释与风险｜2026-07-19")
    assert "市场环境：中性" in messages[0]
    assert "美联储目标利率区间：3.50%–3.75%" in messages[1]
    assert "2Y–10Y利差：+41bp" in messages[1]
    assert "VIX：16.73点" in messages[1]
    assert MACRO_DISCLAIMER in messages[2]
    for internal in ("neutral", "Percent", "Index", "policy_rate_lower", "policy_rate_upper", "treasury_2y", "treasury_10y"):
        assert internal not in all_text


def test_macro_display_without_ai_keeps_deterministic_report_and_no_send_side_effect():
    messages = build_us_macro_feishu_messages(_macro_snapshot(), _assessment())
    assert "当前解释暂不可用" in messages[2]
    assert len(messages) == 3
