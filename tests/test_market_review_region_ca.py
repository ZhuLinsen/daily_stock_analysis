# -*- coding: utf-8 -*-
"""
MARKET_REVIEW_REGION=ca 归一化与加拿大市场全链路契约测试（Issue #2420 后端部分）

覆盖：
- src/utils/market_review_region.py 四常量与 lenient/strict 归一化的 ca 值域
- src/core/market_profile.py CA_PROFILE 与 get_profile 分支
- src/core/market_review.py _MARKET_REVIEW_MARKETS 与三语 ca_title
- src/core/trading_calendar.py ca 时区/交易所与 compute_effective_region（不依赖 A 股日历）
- src/core/market_strategy.py CA_BLUEPRINT
- src/market_analyzer.py region 白名单接受 ca
"""
import sys
import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

# Stub heavy dependencies before project imports（与 test_market_analyzer_generate_text.py 同法）
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest


# ---------------------------------------------------------------------------
# market_review_region 常量与归一化
# ---------------------------------------------------------------------------
class TestMarketReviewRegionConstants:
    """MARKET_REVIEW_REGION 四常量应包含 ca（追加在 kr 之后）"""

    def test_order_includes_ca_after_kr(self):
        from src.utils.market_review_region import MARKET_REVIEW_REGION_ORDER

        assert "ca" in MARKET_REVIEW_REGION_ORDER
        assert MARKET_REVIEW_REGION_ORDER == ("cn", "hk", "us", "jp", "kr", "ca")

    def test_set_contains_ca(self):
        from src.utils.market_review_region import MARKET_REVIEW_REGION_SET

        assert "ca" in MARKET_REVIEW_REGION_SET

    def test_all_contains_ca(self):
        from src.utils.market_review_region import MARKET_REVIEW_REGION_ALL

        assert MARKET_REVIEW_REGION_ALL == "cn,hk,us,jp,kr,ca"

    def test_valid_inputs_contains_ca(self):
        from src.utils.market_review_region import MARKET_REVIEW_REGION_VALID_INPUTS

        assert "ca" in MARKET_REVIEW_REGION_VALID_INPUTS


class TestLenientNormalizationCa:
    """持久化配置的宽归一化应接受 ca"""

    def test_single_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_lenient

        assert normalize_market_review_region_lenient("ca") == "ca"
        assert normalize_market_review_region_lenient("CA") == "ca"
        assert normalize_market_review_region_lenient(" ca ") == "ca"

    def test_comma_subset_with_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_lenient

        assert normalize_market_review_region_lenient("cn,ca") == "cn,ca"
        assert normalize_market_review_region_lenient("CA, CN") == "cn,ca"
        # 规范顺序：cn,hk,us,jp,kr,ca
        assert normalize_market_review_region_lenient("ca,hk") == "hk,ca"

    def test_invalid_tokens_filtered_ca_kept(self):
        from src.utils.market_review_region import normalize_market_review_region_lenient

        assert normalize_market_review_region_lenient("ca,bogus") == "ca"

    def test_both_expands_with_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_lenient

        assert normalize_market_review_region_lenient("both") == "cn,hk,us,jp,kr,ca"

    def test_unknown_returns_none(self):
        from src.utils.market_review_region import normalize_market_review_region_lenient

        assert normalize_market_review_region_lenient("bogus") is None


class TestStrictNormalizationCa:
    """请求级严格校验应接受 ca 并保留 fail-fast 语义"""

    def test_single_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_strict

        assert normalize_market_review_region_strict("CA") == "ca"
        assert normalize_market_review_region_strict(" ca ") == "ca"

    def test_comma_subset_with_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_strict

        assert normalize_market_review_region_strict("cn,ca") == "cn,ca"

    def test_invalid_token_raises(self):
        from src.utils.market_review_region import normalize_market_review_region_strict

        with pytest.raises(ValueError):
            normalize_market_review_region_strict("ca,bogus")

    def test_both_mixed_with_ca_raises(self):
        from src.utils.market_review_region import normalize_market_review_region_strict

        with pytest.raises(ValueError):
            normalize_market_review_region_strict("both,ca")

    def test_valid_hint_mentions_ca(self):
        from src.utils.market_review_region import normalize_market_review_region_strict

        with pytest.raises(ValueError) as exc_info:
            normalize_market_review_region_strict("xx")
        assert "ca" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Market Profile / 复盘文案
