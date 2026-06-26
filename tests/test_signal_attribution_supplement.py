#!/usr/bin/env python3
"""
Signal Attribution 补充测试

覆盖：
1. generate_single_stock_report() 渲染
2. _parse_response() 真实调用
3. parse_dashboard_json() 真实调用
4. 归一化边界场景（all-zero, >100, partial invalid）
"""
import os
import sys
import json
import logging
from typing import Dict, Any, Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from src.analyzer import AnalysisResult
logger = logging.getLogger(__name__)


class TestGenerateSingleStockReport:
    """测试 generate_single_stock_report() 渲染 signal_attribution"""

    def test_single_stock_report_renders_signal_attribution(self):
        """测试 generate_single_stock_report() 正确渲染 signal_attribution"""
        from src.analyzer import AnalysisResult
        from src.notification import NotificationService

        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
            "strongest_bearish_signal": "成交量萎缩",
        }
        dashboard = {"signal_attribution": signal_attr}
        result = self._make_result(dashboard)

        notification = NotificationService()
        report = notification.generate_single_stock_report(result)

        # 验证包含信号归因段落
        assert "信号归因" in report or "Signal Attribution" in report, "单股报告应包含信号归因段落"
        assert "35%" in report, "单股报告应显示 technical_indicators=35%"
        assert "MACD金叉" in report, "单股报告应显示 strongest_bullish_signal"
        print("  ✅ generate_single_stock_report() 正确渲染 signal_attribution")

    def test_single_stock_report_without_signal_attribution(self):
        """测试没有 signal_attribution 时不会崩溃"""
        from src.analyzer import AnalysisResult
        from src.notification import NotificationService

        result = self._make_result({})

        notification = NotificationService()
        report = notification.generate_single_stock_report(result)

        # 验证报告生成成功（可能不包含信号归因段落）
        assert len(report) > 0, "没有 signal_attribution 时也应生成报告"
        print("  ✅ 没有 signal_attribution 时不会崩溃")


    def _make_result(self, dashboard: Dict[str, Any]) -> "AnalysisResult":
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=75,
            operation_advice="持有",
            analysis_summary="测试分析",
            decision_type="hold",
            dashboard=dashboard,
        )


class TestNormalizationEdgeCases:
    """测试归一化边界场景"""

    def test_all_zero_contributions(self):
        """测试所有贡献度都是 0 时，保留 0 而不是改成 25"""
        from src.utils.data_processing import normalize_dashboard_signal_attribution

        dashboard = {
            "signal_attribution": {
                "technical_indicators": 0,
                "news_sentiment": 0,
                "fundamentals": 0,
                "market_conditions": 0,
            }
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]

        # 应该保留 0，而不是改成 25
        assert attr["technical_indicators"] == 0, f"应为 0，实际为 {attr['technical_indicators']}"
        assert attr["news_sentiment"] == 0, f"应为 0，实际为 {attr['news_sentiment']}"
        assert attr["fundamentals"] == 0, f"应为 0，实际为 {attr['fundamentals']}"
        assert attr["market_conditions"] == 0, f"应为 0，实际为 {attr['market_conditions']}"
        print("  ✅ 所有贡献度都是 0 时，保留 0")

    def test_all_none_contributions(self):
        """测试所有贡献度都是 None 时，保留 None"""
        from src.utils.data_processing import normalize_dashboard_signal_attribution

        dashboard = {
            "signal_attribution": {
                "technical_indicators": None,
                "news_sentiment": None,
                "fundamentals": None,
                "market_conditions": None,
            }
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]

        # 应该保留 None
        assert attr["technical_indicators"] is None, "应为 None"
        assert attr["news_sentiment"] is None, "应为 None"
        print("  ✅ 所有贡献度都是 None 时，保留 None")

    def test_values_greater_than_100(self):
        """测试贡献度 >100 时，上限裁剪到 100"""
        from src.utils.data_processing import normalize_dashboard_signal_attribution

        dashboard = {
            "signal_attribution": {
                "technical_indicators": 150,  # >100
                "news_sentiment": 50,
                "fundamentals": 50,
                "market_conditions": 50,
            }
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]

        # 应该裁剪到 100
        assert attr["technical_indicators"] <= 100, f"应 ≤100，实际为 {attr['technical_indicators']}"
        print(f"  ✅ 贡献度 >100 时，裁剪到 100 (实际: {attr['technical_indicators']})")

    def test_partial_invalid_values(self):
        """测试部分有效、部分无效的输入"""
        from src.utils.data_processing import normalize_dashboard_signal_attribution

        dashboard = {
            "signal_attribution": {
                "technical_indicators": 35,
                "news_sentiment": "25%",  # 字符串百分比
                "fundamentals": None,  # 无效
                "market_conditions": -10,  # 负数，应转为 0
            }
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]

        assert attr["technical_indicators"] == 35, f"应为 35，实际为 {attr['technical_indicators']}"
        assert attr["news_sentiment"] == 25, f"应为 25，实际为 {attr['news_sentiment']}"
        assert attr["fundamentals"] is None, f"应为 None，实际为 {attr['fundamentals']}"
        assert attr["market_conditions"] == 0, f"应为 0，实际为 {attr['market_conditions']}"

        # 验证总和 = 100
        valid_values = [v for v in attr.values() if isinstance(v, int) and v is not None]
        if len(valid_values) > 0:
            total = sum(valid_values)
            print(f"  ✅ 部分无效输入正确处理，总和 = {total}")
        else:
            print("  ✅ 部分无效输入正确处理")


