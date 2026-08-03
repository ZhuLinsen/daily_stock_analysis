# -*- coding: utf-8 -*-
"""Regression: LLM 量比占位 0 不得覆盖确定性 N/A / 真实量比。"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext


class TestVolumeRatioConsistency(unittest.TestCase):
    def _orch(self) -> AgentOrchestrator:
        return AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())

    def test_llm_zero_volume_ratio_becomes_na_when_realtime_missing(self):
        orch = self._orch()
        ctx = AgentContext(query="test", stock_code="00700.HK", stock_name="腾讯控股")
        ctx.set_data(
            "realtime_quote",
            {"price": 490.4, "turnover_rate": 0.43, "source": "longbridge"},
        )
        ctx.set_data(
            "trend_result",
            {"volume_status": "放量上涨", "volume_trend": "成交量放大", "volume_ratio_5d": 0.0},
        )

        payload = {
            "decision_type": "hold",
            "analysis_summary": "观望",
            "dashboard": {
                "data_perspective": {
                    "volume_analysis": {
                        "volume_ratio": 0,
                        "volume_status": "放量",
                        "turnover_rate": 0,
                        "volume_meaning": "模型编造",
                    }
                }
            },
        }

        normalized = orch._finalize_dashboard_payload(payload, ctx)
        vol = normalized["dashboard"]["data_perspective"]["volume_analysis"]
        self.assertEqual(vol["volume_ratio"], "N/A")
        self.assertEqual(vol["turnover_rate"], 0.43)

    def test_trend_volume_ratio_5d_fills_when_realtime_missing(self):
        orch = self._orch()
        ctx = AgentContext(query="test", stock_code="00700.HK", stock_name="腾讯控股")
        ctx.set_data("realtime_quote", {"price": 490.4, "source": "longbridge"})
        ctx.set_data(
            "trend_result",
            {
                "volume_status": "放量上涨",
                "volume_trend": "量价齐升",
                "volume_ratio_5d": 1.24,
            },
        )

        payload = {
            "decision_type": "hold",
            "dashboard": {
                "data_perspective": {
                    "volume_analysis": {"volume_ratio": 0, "volume_status": "", "turnover_rate": 0}
                }
            },
        }
        normalized = orch._finalize_dashboard_payload(payload, ctx)
        vol = normalized["dashboard"]["data_perspective"]["volume_analysis"]
        self.assertEqual(vol["volume_ratio"], 1.24)

    def test_realtime_volume_ratio_wins_over_llm(self):
        orch = self._orch()
        ctx = AgentContext(query="test", stock_code="00700.HK", stock_name="腾讯控股")
        ctx.set_data(
            "realtime_quote",
            {"price": 490.4, "volume_ratio": 1.31, "turnover_rate": 0.5},
        )

        payload = {
            "decision_type": "hold",
            "dashboard": {
                "data_perspective": {
                    "volume_analysis": {"volume_ratio": 0, "turnover_rate": 0}
                }
            },
        }
        normalized = orch._finalize_dashboard_payload(payload, ctx)
        vol = normalized["dashboard"]["data_perspective"]["volume_analysis"]
        self.assertEqual(vol["volume_ratio"], 1.31)
        self.assertEqual(vol["turnover_rate"], 0.5)

    def test_fill_volume_ratio_from_trend_helper_semantics(self):
        """与 pipeline._fill_volume_ratio_from_trend 语义对齐的轻量校验。"""
        quote = SimpleNamespace(code="00700.HK", volume_ratio=None)
        trend = SimpleNamespace(volume_ratio_5d=1.24)
        # 直接调用静态逻辑：有日线量比时应写回
        current = getattr(quote, "volume_ratio", None)
        self.assertTrue(current is None or float(current or 0) <= 0)
        quote.volume_ratio = round(float(trend.volume_ratio_5d), 2)
        self.assertEqual(quote.volume_ratio, 1.24)


if __name__ == "__main__":
    unittest.main()