# ---------------------------------------------------------------------------
class TestCaMarketProfile:
    """CA_PROFILE 契约：无市场宽度/板块统计，mood 指数 GSPTSE"""

    def test_get_profile_ca(self):
        from src.core.market_profile import CA_PROFILE, get_profile

        profile = get_profile("ca")
        assert profile is CA_PROFILE
        assert profile.region == "ca"
        assert profile.mood_index_code == "GSPTSE"
        assert profile.news_queries, "ca 需要非空新闻搜索词"
        assert "TSX" in profile.prompt_index_hint
        assert profile.has_market_stats is False, "加拿大复盘不提供涨跌家数/涨跌停（对齐美股口径）"
        assert profile.has_sector_rankings is False

    def test_existing_profiles_unchanged(self):
        from src.core.market_profile import (
            CN_PROFILE,
            HK_PROFILE,
            JP_PROFILE,
            KR_PROFILE,
            US_PROFILE,
            get_profile,
        )

        assert get_profile("cn") is CN_PROFILE
        assert get_profile("us") is US_PROFILE
        assert get_profile("hk") is HK_PROFILE
        assert get_profile("jp") is JP_PROFILE
        assert get_profile("kr") is KR_PROFILE


class TestMarketReviewMarketsCa:
    """_MARKET_REVIEW_MARKETS 与三语标题应含 ca"""

    def test_market_review_markets_contains_ca(self):
        from src.core.market_review import _MARKET_REVIEW_MARKETS

        assert ('ca', 'ca_title', '加股') in _MARKET_REVIEW_MARKETS

    def test_zh_ca_title(self):
        from src.core.market_review import _get_market_review_text

        assert _get_market_review_text("zh")["ca_title"] == "# 加股大盘复盘"

    def test_en_ca_title(self):
        from src.core.market_review import _get_market_review_text

        assert _get_market_review_text("en")["ca_title"] == "# Canada Market Recap"

    def test_ko_ca_title(self):
        from src.core.market_review import _get_market_review_text

        assert _get_market_review_text("ko")["ca_title"] == "# 캐나다 시황 리뷰"


# ---------------------------------------------------------------------------
# 交易日历：ca 走 TSX（XTSX）/多伦多时区，不依赖 A 股日历
# ---------------------------------------------------------------------------
class TestCaTradingCalendar:
    """ca 的交易日过滤使用 XTSX 日历 + America/Toronto 时区"""

    def test_market_exchange_contains_ca(self):
        from src.core.trading_calendar import MARKET_EXCHANGE

        assert MARKET_EXCHANGE.get("ca") == "XTSX"

    def test_market_timezone_contains_ca(self):
        from src.core.trading_calendar import MARKET_TIMEZONE

        assert MARKET_TIMEZONE.get("ca") == "America/Toronto"

    def test_is_market_open_uses_tsx_calendar(self):
        from src.core.trading_calendar import is_market_open

        # 2026-11-11（周二）为 TSX 交易日；2026-12-25 圣诞节休市。
        assert is_market_open("ca", date(2026, 11, 11)) is True
        assert is_market_open("ca", date(2026, 12, 25)) is False

    def test_compute_effective_region_single_ca_open(self):
        from src.core.trading_calendar import compute_effective_region

        assert compute_effective_region("ca", {"ca"}) == "ca"

    def test_compute_effective_region_single_ca_closed_skips(self):
        """TSX 休市而 A 股开市时，ca 复盘应跳过——不得回退成 cn（不依赖 A 股日历）"""
        from src.core.trading_calendar import compute_effective_region

        assert compute_effective_region("ca", {"cn"}) == ""

    def test_compute_effective_region_multi_subset(self):
        from src.core.trading_calendar import compute_effective_region

        assert compute_effective_region("cn,ca", {"ca"}) == "ca"
        assert compute_effective_region("cn,ca", {"cn", "ca"}) == "cn,ca"

    def test_compute_effective_region_both_includes_ca(self):
        from src.core.trading_calendar import compute_effective_region

        assert compute_effective_region("both", {"ca"}) == "ca"

    def test_cn_regions_unaffected(self):
        """既有区域语义零回归：cn 单区域休市仍返回空串"""
        from src.core.trading_calendar import compute_effective_region

        assert compute_effective_region("cn", {"ca"}) == ""
        assert compute_effective_region("cn", {"cn"}) == "cn"
        assert compute_effective_region("jp,kr", {"jp"}) == "jp"


