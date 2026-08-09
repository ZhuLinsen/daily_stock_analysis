# -*- coding: utf-8 -*-

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.share_image import (
    DEFAULT_XIAOHONGSHU_HANDLE,
    DEFAULT_XIAOHONGSHU_QR_PATH,
    PROJECT_DISPLAY_NAME,
    PROJECT_REPOSITORY,
    ShareImageBranding,
    build_share_image_html,
    share_image_branding_from_config,
)

XIAOHONGSHU_HANDLE = "@示例账号"
XIAOHONGSHU_BRANDING = ShareImageBranding(
    xiaohongshu_url="https://example.com/xiaohongshu",
    xiaohongshu_handle=XIAOHONGSHU_HANDLE,
    xiaohongshu_id="123456",
    xiaohongshu_qr_path=str(
        Path(__file__).parents[1] / "src" / "assets" / "share_image" / "xiaohongshu_qr.jpg"
    ),
)


def test_stock_share_image_uses_configured_xiaohongshu_branding():
    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
        branding=XIAOHONGSHU_BRANDING,
    )

    assert 'class="poster stock"' in html
    assert "个股决策卡" in html
    assert "贵州茅台" in html
    assert '<span class="code">600519</span>' in html
    assert html.count('class="qr-frame"') == 1
    assert html.count("data:image/jpeg;base64,") == 1
    assert "项目主页二维码" not in html
    assert "GitHub 项目" not in html
    assert PROJECT_REPOSITORY in html
    assert "小红书二维码" in html
    assert PROJECT_DISPLAY_NAME in html
    assert f"<b>小红书</b>{XIAOHONGSHU_HANDLE}" in html
    assert "123456" not in html
    assert 'href="https://example.com/xiaohongshu"' in html
    assert "2026-07-31" in html
    assert html.count("<h1>") == 1


def test_stock_share_image_omits_unconfigured_social_account():
    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="qr-card' not in html
    assert "小红书" not in html
    assert 'class="footer-brand full"' in html


def test_runtime_branding_defaults_to_bundled_xiaohongshu_qr():
    branding = share_image_branding_from_config(object())

    assert branding.xiaohongshu_handle == DEFAULT_XIAOHONGSHU_HANDLE
    assert branding.xiaohongshu_id == ""
    assert branding.xiaohongshu_qr_path == DEFAULT_XIAOHONGSHU_QR_PATH
    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
        branding=branding,
    )

    assert html.count('class="qr-frame"') == 1
    assert html.count("data:image/jpeg;base64,") == 1
    assert f"<b>小红书</b>{DEFAULT_XIAOHONGSHU_HANDLE}" in html
    assert " ID " not in html


def test_runtime_branding_does_not_mix_default_qr_with_custom_identity():
    branding = share_image_branding_from_config(
        SimpleNamespace(
            share_image_xiaohongshu_url="https://example.com/custom",
            share_image_xiaohongshu_handle="@自定义账号",
            share_image_xiaohongshu_id="custom-id",
        )
    )

    assert branding.xiaohongshu_id == "custom-id"
    assert branding.xiaohongshu_qr_path == ""

    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
        branding=branding,
    )

    assert "<b>小红书</b>@自定义账号" in html
    assert "custom-id" not in html
    assert "data:image/jpeg;base64," not in html
    assert DEFAULT_XIAOHONGSHU_HANDLE not in html


def test_runtime_branding_does_not_mix_default_pair_with_custom_handle_or_url():
    branding = share_image_branding_from_config(
        SimpleNamespace(
            share_image_xiaohongshu_url="https://example.com/custom",
            share_image_xiaohongshu_handle="@自定义账号",
        )
    )

    assert branding.xiaohongshu_handle == "@自定义账号"
    assert branding.xiaohongshu_id == ""
    assert branding.xiaohongshu_qr_path == ""

    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
        branding=branding,
    )

    assert "@自定义账号" in html
    assert 'href="https://example.com/custom"' in html
    assert "data:image/jpeg;base64," not in html
    assert DEFAULT_XIAOHONGSHU_HANDLE not in html


def test_runtime_branding_does_not_mix_default_handle_with_custom_qr():
    branding = share_image_branding_from_config(
        SimpleNamespace(
            share_image_xiaohongshu_qr_path=str(
                Path(__file__).parents[1] / "src" / "assets" / "share_image" / "xiaohongshu_qr.jpg"
            ),
        )
    )

    assert branding.xiaohongshu_id == ""
    assert branding.xiaohongshu_qr_path

    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        generated_on=date(2026, 7, 31),
        branding=branding,
    )

    assert html.count("data:image/jpeg;base64,") == 1
    assert DEFAULT_XIAOHONGSHU_HANDLE not in html


def test_runtime_branding_treats_whitespace_only_values_as_unconfigured():
    branding = share_image_branding_from_config(
        SimpleNamespace(
            share_image_xiaohongshu_url="  ",
            share_image_xiaohongshu_handle="  ",
            share_image_xiaohongshu_id="  ",
            share_image_xiaohongshu_qr_path="  ",
        )
    )

    assert branding.xiaohongshu_handle == DEFAULT_XIAOHONGSHU_HANDLE
    assert branding.xiaohongshu_id == ""
    assert branding.xiaohongshu_qr_path == DEFAULT_XIAOHONGSHU_QR_PATH


def test_stock_share_image_does_not_link_unsafe_social_url():
    html = build_share_image_html(
        "# 贵州茅台 600519 分析报告\n\n## 核心判断\n\n- 趋势偏多\n",
        branding=ShareImageBranding(
            xiaohongshu_url="javascript:alert(1)",
            xiaohongshu_handle="@自定义账号",
        ),
    )

    assert "@自定义账号" in html
    assert "javascript:" not in html


