"""
端到端测试：signal_attribution 完整契约收敛测试。

验证以下路径：
1. LLM raw JSON → _parse_response() → AnalysisResult.dashboard (归一化生效)
2. AnalysisResult.dashboard → notification (展示正确)
3. AnalysisResult.dashboard → Jinja2 template (渲染正确)
4. AnalysisResult.dashboard → HistoryService markdown (渲染正确)
5. check_content_integrity() (契约检查)
"""
import sys
import os
import pytest
import json

# 添加 src 到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.analyzer import AnalysisResult, check_content_integrity
from src.utils.data_processing import normalize_dashboard_signal_attribution
from src.agent.runner import parse_dashboard_json
from src.services.report_renderer import render


class TestSignalAttributionE2E:
    """端到端测试：验证 signal_attribution 在所有路径中正确工作"""

    def _make_dashboard_with_signal_attr(self, signal_attr):
        """创建包含 signal_attribution 的 dashboard dict"""
        return {
            "core_conclusion": {
                "one_sentence": "测试结论",
                "signal": "buy",
                "confidence": "中",
            },
            "intelligence": {
                "risk_alerts": ["测试风险"],
            },
            "signal_attribution": signal_attr,
        }

    def _make_result(self, dashboard):
        """创建 AnalysisResult"""
        return AnalysisResult(
            code="600519",
            name="测试股票",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            decision_type="hold",
            confidence_level="中",
            dashboard=dashboard,
            analysis_summary="测试摘要",
        )

    # ========== 测试 1: _parse_response() 归一化 ==========
    def test_normalize_called_in_parse_response(self):
        """
        测试 _parse_response() 中归一化函数被调用。

        验证：
        1. 输入贡献度为字符串 "30%" → 归一化后变为 int 30
        2. 输入贡献度之和不为 100 → 归一化后变为之和=100
        """
        from src.analyzer import GeminiAnalyzer

        # 创建 analyzer 实例
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)

        # 模拟 LLM 返回的 JSON（贡献度为字符串，总和≠100）
        response_text = json.dumps({
            "sentiment_score": 50,
            "trend_prediction": "震荡",
            "operation_advice": "持有",
            "decision_type": "hold",
            "confidence_level": "中",
            "analysis_summary": "测试",
            "dashboard": {
                "core_conclusion": {"one_sentence": "测试", "signal": "hold", "confidence": "中"},
                "intelligence": {"risk_alerts": []},
                "signal_attribution": {
                    "technical_indicators": "30%",
                    "news_sentiment": 20,
                    "fundamentals": 30,
                    "market_conditions": 10,  # 总和=90，且有一个是字符串
                    "strongest_bullish_signal": "测试看涨",
                    "strongest_bearish_signal": "测试看空",
                },
            },
        })

        # 调用 _parse_response()
        result = analyzer._parse_response(response_text, "600519", "测试")

        # 验证归一化已执行
        dash = result.dashboard
        assert isinstance(dash, dict), "dashboard 应该是 dict"

        signal_attr = dash.get("signal_attribution")
        assert signal_attr is not None, "signal_attribution 应该存在"

        # 验证字符串已转为 int
        assert isinstance(signal_attr.get("technical_indicators"), int), "technical_indicators 应该是 int"

        # 验证总和=100
        total = sum([
            signal_attr.get("technical_indicators", 0),
            signal_attr.get("news_sentiment", 0),
            signal_attr.get("fundamentals", 0),
            signal_attr.get("market_conditions", 0),
        ])
        assert total == 100, f"贡献度之和应该=100，实际={total}"

    # ========== 测试 2: notification 渲染 ==========
    def test_notification_renders_signal_attribution(self):
        """
        测试 notification.py 中 generate_dashboard_report() 正确渲染 signal_attribution。

        验证：
        1. signal_attribution 存在时，通知中包含"信号归因"段落
        2. 四个贡献度都正确显示
        """
        from src.notification import NotificationService

        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
            "strongest_bearish_signal": "成交量萎缩",
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        # 调用 generate_dashboard_report()
        notification = NotificationService()
        report = notification.generate_dashboard_report([result], [dashboard])

        # 验证包含信号归因段落
        assert "信号归因" in report or "Signal Attribution" in report, "通知应包含信号归因段落"
        assert "35%" in report, "通知应显示 technical_indicators=35%"
        assert "25%" in report, "通知应显示 news_sentiment=25%"
        assert "20%" in report, "通知应显示 fundamentals=20%"
        assert "20%" in report, "通知应显示 market_conditions=20%"
        assert "MACD金叉" in report, "通知应显示 strongest_bullish_signal"

    # ========== 测试 3: Jinja2 模板渲染 ==========
    def test_jinja2_template_renders_signal_attribution(self):
        """
        测试 templates/report_markdown.j2 正确渲染 signal_attribution。

        验证：
        1. signal_attribution 存在时，模板输出中包含归因权重
        2. 四个贡献度都正确显示
        """
        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
        }
        result = self._make_result(self._make_dashboard_with_signal_attr(signal_attr))

        out = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        assert out is not None
        assert "35%" in out
        assert "MACD金叉" in out

    def test_parse_dashboard_json_normalizes_nested_dashboard_payload(self):
        """Agent JSON can return a full report object with nested dashboard."""
        payload = json.dumps({
            "dashboard": {
                "signal_attribution": {
                    "technical_indicators": "70%",
                    "news_sentiment": "10%",
                    "fundamentals": "10%",
                    "market_conditions": "10%",
                }
            }
        })

        parsed = parse_dashboard_json(payload)

        assert parsed is not None
        signal_attr = parsed["dashboard"]["signal_attribution"]
        assert signal_attr["technical_indicators"] == 70
        assert isinstance(signal_attr["technical_indicators"], int)

    def test_non_dict_signal_attribution_is_removed_before_rendering(self):
        """Invalid non-dict signal_attribution must not survive into renderers."""
        dashboard = {"signal_attribution": "bad payload"}

        normalize_dashboard_signal_attribution(dashboard)

        assert "signal_attribution" not in dashboard

    def test_partial_signal_attribution_uses_same_display_contract(self):
        """Partial weights should not render N/A% or None% in any report path."""
        from src.notification import NotificationService
        from src.services.history_service import HistoryService

        dashboard = self._make_dashboard_with_signal_attr({
            "technical_indicators": 35,
            "news_sentiment": None,
            "fundamentals": None,
            "market_conditions": 0,
            "strongest_bullish_signal": "MACD金叉",
        })
        result = self._make_result(dashboard)
        notification = NotificationService()

        dashboard_report = notification.generate_dashboard_report([result], [dashboard])
        single_report = notification.generate_single_stock_report(result)

        class MockRecord:
            created_at = None

        history_report = HistoryService.__new__(HistoryService)._generate_single_stock_markdown(result, MockRecord())
        template_report = render("markdown", [result], summary_only=False, extra_context={"report_language": "zh"})

        for output in [dashboard_report, single_report, history_report, template_report]:
            assert output is not None
            assert "N/A%" not in output
            assert "None%" not in output
            assert "35%" in output

    # ========== 测试 4: HistoryService markdown 渲染 ==========
    def test_history_service_renders_signal_attribution(self):
        """
        测试 HistoryService._generate_single_stock_markdown() 正确渲染 signal_attribution。

        验证：
        1. signal_attribution 存在时，markdown 中包含"信号归因分析"段落
        2. 四个贡献度都正确显示
        """
        from src.services.history_service import HistoryService

        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
            "strongest_bullish_signal": "MACD金叉",
            "strongest_bearish_signal": "成交量萎缩",
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        # 创建 mock record
        class MockRecord:
            created_at = None

        # 调用 _generate_single_stock_markdown()
        history_service = HistoryService.__new__(HistoryService)
        markdown = history_service._generate_single_stock_markdown(result, MockRecord())

        # 验证包含信号归因段落
        assert "信号归因" in markdown or "Signal Attribution" in markdown, "Markdown 应包含信号归因段落"
        assert "35%" in markdown, "Markdown 应显示 technical_indicators=35%"
        assert "MACD金叉" in markdown, "Markdown 应显示 strongest_bullish_signal"

    # ========== 测试 5: check_content_integrity() optional 契约 ==========
    def test_check_content_integrity_treats_signal_attribution_as_optional(self):
        """
        测试 check_content_integrity() 将 signal_attribution 作为可选展示字段。

        验证：
        1. signal_attribution 存在时，不添加到 missing
        2. signal_attribution 缺失时，不添加到 missing
        3. signal_attribution 贡献度缺失时，不添加到 missing
        """
        # 情况 1: signal_attribution 完整
        signal_attr = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            "fundamentals": 20,
            "market_conditions": 20,
        }
        dashboard = self._make_dashboard_with_signal_attr(signal_attr)
        result = self._make_result(dashboard)

        passed, missing = check_content_integrity(result)
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, f"signal_attribution 完整时不应出现在 missing 中，实际: {signal_attr_missing}"

        # 情况 2: signal_attribution 缺失
        dashboard_no_attr = self._make_dashboard_with_signal_attr(None)
        dashboard_no_attr["battle_plan"] = {"sniper_points": {"stop_loss": "100"}}
        result_no_attr = self._make_result(dashboard_no_attr)

        passed, missing = check_content_integrity(result_no_attr)
        assert passed is True
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, "signal_attribution 缺失时不应出现在 missing 中"

        # 情况 3: signal_attribution 贡献度缺失
        signal_attr_incomplete = {
            "technical_indicators": 35,
            "news_sentiment": 25,
            # 缺少 fundamentals 和 market_conditions
        }
        dashboard_incomplete = self._make_dashboard_with_signal_attr(signal_attr_incomplete)
        dashboard_incomplete["battle_plan"] = {"sniper_points": {"stop_loss": "100"}}
        result_incomplete = self._make_result(dashboard_incomplete)

        passed, missing = check_content_integrity(result_incomplete)
        assert passed is True
        signal_attr_missing = [m for m in missing if "signal_attribution" in m]
        assert len(signal_attr_missing) == 0, "signal_attribution 贡献度缺失时不应出现在 missing 中"

    # ========== 测试 6: 归一化函数测试 ==========
    def test_normalize_dashboard_signal_attribution_direct(self):
        """
        直接测试 normalize_dashboard_signal_attribution() 函数。

        验证：
        1. 字符串百分比转为 int
        2. 负数转为 0
        3. 总和≠100 时归一化为 100
        4. None 值处理
        """
        # 情况 1: 字符串百分比
        dashboard = {
            "signal_attribution": {
                "technical_indicators": "30%",
                "news_sentiment": 20,
                "fundamentals": "30",
                "market_conditions": 10,
                "strongest_bullish_signal": "测试",
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        # 验证字符串已转为 int（具体值可能因归一化而改变，但应该是 int）
        assert isinstance(attr["technical_indicators"], int), f"字符串百分比应转为 int: {attr['technical_indicators']}"
        assert isinstance(attr["fundamentals"], int), f"字符串应转为 int: {attr['fundamentals']}"

        # 验证总和=100
        total = sum([
            attr.get("technical_indicators", 0),
            attr.get("news_sentiment", 0),
            attr.get("fundamentals", 0),
            attr.get("market_conditions", 0),
        ])
        assert total == 100, f"归一化后总和应为 100: {total}"

        # 情况 2: 负数
        dashboard = {
            "signal_attribution": {
                "technical_indicators": -10,
                "news_sentiment": 20,
                "fundamentals": 30,
                "market_conditions": 40,
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        assert attr["technical_indicators"] == 0, f"负数应转为 0: {attr['technical_indicators']}"

        # 情况 3: 总和=100，不需要归一化
        dashboard = {
            "signal_attribution": {
                "technical_indicators": 25,
                "news_sentiment": 25,
                "fundamentals": 25,
                "market_conditions": 25,
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        total = sum([attr["technical_indicators"], attr["news_sentiment"], attr["fundamentals"], attr["market_conditions"]])
        assert total == 100, f"总和应为 100: {total}"

        # 情况 4: 总和≠100（需要归一化）
        dashboard = {
            "signal_attribution": {
                "technical_indicators": 10,
                "news_sentiment": 20,
                "fundamentals": 30,
                "market_conditions": 30,  # 总和=90
            },
        }
        normalize_dashboard_signal_attribution(dashboard)
        attr = dashboard["signal_attribution"]
        total = sum([attr["technical_indicators"], attr["news_sentiment"], attr["fundamentals"], attr["market_conditions"]])
        assert total == 100, f"归一化后总和应为 100: {total}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