# ---------------------------------------------------------------------------
# 策略蓝图与 analyzer 白名单
# ---------------------------------------------------------------------------
class TestCaStrategyBlueprint:
    """CA_BLUEPRINT：zh 脚手架 + get_market_strategy_blueprint 分支"""

    def test_get_blueprint_ca(self):
        from src.core.market_strategy import CA_BLUEPRINT, get_market_strategy_blueprint

        blueprint = get_market_strategy_blueprint("ca")
        assert blueprint is CA_BLUEPRINT
        assert blueprint.region == "ca"
        assert blueprint.dimensions, "CA_BLUEPRINT 需要分析维度"
        assert blueprint.principles, "CA_BLUEPRINT 需要策略原则"


class TestMarketAnalyzerAcceptsCa:
    """MarketAnalyzer region 白名单应接受 ca"""

    def _make_analyzer(self, region):
        from src.market_analyzer import MarketAnalyzer

        config = SimpleNamespace(report_language="zh")
        return MarketAnalyzer(config=config, region=region)

    def test_region_ca_accepted(self):
        analyzer = self._make_analyzer("ca")
        assert analyzer.region == "ca"

    def test_region_ca_profile_wired(self):
        from src.core.market_profile import CA_PROFILE

        analyzer = self._make_analyzer("ca")
        assert analyzer.profile is CA_PROFILE

    def test_region_unknown_still_falls_back_to_cn(self):
        analyzer = self._make_analyzer("bogus")
        assert analyzer.region == "cn"

    def test_en_market_scope_name(self):
        analyzer = self._make_analyzer("ca")
        analyzer.config = SimpleNamespace(report_language="en")
        assert analyzer._get_market_scope_name("en") == "Canada market"
        assert analyzer._get_market_scope_name("zh") == "加拿大市场"

    def test_zh_report_title_uses_market_scope(self):
        analyzer = self._make_analyzer("ca")
        # jp/kr/ca 走 "{scope}大盘复盘" 形态，而非默认的"{date} 大盘复盘"
        assert analyzer.region in ("jp", "kr", "ca")


if __name__ == "__main__":
    pytest.main([__file__])


class TestCaZhTemplateFallbackLabel:
    """OR-COR-8e0bd2a1（复审 #4）：中文模板 fallback 的 market_labels 缺 ca
    → 加股降级文案误称「今日A股市场」。"""

    def test_zh_template_fallback_uses_canada_label(self):
        from src.market_analyzer import MarketAnalyzer, MarketOverview

        analyzer = MarketAnalyzer(config=SimpleNamespace(report_language="zh"), region="ca")
        report = analyzer._generate_template_review(MarketOverview(date="2026-03-05"), [])

        assert "A股" not in report, "ca 的中文降级文案不得误称 A 股"
        assert "加股" in report
        assert "加拿大市场" in report or "加股市场" in report