def test_stock_share_image_prefers_structured_json_and_compacts_trade_points():
    payload = {
        "name": "中钨高新",
        "code": "000657",
        "sentiment_score": 40,
        "trend_prediction": "看空",
        "confidence_level": "中",
        "operation_advice": "观望",
        "current_price": 49.51,
        "change_pct": 2.29,
        "dashboard": {
            "core_conclusion": {
                "one_sentence": "空头趋势未止跌，冲高回落收最低，观望待企稳",
                "position_advice": {
                    "no_position": "等待右侧企稳信号（收复MA5并放量或回踩47.5缩量止跌）后再考虑",
                    "has_position": "反弹至MA10（55元附近）逢高减仓，跌破47.47前低务必止损离场",
                },
            },
            "data_perspective": {
                "trend_status": {"ma_alignment": "空头排列 MA5<MA10<MA20", "trend_score": 25},
                "price_position": {"support_level": 47.47, "resistance_level": 53.24, "bias_ma5": -6.02},
                "volume_analysis": {"volume_ratio": 1.13, "turnover_rate": 4.48},
            },
            "intelligence": {
                "positive_catalysts": ["2026H1归母净利预增261%~298%，基本面景气度高"],
                "risk_alerts": ["近7个交易日累计下跌16.07%，趋势破位未止跌"],
            },
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "暂无理想买点：需先收复并站稳MA5（52.68）且放量",
                    "secondary_buy": "放量收复MA10（55.13）确认趋势反转后介入",
                    "stop_loss": "跌破47.47即止损",
                    "take_profit": "第一压力53.24-55.13，第二压力63.76",
                }
            },
            "phase_decision": {
                "action_window": "非交易日观察（周六休市）",
                "next_check_time": "2026-08-03 09:15集合竞价及09:30开盘",
                "watch_conditions": [
                    "08-03能否守住47.47前低支撑，不破为短线企稳前提",
                    "能否放量收复MA5（52.68），上攻53.24-55.13压力区",
                ],
            },
        },
    }

    html = build_share_image_html(
        "# 中钨高新 000657 分析报告\n\n## 核心结论\n\n观望",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "中钨高新" in html
    assert 'class="signal-score warning"' in html
    assert 'class="signal-trend negative"' in html
    assert "置信度 中" in html
    assert 'class="metric red"><span>涨跌</span><strong>+2.29%</strong>' in html
    assert "等待企稳" in html
    assert "确认买入" in html
    assert "确认买入</span><strong>55.13" in html
    assert "47.47" in html
    assert "53.24–55.13" in html
    assert "25/100" in html
    assert "-6.02%" in html
    assert "下一步观察" in html
    assert "非交易日观察" in html
    assert "2026-08-03 09:15集合竞价" in html
    assert "需先收复并站稳" not in html
    assert "建仓策略" not in html
    assert "风控策略" not in html


def test_stock_share_image_merges_partial_intelligence_lists_with_markdown_fallback():
    payload = {
        "name": "中钨高新",
        "code": "000657",
        "dashboard": {
            "intelligence": {
                "positive_catalysts": ["订单修复信号开始出现，板块景气边际改善"],
                "risk_alerts": [],
            },
        },
    }

    html = build_share_image_html(
        """# 中钨高新 000657 分析报告

## 重要信息

**利好催化：**
- 钨价企稳叠加军工需求回暖，盈利弹性有望释放。
- 海外订单恢复，出口占比回升。

## 风险提示

- 下游需求恢复不及预期。
- 跌破关键支撑后可能继续放量回撤。
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "订单修复信号开始出现" in html
    assert "钨价企稳叠加军工需求回暖" in html
    assert "下游需求恢复不及预期" in html
    assert "跌破关键支撑后可能继续放量回撤" in html


def test_market_share_image_prefers_structured_market_metrics():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "title": "A股市场复盘",
        "date": "2026-08-01",
        "market_light": {
            "score": 83,
            "temperature_label": "强势",
            "label": "可进攻",
            "dimensions": {
                "breadth": {"score": 86},
                "index": {"score": 69},
                "limit": {"score": 100},
            },
        },
        "indices": [
            {"name": "上证指数", "current": 3559.95, "change_pct": 0.72},
            {"name": "深证成指", "current": 11206.12, "change_pct": 2.21},
            {"name": "创业板指", "current": 2328.31, "change_pct": 3.06},
            {"name": "科创50", "current": 1635.96, "change_pct": 2.99},
        ],
        "breadth": {
            "up_count": 4690,
            "down_count": 728,
            "limit_up_count": 101,
            "limit_down_count": 0,
            "total_amount": 25591,
            "turnover_unit": "亿元",
        },
        "sectors": {
            "top": [{"name": "半导体", "change_pct": 4.25}],
            "bottom": [{"name": "货币金融服务", "change_pct": -1.10}],
        },
    }
    html = build_share_image_html(
        """# A股大盘复盘

## 2026-08-01 大盘复盘

> 指数普涨，市场情绪明显回暖。

### 一、盘面总览
- **盘面信号**：20/100（偏弱，防守）
- **操作建议**：关注成交额和主线持续性。

### 四、资金与情绪
涨跌比接近6.4:1，成交额较前一交易日放量逾2000亿元；科创方向冲高回落，资金分歧明显。

### 六、明日交易计划
结论：均衡偏进攻。
- 仓位区间：建议维持5-7成。
- 关注方向：其一，软件、AI应用等方向；其二，建筑装饰、食品制造等低位方向。
- 回避方向：科创50中冲高回落的半导体设备等高位标的；银行、保险等防御板块。
- 触发失效条件：成交额缩至2.2万亿以下则降仓。

### 七、风险提示
- 高位板块回撤。
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "<strong>83</strong><small>/100</small>" in html
    assert '<div class="market-label">可进攻</div>' in html
    assert '<div class="market-label">强势</div>' not in html
    assert "+0.72%" in html
    assert "4690" in html
    assert "2.56万亿" in html
    assert "半导体" in html
    assert "科创50" in html
    assert "信号拆解" in html
    assert "86/100" in html
    assert "弱势板块" in html
    assert "货币金融服务" in html
    assert "重点跟踪" in html
    assert "软件、AI应用" in html
    assert "半导体设备" in html
    assert "资金观察" in html
    assert "+2000亿" in html
    assert "20/100" not in html


def test_market_share_image_hides_unavailable_dimensions_and_uses_payload_color_scheme():
    payload = {
        "kind": "market_review",
        "region": "us",
        "color_scheme": "red_up",
        "market_light": {
            "score": 65,
            "dimensions": {
                "breadth": {"score": 50, "available": False},
                "index": {"score": 72, "available": True},
                "limit": {"score": 50, "available": False},
            },
        },
        "indices": [
            {"name": "S&P 500", "current": 6500, "change_pct": 0.8},
        ],
    }

    html = build_share_image_html(
        "# US Market Recap\n\n## Major Indices\n\n- S&P 500 closed higher.",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "Index Strength" in html
    assert "72/100" in html
    assert "Breadth Score" not in html
    assert "Limit Structure" not in html
    assert '<strong class="red">+0.80%</strong>' in html


def test_market_share_image_skips_unavailable_market_light_overlay():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "market_light": {
            "score": 50,
            "temperature_label": "震荡",
            "label": "需观察",
            "data_quality": "unavailable",
            "dimensions": {
                "breadth": {"score": 50, "available": False},
                "index": {"score": 50, "available": False},
                "limit": {"score": 50, "available": False},
            },
        },
    }

    html = build_share_image_html(
        """# A股大盘复盘

> 指数数据暂缺，等待补齐后再看盘面。
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert 'class="market-signal"' not in html
    assert '<div class="market-label">需观察</div>' not in html
    assert "<small>/100</small>" not in html


def test_market_share_image_merges_partial_structured_indices_with_markdown_fallback():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "indices": [
            {"name": "上证指数", "change_pct": 0.72},
            {"name": "创业板指", "current": 2328.31, "change_pct": 3.06},
        ],
    }

    html = build_share_image_html(
        """# A股大盘复盘

## 指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3559.95 | +0.80% |
| 深证成指 | 11206.12 | +2.21% |
| 创业板指 | 2200.00 | +2.50% |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "3559.95" in html
    assert "+0.72%" in html
    assert "11206.12" in html
    assert "+2.21%" in html
    assert "2328.31" in html
    assert "+3.06%" in html


def test_market_share_image_merges_partial_structured_breadth_with_markdown_fallback():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "breadth": {
            "up_count": 3200,
            "total_amount": 12500,
            "turnover_unit": "亿元",
        },
    }

    html = build_share_image_html(
        """# A股大盘复盘

## 盘面总览

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 3000 / 1800 |
| 涨停/跌停 | 80 / 6 |
| 两市成交额 | 1.10万亿 |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "3200" in html
    assert "1800" in html
    assert "80" in html
    assert "6" in html
    assert "1.25万亿" in html


def test_market_share_image_uses_payload_color_scheme_for_sector_rankings():
    payload = {
        "kind": "market_review",
        "region": "us",
        "color_scheme": "green_up",
        "sectors": {
            "top": [
                {"name": "Software", "change_pct": 1.25},
                {"name": "Semis", "change_pct": 0.8},
            ],
            "bottom": [
                {"name": "Utilities", "change_pct": -0.35},
                {"name": "Staples", "change_pct": -0.2},
            ],
        },
    }

    html = build_share_image_html(
        "# US Market Recap\n\n## Sector Highlights\n\n- Software leads.\n",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert '<strong class="green">+1.25%</strong>' in html
    assert '<strong class="green">+0.80%</strong>' in html
    assert '<strong class="red">-0.35%</strong>' in html
    assert '<strong class="red">-0.20%</strong>' in html
    assert ".ranking-row.lagging strong{color:#0a9c58}" not in html


def test_market_share_image_merges_partial_structured_sectors_with_markdown_fallback():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "sectors": {
            "top": [
                {"name": "AI算力"},
                {"name": "机器人", "change_pct": 2.45},
            ],
            "bottom": [
                {"name": "消费"},
                {"name": "地产", "change_pct": -1.3},
            ],
        },
    }

    html = build_share_image_html(
        """# A股大盘复盘

## 板块主线

### 领涨板块 Top 3

| 排名 | 板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | AI算力 | +3.20% |
| 2 | 机器人 | +2.10% |
| 3 | 算力租赁 | +1.50% |

### 领跌板块 Top 3

| 排名 | 板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | 消费 | -1.80% |
| 2 | 地产 | -1.10% |
| 3 | 医药 | -0.80% |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "AI算力" in html
    assert "+3.20%" in html
    assert "机器人" in html
    assert "+2.45%" in html
    assert "算力租赁" in html
    assert "+1.50%" in html
    assert "消费" in html
    assert "-1.80%" in html
    assert "地产" in html
    assert "-1.30%" in html
    assert "医药" in html
    assert "-0.80%" in html


def test_market_share_image_does_not_replace_markdown_sector_with_unmatched_name_only_overlay():
    payload = {
        "kind": "market_review",
        "region": "cn",
        "sectors": {
            "top": [
                {"name": "新消费"},
            ],
        },
    }

    html = build_share_image_html(
        """# A股大盘复盘

## 板块主线

### 领涨板块 Top 3

| 排名 | 板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | AI算力 | +3.20% |
| 2 | 机器人 | +2.10% |
| 3 | 算力租赁 | +1.50% |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "AI算力" in html
    assert "+3.20%" in html
    assert "机器人" in html
    assert "+2.10%" in html
    assert "算力租赁" in html
    assert "+1.50%" in html
    assert "新消费" not in html


def test_market_share_image_uses_market_variant_and_preserves_tables():
    html = build_share_image_html(
        "# A 股大盘复盘\n\n## 指数表现\n\n| 指数 | 涨跌 |\n| --- | --- |\n| 上证 | +0.8% |",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "市场复盘" in html
    assert "<table>" in html
    assert "上证" in html
    assert "+0.8%" in html


def test_market_share_image_populates_decision_modules_from_report_contract():
    html = build_share_image_html(
        """# 🎯 大盘复盘

## 2026-07-31 大盘复盘

> 今日A股温和上行，但仍需观察成交额能否延续。

### 一、盘面总览

- **盘面信号**：66/100（偏暖，可进攻）
- **操作建议**：关注主线延续，避免追高。

| 指标 | 数值 | 观察 |
| --- | --- | --- |
| 上涨/下跌/平盘 | 3298 / 1687 / 70 | 扩散 |
| 涨停/跌停 | 72 / 6 | 正向 |
| 两市成交额 | 1.12 万亿 | 活跃 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3185.53 | +0.80% |
| 深证成指 | 9732.28 | +1.12% |
| 创业板指 | 1875.90 | +0.65% |

### 三、板块主线

#### 领涨板块 Top 3

| 排名 | 板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | 半导体 | +3.2% |
| 2 | 消费电子 | +2.6% |
| 3 | 机器人 | +2.1% |

### 五、消息催化

- 国产算力产业链活跃。

### 六、明日交易计划

**结论：建设性偏多。**
**仓位区间：** 5-7成。
**关注方向：** 权重板块承接。

### 七、风险提示

1. 高位板块回撤。
""",
        generated_on=date(2026, 7, 31),
    )

    assert '<section class="market-signal">' in html
    assert '<strong>66</strong><small>/100</small>' in html
    assert "上证指数" in html
    assert "3298" in html
    assert "半导体" in html
    assert "建设性偏多" in html
    assert "高位板块回撤" in html


def test_market_share_image_does_not_duplicate_full_report_for_extra_detail_sections():
    html = build_share_image_html(
        """# 大盘复盘

### 一、盘面总览

- **盘面信号**：83/100（强势，可进攻）
- **操作建议**：关注主线延续与仓位纪律。

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌/平盘 | 4690 / 728 / 109 |
| 涨停/跌停 | 101 / 0 |
| 两市成交额 | 25591 亿 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3832.26 | +0.72% |

### 三、板块主线

| 排名 | 行业板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | 软件和信息技术服务业 | +7.75% |

### 四、资金与情绪

成交额放大，赚钱效应扩散，但高位股分歧增加。

### 五、消息催化

- 稳增长政策预期升温。

### 六、明日交易计划

- 仓位区间：5-7成。

### 七、风险提示

- 高位科技股分歧扩散。
""",
        generated_on=date(2026, 8, 1),
    )

    assert '<section class="market-signal">' in html
    assert "软件和信息技术服务业" in html
    assert "稳增长政策预期升温" in html
    assert '<section class="report-fallback">' not in html


def test_market_share_image_preserves_scoreless_overview_guidance_without_fallback():
    html = build_share_image_html(
        """# A股市场复盘

> 量能尚未完全回到进攻区间。

## 盘面总览

**操作建议：** 等待放量确认后再提升仓位，避免尾盘追涨。
**信号依据：** 成交额仍低于强趋势阈值；权重护盘但题材扩散一般。

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 3012 / 1988 |
| 涨停/跌停 | 58 / 9 |
| 成交额 | 8921 亿 |

## 指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3210.11 | +0.34% |

## 板块主线

| 排名 | 板块 | 涨跌幅 |
| --- | --- | --- |
| 1 | 银行 | +1.20% |

## 明日交易计划

- 结论：先观察量能能否继续修复。

## 风险提示

- 缩量反弹后冲高回落。
""",
        generated_on=date(2026, 8, 1),
    )

    assert '<section class="market-signal">' not in html
    assert "等待放量确认后再提升仓位" in html
    assert "成交额仍低于强趋势阈值" in html
    assert "权重护盘但题材扩散一般" in html
    assert '<section class="report-fallback">' not in html


def test_market_share_image_preserves_report_color_scheme_from_index_markers():
    html = build_share_image_html(
        """# 大盘复盘

### 一、盘面总览

- **盘面信号**：60/100（偏暖，可进攻）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌/平盘 | 3000 / 1800 / 20 |
| 涨停/跌停 | 60 / 8 |
| 两市成交额 | 10000 亿 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3200 | 🔴 +0.80% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert '<strong class="red">+0.80%</strong>' in html
    assert 'class="metric red"><span>上涨</span>' in html


def test_generic_share_image_wraps_long_preformatted_lines_and_urls_in_fallback():
    html = build_share_image_html(
        """# 完整报告

## 原始链接

https://example.com/this-is-a-very-long-url-with-no-natural-breakpoints/abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ

## 调试片段

```text
TRACEBACK_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz_TRACEBACK_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz
```
""",
        generated_on=date(2026, 8, 1),
    )

    assert 'class="poster dashboard"' in html
    assert '<section class="report-fallback">' in html
    assert "<pre>" in html
    assert "<code>" in html
    assert ".report-content{overflow-wrap:anywhere}" in html
    assert ".report-content h1,.report-content h2,.report-content h3{color:#153d78;overflow-wrap:anywhere;word-break:break-word}" in html
    assert ".report-content p,.report-content li,.report-content th,.report-content td,.report-content blockquote,.report-content a{overflow-wrap:anywhere;word-break:break-word}" in html
    assert ".report-content pre{max-width:100%;" in html
    assert "white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word" in html


def test_real_single_stock_shape_uses_h2_title_score_and_sniper_contract():
    html = build_share_image_html(
        """## 🟢 贵州茅台 (600519)

> 2026-07-31 15:30 | 评分: **72** | 看多

### 📌 核心结论

**买入**: 回调到支撑区可分批关注。

### 🎯 操作点位

| 操作点位 | 当前价格 |
| --- | --- |
| 🎯 理想买入点 | 1420-1450 |
| 🔵 次优买入点 | 1380-1400 |
| 🛑 止损位 | 1350 |
| 🎊 目标位 | 1580 |
""",
        generated_on=date(2026, 7, 31),
    )

    assert "贵州茅台" in html
    assert '<span class="code">600519</span>' in html
    assert "个股决策卡" in html
    assert '<strong>72</strong><small>/100</small>' in html
    assert "回调到支撑区可分批关注" in html
    assert "综合评分" not in html
    assert 'class="signal-trend positive"' in html
    assert ">看多<" in html
    assert "sniper-table" in html
    assert 'class="metric sniper buy"' in html
    assert 'class="metric sniper stop"' in html
    assert 'class="metric sniper target"' in html


def test_stock_share_image_reads_notification_service_chinese_market_snapshot_heading():
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**买入**：回调到支撑区可分批关注。

### 当日行情

| 当前价 | 涨跌幅 | 量比 | 换手率 | 行情来源 |
| --- | --- | --- | --- | --- |
| 1425.00 | +1.20% | 1.35 | 0.82% | 腾讯财经 |
""",
        generated_on=date(2026, 7, 31),
    )

    assert "市场快照" in html
    assert "1425.00" in html
    assert "+1.20%" in html
    assert "1.35" in html
    assert "0.82%" in html
    assert "数据源：腾讯财经" in html


def test_stock_share_image_reads_close_only_market_snapshot_column():
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**买入**：回调到支撑区可分批关注。

### 当日行情

| 收盘 | 涨跌幅 | 量比 | 换手率 |
| --- | --- | --- | --- |
| 1420.00 | +0.90% | 1.18 | 0.76% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert "市场快照" in html
    assert "1420.00" in html
    assert "+0.90%" in html
    assert "1.18" in html
    assert "0.76%" in html


def test_partial_stock_payload_preserves_markdown_snapshot_technical_and_trade_points():
    payload = {
        "name": "贵州茅台",
        "code": "600519",
        "dashboard": {
            "core_conclusion": {"one_sentence": "等待支撑确认。"},
        },
    }
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**买入**：等待支撑确认。

### 当日行情

| 当前价 | 涨跌幅 | 量比 | 换手率 |
| --- | --- | --- | --- |
| 1425.00 | +1.20% | 1.35 | 0.82% |

### 数据透视

**成交量**: 量比 1.35 | 换手率 0.82%

### 作战计划

| 点位类型 | 价格 |
| --- | --- |
| 理想买入点 | 1420-1450 |
| 止损位 | 1350 |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "1425.00" in html
    assert "+1.20%" in html
    assert "量比 1.35" in html
    assert "<strong>1420</strong>" in html
    assert "1350" in html


def test_complete_stock_volume_payload_does_not_duplicate_verbose_volume_card():
    payload = {
        "name": "贵州茅台",
        "code": "600519",
        "dashboard": {
            "data_perspective": {
                "volume_analysis": {
                    "volume_ratio": 1.35,
                    "turnover_rate": 0.82,
                },
            },
        },
    }
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**持有**：继续观察。

### 数据透视

**成交量**: 量比 1.35，量能正常，较 5 日均量放大约 5% | 换手率 0.82%
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "较 5 日均量放大" not in html
    assert "1.35" in html
    assert "0.82%" in html


def test_stock_payload_market_snapshot_overlays_only_populated_fields():
    payload = {
        "name": "贵州茅台",
        "code": "600519",
        "dashboard": {},
        "market_snapshot": {"price": "1430.00", "source": "tencent"},
    }
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**持有**：继续观察。

### 当日行情

| 当前价 | 涨跌幅 | 量比 | 换手率 |
| --- | --- | --- | --- |
| 1425.00 | +1.20% | 1.35 | 0.82% |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "1430.00" in html
    assert "1425.00" not in html
    assert "+1.20%" in html
    assert "1.35" in html
    assert "0.82%" in html
    assert "数据源：tencent" in html


def test_stock_share_image_prefers_realtime_price_over_close_in_combined_snapshot():
    html = build_share_image_html(
        """# 贵州茅台 600519 分析报告

## 核心结论

**买入**：回调到支撑区可分批关注。

### 当日行情

| 收盘 | 当前价 | 涨跌幅 | 量比 | 换手率 |
| --- | --- | --- | --- | --- |
| 1420.00 | 1425.00 | +1.20% | 1.35 | 0.82% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert "市场快照" in html
    assert "1425.00" in html
    assert "1420.00" not in html


def test_stock_share_image_reads_chinese_volume_label_from_data_view():
    html = build_share_image_html(
        """## 🟢 贵州茅台 (600519)

> 2026-07-31 15:30 | 评分: **72** | 看多

### 📌 核心结论

**买入**: 回调到支撑区可分批关注。

### 📊 数据透视

**均线排列**: 多头排列

**成交量**: 量比 1.35 (放量) | 换手率 0.82%
""",
        generated_on=date(2026, 7, 31),
    )

    assert "技术参考" in html
    assert ">量能<" in html
    assert "1.35" in html
    assert "0.82%" in html


def test_share_image_escapes_title_but_keeps_markdown_body_markup():
    html = build_share_image_html(
        "# AAPL <script>alert(1)</script>\n\n**结论**：关注。",
        generated_on=date(2026, 7, 31),
    )

    assert "AAPL alert(1)" in html
    assert "<script>" not in html
    assert "<strong>结论</strong>" in html


def test_english_company_name_is_not_mistaken_for_a_ticker():
    html = build_share_image_html(
        "## Apple Inc. (AAPL)\n\n> 2026-07-31 | Score: **70** | Bullish",
        generated_on=date(2026, 7, 31),
    )

    assert "Apple Inc." in html
    assert '<span class="code">AAPL</span>' in html


def test_dotted_us_ticker_is_preserved_in_stock_heading():
    html = build_share_image_html(
        "## Berkshire Hathaway (BRK.B)\n\n> 2026-07-31 | Score: **70** | Bullish",
        generated_on=date(2026, 7, 31),
    )

    assert "Berkshire Hathaway" in html
    assert '<span class="code">BRK.B</span>' in html


@pytest.mark.parametrize(
    ("heading", "company", "code"),
    [
        ("## 台积电 (2330.TW)", "台积电", "2330.TW"),
        ("## 台塑化 (6505.TWO)", "台塑化", "6505.TWO"),
        ("## 国泰永续高股息 (00878.TW)", "国泰永续高股息", "00878.TW"),
    ],
)
def test_suffix_stock_code_is_preserved_in_stock_heading(heading, company, code):
    html = build_share_image_html(
        f"{heading}\n\n> 2026-07-31 | Score: **70** | Bullish",
        generated_on=date(2026, 7, 31),
    )

    assert company in html
    assert f'<span class="code">{code}</span>' in html


def test_korean_market_review_heading_uses_market_poster():
    html = build_share_image_html(
        "# 미국 시황 리뷰\n\n## 지수 구조\n\n| 지수 | 최신 | 涨跌幅 |\n| --- | --- | --- |\n| S&P 500 | 6200 | +0.8% |",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "多股决策摘要" not in html
    assert "미국 시황 리뷰" in html


def test_korean_multi_market_review_skips_root_wrapper_segment():
    html = build_share_image_html(
        """# 🎯 시황 리뷰

> 여러 시장 마감 요약.

# 미국 시황 리뷰

## 2026-07-31 미국 시황 리뷰

### 1. 시장 요약

- **시장 신호**: 66/100 (건설적, 위험 선호)

### 2. 주요 지수

| 지수 | 최신 | 등락률 |
| --- | --- | --- |
| S&P 500 | 6200 | +0.8% |

> 다음 시장 시황 리뷰

# 홍콩 시황 리뷰

## 2026-07-31 홍콩 시황 리뷰

### 1. 시장 요약

- **시장 신호**: 58/100 (중립, 선별)

### 2. 주요 지수

| 지수 | 최신 | 등락률 |
| --- | --- | --- |
| Hang Seng | 18200 | +1.2% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "다중 시장 리뷰" in html
    assert "미국 시황 리뷰" in html
    assert "홍콩 시황 리뷰" in html
    assert "여러 시장 마감 요약" not in html


def test_stock_report_market_snapshot_does_not_route_to_market_poster():
    html = build_share_image_html(
        """# Apple Inc. (AAPL)

## Core Conclusion

**Buy**: Pullbacks into support remain actionable.

## Market Snapshot

| Current Price | Change % | Volume Ratio | Source |
| --- | --- | --- | --- |
| 210.15 | +1.5% | 1.2x | IEX |

## Action Levels

| Ideal Entry | Secondary Entry | Stop Loss | Target |
| --- | --- | --- | --- |
| 205-207 | 202-204 | 198 | 220 |

## Risk Alerts

- A failed earnings guide can break momentum.
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster stock"' in html
    assert "Stock decision card" in html
    assert "Apple Inc." in html
    assert "Ideal Entry" in html
    assert "failed earnings guide" in html


def test_multi_market_review_keeps_every_region_in_share_image():
    html = build_share_image_html(
        """# A股大盘复盘

## 2026-07-31 A股大盘复盘

> 今日A股情绪修复。

### 一、盘面总览

- **盘面信号**：66/100（偏暖，可进攻）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 3200 / 1500 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3200 | +0.80% |

---

> 以下为下一市场大盘复盘

# 港股大盘复盘

## 2026-07-31 港股大盘复盘

> 今日港股科技反弹。

### 一、盘面总览

- **盘面信号**：61/100（偏暖，可进攻）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 900 / 700 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 恒生指数 | 18200 | +1.20% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "多市场复盘" in html
    assert "A股市场复盘" in html
    assert "港股市场复盘" in html
    assert "上证指数" in html
    assert "恒生指数" in html


def test_multi_market_review_uses_each_structured_market_payload():
    payload = {
        "kind": "market_review",
        "region": "cn,us",
        "language": "zh",
        "markets": {
            "cn": {
                "region": "cn",
                "title": "A股市场复盘",
                "color_scheme": "green_up",
                "market_light": {
                    "score": 81,
                    "dimensions": {
                        "breadth": {"score": 88, "available": True},
                    },
                },
                "indices": [
                    {"name": "结构化上证", "current": 3999, "change_pct": 0.9},
                ],
            },
            "us": {
                "region": "us",
                "title": "美股市场复盘",
                "color_scheme": "green_up",
                "market_light": {
                    "score": 67,
                    "dimensions": {
                        "breadth": {"score": 50, "available": False},
                        "index": {"score": 71, "available": True},
                    },
                },
                "indices": [
                    {"name": "Structured Nasdaq", "current": 7777, "change_pct": 1.1},
                ],
            },
        },
    }
    html = build_share_image_html(
        """# A股大盘复盘

## 指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3200 | +0.80% |

# 美股大盘复盘

## Major Indices

| Index | Last | Change % |
| --- | --- | --- |
| Nasdaq | 6500 | +0.70% |
""",
        generated_on=date(2026, 8, 1),
        structured_payload=payload,
    )

    assert "结构化上证" in html
    assert "3999" in html
    assert "Structured Nasdaq" in html
    assert "7777" in html
    assert "88/100" in html
    assert "71/100" in html
    assert html.count("赚钱效应") == 1


@pytest.mark.parametrize("action", ["强烈买入", "Strong Buy"])
def test_stock_share_image_preserves_compound_buy_action(action):
    html = build_share_image_html(
        f"## Apple (AAPL)\n\n## Core Conclusion\n\n**{action}**: Momentum remains constructive.",
        generated_on=date(2026, 8, 1),
    )

    assert f'<div class="action-chip positive">{action}</div>' in html


def test_stock_share_image_finds_action_after_other_bold_labeled_fields():
    html = build_share_image_html(
        """## Apple (AAPL)

## Core Conclusion

**One-line Decision**: Wait for confirmation.

**Strong Buy**: Momentum remains constructive.
""",
        generated_on=date(2026, 8, 1),
    )

    assert '<div class="action-chip positive">Strong Buy</div>' in html


def test_multi_market_review_ignores_root_wrapper_title_when_splitting_regions():
    html = build_share_image_html(
        """# 🎯 大盘复盘

> 汇总多个市场的收盘观察。

# A股大盘复盘

## 2026-07-31 A股大盘复盘

> 今日A股情绪修复。

### 一、盘面总览

- **盘面信号**：66/100（偏暖，可进攻）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 3200 / 1500 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3200 | +0.80% |

---

> 以下为下一市场大盘复盘

# 港股大盘复盘

## 2026-07-31 港股大盘复盘

> 今日港股科技反弹。

### 一、盘面总览

- **盘面信号**：61/100（偏暖，可进攻）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 900 / 700 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 恒生指数 | 18200 | +1.20% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert html.count("A股市场复盘") == 1
    assert html.count("港股市场复盘") == 1
    assert "汇总多个市场的收盘观察" not in html
    assert "上证指数" in html
    assert "恒生指数" in html


def test_english_multi_market_review_maps_region_titles_from_headings():
    html = build_share_image_html(
        """# US Market Recap

## 2026-07-31 US Market Recap

> US breadth improved into the close.

### 1. Market Summary

- **Market Signal**: 62/100 (constructive, risk-on)

### 2. Index Commentary

| Index | Last | Change % |
| --- | --- | --- |
| S&P 500 | 6500 | +0.80% |

# HK Market Recap

## 2026-07-31 HK Market Recap

> Hong Kong tech outperformed.

### 1. Market Summary

- **Market Signal**: 58/100 (neutral, selective)

### 2. Index Commentary

| Index | Last | Change % |
| --- | --- | --- |
| Hang Seng Index | 18200 | +1.20% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "US Market Recap" in html
    assert "HK Market Recap" in html
    assert "A股市场复盘" not in html


def test_generic_market_review_does_not_treat_english_pronoun_us_as_us_market():
    html = build_share_image_html(
        """# 大盘复盘

> This gives us more room to focus on the strongest sectors.

## 2026-07-31 大盘复盘

### 1. 盘面总览

- **盘面信号**：60/100（中性，均衡）

### 2. 指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3400 | +0.20% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "大盘复盘" in html
    assert "美股市场复盘" not in html


def test_hidden_market_region_metadata_preserves_single_region_chinese_market_title():
    html = build_share_image_html(
        """[dsa-market-region]: # (us)

# 🎯 大盘复盘

## 2026-07-31 大盘复盘

> 今晚先看科技股财报与指数承接。

### 一、盘面总览

- **盘面信号**：63/100（偏暖，可进攻）

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 纳斯达克 | 19000 | +0.95% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "美股市场复盘" in html
    assert "A股市场复盘" not in html


def test_hidden_market_region_metadata_overrides_body_scope_mentions():
    html = build_share_image_html(
        """[dsa-market-region]: # (us)

# 🎯 大盘复盘

## 2026-07-31 大盘复盘

> 今晚主要看美股科技股财报，同时留意其与A股风险偏好的联动。

### 一、盘面总览

- **盘面信号**：63/100（偏暖，可进攻）

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 纳斯达克 | 19000 | +0.95% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "美股市场复盘" in html
    assert "A股市场复盘" not in html


def test_english_breadth_line_populates_structured_market_breadth_cards():
    html = build_share_image_html(
        """# US Market Recap

## 2026-07-31 US Market Recap

> Breadth and liquidity both improved.

### 1. Market Summary

- **Market Signal**: 66/100 (constructive, risk-on)
- **Breadth**: Advancers 3200 / Decliners 1800 / Flat 100; Limit-up 88 / Limit-down 5; Turnover 14567 (CNY 100m)

### 2. Major Indices

| Index | Last | Change % |
| --- | --- | --- |
| S&P 500 | 6500 | +0.80% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "US Market Recap" in html
    assert "Market Breadth" in html
    assert "3200" in html
    assert "1800" in html
    assert "88" in html
    assert "14567 (CNY 100m)" in html


def test_market_share_image_keeps_signal_card_without_breadth_for_hk_review():
    html = build_share_image_html(
        """# HK Market Recap

## 2026-07-31 HK Market Recap

> Hong Kong tech outperformed into the close.

### 1. Market Summary

- **Market Signal**: 58/100 (neutral, selective)
- **Drivers**: Hang Seng held above prior support; average major-index change +0.42%
- **Guidance**: Signals are mixed; keep position sizing moderate and wait for confirmation.

### 2. Major Indices

| Index | Last | Change % |
| --- | --- | --- |
| Hang Seng Index | 18200 | +1.20% |
| Hang Seng Tech | 3900 | +1.85% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert '<section class="market-signal">' in html
    assert '<strong>58</strong><small>/100</small>' in html
    assert "selective" in html
    assert "Hang Seng held above prior support" not in html
    assert "Signals are mixed" in html
    assert "市场宽度" not in html


def test_korean_market_review_preserves_localized_sections_with_english_sector_fallback():
    html = build_share_image_html(
        """# 중국 A주 시황 리뷰

## 2026-07-31 중국 A주 시황 리뷰

> 거래대금은 회복됐지만 추격 매수는 아직 신중해야 합니다.

### 1. 시장 요약

- **시장 신호**: 66/100 (건설적, 위험 선호)
- **운용 제안**: 주도 섹터 눌림목만 선별한다.
- **신호 근거**: 거래대금 회복; 상승 종목 확산

| 지표 | 수치 |
| --- | --- |
| 상승/하락 | 3200 / 1500 |
| 상한가/하한가 | 80 / 5 |
| 거래대금 | 1.1조 위안 |

### 2. 주요 지수

| 지수 | 최신 | 등락률 |
| --- | --- | --- |
| 상하이종합 | 3200 | +0.80% |

### 3. 내일 거래 계획

- 눌림목 확인 후 분할 대응.

### 4. 리스크 경보

- 추격 매수 과열 가능성.

### 5. Sector Highlights

| Rank | Sector | Change % |
| --- | --- | --- |
| 1 | 반도체 | +3.2% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert '<section class="market-signal">' in html
    assert "중국 A주 시황 리뷰" in html
    assert "주도 섹터 눌림목만 선별한다" in html
    assert "상하이종합" in html
    assert "3200" in html
    assert "눌림목 확인 후 분할 대응." in html
    assert "추격 매수 과열 가능성." in html
    assert "반도체" in html


def test_korean_market_review_keeps_fallback_body_when_only_sector_fallback_is_structured():
    html = build_share_image_html(
        """# 중국 A주 시황 리뷰

## 2026-07-31 중국 A주 시황 리뷰

> 거래대금은 회복됐지만 추격 매수는 아직 신중해야 합니다.

### 1. 시장 개요

- **시장 체력**: 회복 구간이지만 추세 확인이 더 필요합니다.
- **운용 포인트**: 눌림목만 선별 대응합니다.

### 2. 주요 지표

| 지수 | 최신 | 변동률 |
| --- | --- | --- |
| 상하이종합 | 3200 | +0.80% |

### 3. 내일 전략

- 눌림목 확인 후 분할 대응.

### 4. 위험 요인

- 추격 매수 과열 가능성.

### 5. Sector Highlights

| Rank | Sector | Change % |
| --- | --- | --- |
| 1 | 반도체 | +3.2% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert '<section class="report-fallback">' in html
    assert "시장 체력" in html
    assert "내일 전략" in html
    assert "위험 요인" in html
    assert "반도체" in html


def test_market_share_image_parses_fallback_major_indices_bullets():
    html = build_share_image_html(
        """# US Market Recap

## 2026-07-31 US Market Recap

> Breadth and liquidity both improved.

### 1. Market Summary

- **Market Signal**: 66/100 (constructive, risk-on)
- **Drivers**: Mega-cap tech led into the close.
- **Guidance**: Stay selective and wait for confirmation.

### 2. Major Indices
- **S&P 500**: 5000.00 (↑0.50%)
- **Nasdaq**: 18000.00 (↓0.20%)
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster market"' in html
    assert "S&amp;P 500" in html
    assert "5000.00" in html
    assert "↑0.50%" in html
    assert "Nasdaq" in html
    assert "↓0.20%" in html


def test_arrow_only_fallback_keeps_default_gain_color_when_first_index_declines():
    html = build_share_image_html(
        """# US Market Recap

## Market Summary

- **Breadth**: Advancers 1200 / Decliners 3800

## Major Indices

- **S&P 500**: 5000.00 (↓0.80%)
""",
        generated_on=date(2026, 8, 1),
    )

    assert 'class="metric green"><span>Advancers</span>' in html
    assert 'class="metric red"><span>Decliners</span>' in html


def test_market_share_image_uses_red_up_gain_color_for_breadth_when_all_indices_decline():
    html = build_share_image_html(
        """# 大盘复盘

### 一、盘面总览

- **盘面信号**：60/100（偏弱，防守）

| 指标 | 数值 |
| --- | --- |
| 上涨/下跌 | 1200 / 3800 |
| 涨停/跌停 | 18 / 42 |
| 两市成交额 | 9200 亿 |

### 二、指数结构

| 指数 | 最新 | 涨跌幅 |
| --- | --- | --- |
| 上证指数 | 3200 | 🟢 -0.80% |
| 深证成指 | 9800 | 🟢 -1.20% |
""",
        generated_on=date(2026, 7, 31),
    )

    assert '<strong class="green">-0.80%</strong>' in html
    assert 'class="metric red"><span>上涨</span>' in html
    assert 'class="metric green"><span>下跌</span>' in html


def test_market_share_image_preserves_red_up_colors_for_english_fallback_index_bullets():
    html = build_share_image_html(
        """# US Market Recap

## 2026-07-31 US Market Recap

> Breadth improved while leadership stayed concentrated.

### 1. Market Summary

- **Market Signal**: 66/100 (constructive, risk-on)
- **Breadth**: Advancers 3200 / Decliners 1800; Limit-up 88 / Limit-down 5

### 2. Major Indices

- **S&P 500**: 5000.00 (🔴 +0.80%)
- **Nasdaq**: 18000.00 (🟢 -0.20%)
""",
        generated_on=date(2026, 7, 31),
    )

    assert '<strong class="red">🔴 +0.80%</strong>' in html
    assert '<strong class="green">🟢 -0.20%</strong>' in html
    assert 'class="metric red"><span>Advancers</span>' in html
    assert 'class="metric green"><span>Decliners</span>' in html


def test_single_stock_dashboard_title_routes_to_stock_poster():
    html = build_share_image_html(
        """# 2026-07-31 Decision Dashboard

## Apple Inc. (AAPL)

> 2026-07-31 15:30 | Score: **70** | Bullish

### Core Conclusion

**Buy**: Pullbacks into support remain actionable.

### Action Levels

| Ideal Entry | Secondary Entry | Stop Loss | Target |
| --- | --- | --- | --- |
| 205-207 | 202-204 | 198 | 220 |
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster stock"' in html
    assert "Stock decision card" in html
    assert "Apple Inc." in html
    assert '<span class="code">AAPL</span>' in html


def test_single_stock_dashboard_prefers_parenthesized_numeric_code_after_st_prefix():
    html = build_share_image_html(
        """# 2026-07-31 决策仪表盘

## 🟡 *ST 海越 (600387)

> 2026-07-31 15:30 | 评分：**62** | 中性

### 核心结论

**观望**：等待趋势进一步确认。
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster stock"' in html
    assert "个股决策卡" in html
    assert "ST 海越" in html
    assert '<span class="code">600387</span>' in html


def test_single_stock_dashboard_uses_trailing_parenthesized_us_ticker():
    html = build_share_image_html(
        """# 2026-07-31 Decision Dashboard

## IBM (IBM)

> 2026-07-31 15:30 | Score: **64** | Neutral

### Core Conclusion

**Hold**: Wait for a clearer breakout.
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster stock"' in html
    assert "Stock decision card" in html
    assert "IBM" in html
    assert '<span class="code">IBM</span>' in html


def test_single_stock_dashboard_uses_numeric_code_prefix_with_trailing_name():
    html = build_share_image_html(
        """# 2026-07-31 决策仪表盘

## 600519 贵州茅台

> 2026-07-31 15:30 | 评分：**72** | 看多

### 核心结论

**买入**：回调到支撑区可分批关注。
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster stock"' in html
    assert "个股决策卡" in html
    assert "贵州茅台" in html
    assert '<span class="code">600519</span>' in html


def test_multi_stock_daily_report_uses_generic_poster_and_keeps_all_stocks():
    html = build_share_image_html(
        """# 股票分析报告

## 📈 股票分析报告

### 贵州茅台 (600519)

**操作建议：买入** | **评分：72**

### 宁德时代 (300750)

**操作建议：观望** | **评分：61**
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster dashboard"' in html
    assert "贵州茅台" in html
    assert "宁德时代" in html
    assert '<span class="code">' not in html


def test_brief_aggregate_report_without_single_stock_heading_uses_generic_poster():
    html = build_share_image_html(
        """# Stock Analysis Report

## Summary

- Buy leaders on pullbacks.
- Avoid weak late-cycle names.
""",
        generated_on=date(2026, 7, 31),
    )

    assert 'class="poster dashboard"' in html
    assert "Summary" in html
    assert "Buy leaders on pullbacks." in html


def test_desktop_backend_build_scripts_bundle_share_image_assets():
    root = Path(__file__).resolve().parents[1]
    for relative_path in ("scripts/build-backend.ps1", "scripts/build-backend-macos.sh"):
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "src/assets/share_image" in content