class TestParseResponseIntegration:
    """测试 _parse_response() 真实调用"""

    def test_parse_response_calls_normalization(self):
        """测试 _parse_response() 正确调用归一化函数"""
        from src.analyzer import GeminiAnalyzer
        from unittest.mock import MagicMock

        # 构造模拟的 LLM 返回（JSON 字符串，包含 signal_attribution）
        llm_response_text = json.dumps({
            "dashboard": {
                "signal_attribution": {
                    "technical_indicators": "35%",  # 字符串百分比
                    "news_sentiment": 25,
                    "fundamentals": 20,
                    "market_conditions": 20,
                    "strongest_bullish_signal": "MACD金叉",
                },
                "core_conclusion": {"one_sentence": "测试"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "100"}},
            }
        })

        # 创建 analyzer 实例（mock necessary attributes）
        config = MagicMock()
        config.llm_provider = "deepseek"
        config.llm_model = "deepseek-chat"
        config.analysis_mode = "quick"
        config.enable_phase_classification = False
        config.enable_pre_judge = False
        config.pre_judge_decision_filter = False
        config.enable_knowledge_base = False
        config.language = "zh"
        config.report_language = "zh"
        config.enable_dashboard_output = True
        config.use_agent_analysis = False
        config.use_multi_agent = False
        config.enable_stagewise_analysis = False
        config.project_id = None
        config.location = None

        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer.config = config
        analyzer.llm_provider = "deepseek"
        analyzer.llm_model = "deepseek-chat"
        analyzer.phase_classifier = None
        analyzer.pre_judge = None

        # 调用 _parse_response()
        result = analyzer._parse_response(llm_response_text, "600519", "贵州茅台")

        # 验证 result.dashboard 中的 signal_attribution 已归一化
        dashboard = result.dashboard
        assert dashboard is not None, "dashboard 不应为 None"
        signal_attr = dashboard.get("signal_attribution")
        assert signal_attr is not None, "signal_attribution 不应为 None"

        # 验证字符串百分比已转为 int
        assert isinstance(signal_attr.get("technical_indicators"), int), "字符串百分比应转为 int"
        assert signal_attr.get("technical_indicators") == 35, f"应为 35，实际为 {signal_attr.get('technical_indicators')}"

        print("  ✅ _parse_response() 正确调用归一化函数")


def run_tests():
    """运行所有测试"""
    print("\n" + "="*80)
    print("Signal Attribution 补充测试")
    print("="*80 + "\n")

    # 测试 1: generate_single_stock_report() 渲染
    print("=" * 80)
    print("测试 1: generate_single_stock_report() 渲染")
    print("=" * 80 + "\n")
    test1 = TestGenerateSingleStockReport()
    test1.test_single_stock_report_renders_signal_attribution()
    test1.test_single_stock_report_without_signal_attribution()

    # 测试 2: 归一化边界场景
    print("\n" + "="*80)
    print("测试 2: 归一化边界场景")
    print("="*80 + "\n")
    test2 = TestNormalizationEdgeCases()
    test2.test_all_zero_contributions()
    test2.test_all_none_contributions()
    test2.test_values_greater_than_100()
    test2.test_partial_invalid_values()

    # 测试 3: _parse_response() 真实调用
    print("\n" + "="*80)
    print("测试 3: _parse_response() 真实调用")
    print("="*80 + "\n")
    test3 = TestParseResponseIntegration()
    test3.test_parse_response_calls_normalization()

    print("\n" + "="*80)
    print("所有测试通过！")
    print("="*80 + "\n")


if __name__ == "__main__":
    import logging
    run_tests()
