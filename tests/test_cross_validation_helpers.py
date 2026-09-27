# -*- coding: utf-8 -*-
"""cross_validation_helpers 单测 —— 100% 覆盖。

注入 fake validator，覆盖：开关关/无 validator→None、正常 block 构建、
primary_readings 透传、单锚点异常隔离、summary 计数、_build_sources（iFinD 配置与否）。
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.cross_source_validator import AnchorReading, AnchorVerification  # noqa: E402
from src.agent.tools import cross_validation_helpers as h  # noqa: E402
from src.agent.tools.cross_validation_helpers import build_cross_validation_block  # noqa: E402


def _verification(field, confidence="high", value=1.0):
    return AnchorVerification(
        field=field, value=value, confidence=confidence,
        sources=("mx", "ifind"), agreed=True, discrepancy_pct=0.1,
    )


class _FakeValidator:
    def __init__(self, results, raise_on=None):
        self._results = results  # {field: AnchorVerification}
        self._raise_on = raise_on or set()
        self.calls = []

    def verify(self, code, field, period=None, primary_reading=None):
        self.calls.append((field, primary_reading))
        if field in self._raise_on:
            raise RuntimeError("boom")
        return self._results.get(field, _verification(field, "low", 0.0))


class TestBuildBlock(unittest.TestCase):
    def test_returns_none_when_no_validator(self):
        # validator=None + 开关关 → _get_validator() 返回 None → build 返回 None
        # 显式 patch config 强制开关关（隔离 .env 真实 key + switch=true 的环境）
        with patch("src.config.get_config") as gc:
            gc.return_value.deep_research_cross_validate = False
            h.reset_validator()
            self.assertIsNone(build_cross_validation_block("600519", ["pe_ratio"], validator=None))

    def test_returns_none_when_switch_off_no_injected_validator(self):
        # validator=None + 开关关 → _get_validator() 返回 None → build 走 line 88 return None
        with patch("src.config.get_config") as gc:
            gc.return_value.deep_research_cross_validate = False
            h.reset_validator()
            self.assertIsNone(build_cross_validation_block("600519", ["pe_ratio"]))

    def test_builds_block_with_fake_validator(self):
        v = _FakeValidator({"pe_ratio": _verification("pe_ratio", "high", 30.5)})
        block = build_cross_validation_block("600519", ["pe_ratio"], validator=v)
        self.assertIsNotNone(block)
        self.assertTrue(block["enabled"])
        self.assertEqual(block["anchors"]["pe_ratio"]["v"], 30.5)
        self.assertIn("1/1", block["summary"])

    def test_primary_readings_passed_through(self):
        v = _FakeValidator({"current_price": _verification("current_price")})
        primary = AnchorReading(source="realtime", value=100.0)
        build_cross_validation_block(
            "600519", ["current_price"],
            primary_readings={"current_price": primary}, validator=v)
        self.assertEqual(v.calls[0][1], primary)  # primary_reading 透传到 verify

    def test_exception_isolation(self):
        # pe_ratio 抛异常被跳过；pb_ratio 正常 → block 仍含 pb_ratio
        v = _FakeValidator(
            {"pb_ratio": _verification("pb_ratio", "high")},
            raise_on={"pe_ratio"})
        block = build_cross_validation_block("600519", ["pe_ratio", "pb_ratio"], validator=v)
        self.assertIsNotNone(block)
        self.assertNotIn("pe_ratio", block["anchors"])
        self.assertIn("pb_ratio", block["anchors"])
        self.assertIn("1/2", block["summary"])  # 只 pb 高

    def test_summary_counts_high_only(self):
        v = _FakeValidator({
            "pe_ratio": _verification("pe_ratio", "high"),
            "pb_ratio": _verification("pb_ratio", "low"),
        })
        block = build_cross_validation_block("600519", ["pe_ratio", "pb_ratio"], validator=v)
        self.assertIn("1/2", block["summary"])

    def test_empty_fields_returns_none(self):
        v = _FakeValidator({})
        self.assertIsNone(build_cross_validation_block("600519", [], validator=v))


class TestGetValidatorConfigGate(unittest.TestCase):
    def setUp(self):
        h.reset_validator()

    def tearDown(self):
        h.reset_validator()

    def test_get_validator_none_when_switch_off(self):
        with patch("src.config.get_config") as gc:
            gc.return_value.deep_research_cross_validate = False
            self.assertIsNone(h._get_validator())

    def test_get_validator_builds_and_caches_when_switch_on(self):
        with patch("src.config.get_config") as gc, \
             patch.object(h, "_build_sources", return_value=[object()]):
            gc.return_value.deep_research_cross_validate = True
            v1 = h._get_validator()
            self.assertIsNotNone(v1)
            v2 = h._get_validator()  # 缓存命中（不再重建）
            self.assertIs(v1, v2)

    def test_get_validator_none_when_no_sources(self):
        with patch("src.config.get_config") as gc, \
             patch.object(h, "_build_sources", return_value=[]):
            gc.return_value.deep_research_cross_validate = True
            self.assertIsNone(h._get_validator())

    def test_build_sources_ifind_optional(self):
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
        self.assertEqual(len(h._build_sources(_Cfg())), 1)

    def test_build_sources_with_ifind(self):
        class _Cfg:
            ifind_mcp_endpoint = "https://x"
            ifind_mcp_token = "t"
            ifind_mcp_timeout_seconds = 5.0
        self.assertEqual(len(h._build_sources(_Cfg())), 2)

    def test_build_sources_with_mx_mcp_disabled_without_key(self):
        """MX_MCP 装配 opt-in：开关 false 或缺 key 均不挂入（默认零回归）。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = False
            mx_mcp_api_key = "redacted"
            mx_mcp_endpoint = "https://x"
            mx_mcp_timeout_seconds = 30.0
        names = [s.name for s in h._build_sources(_Cfg())]
        self.assertNotIn("mx_mcp", names)

    def test_build_sources_with_mx_mcp_enabled(self):
        """MX_MCP 装配：开关 true 且 key 存在时挂入，name 标识明确。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = True
            mx_mcp_api_key = "redacted"
            mx_mcp_endpoint = "https://x"
            mx_mcp_timeout_seconds = 30.0
        sources = h._build_sources(_Cfg())
        names = [s.name for s in sources]
        self.assertIn("mx_mcp", names)
        # 第三源与第一/第二同列
        self.assertEqual(names[0], "mx")
        self.assertEqual(len(sources), 2)

    def test_build_sources_with_fuyao_disabled_without_key(self):
        """fuyao 装配 opt-in：开关 false 或缺 key 均不挂入（默认零回归）。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = False
            mx_mcp_api_key = None
            enable_fuyao = False
            fuyao_api_key = "redacted"
            fuyao_endpoint = "https://fuyao.example"
            fuyao_timeout_seconds = 30.0
        names = [s.name for s in h._build_sources(_Cfg())]
        self.assertNotIn("fuyao", names)

    def test_build_sources_with_fuyao_enabled_no_key(self):
        """fuyao enable=true 但 key 为空：不挂入（避免明面开启实际不可用）。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = False
            mx_mcp_api_key = None
            enable_fuyao = True
            fuyao_api_key = None
            fuyao_endpoint = "https://fuyao.example"
            fuyao_timeout_seconds = 30.0
        names = [s.name for s in h._build_sources(_Cfg())]
        self.assertNotIn("fuyao", names)

    def test_build_sources_with_fuyao_enabled(self):
        """fuyao 装配：开关 true 且 key 存在时挂入第 4 源，name 标识明确。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = False
            mx_mcp_api_key = None
            enable_fuyao = True
            fuyao_api_key = "redacted"
            fuyao_endpoint = "https://fuyao.example"
            fuyao_timeout_seconds = 30.0
        sources = h._build_sources(_Cfg())
        names = [s.name for s in sources]
        self.assertIn("fuyao", names)
        self.assertEqual(names[0], "mx")
        self.assertEqual(len(sources), 2)

    def test_build_sources_with_fuyao_and_choice_mcp(self):
        """fuyao 与 Choice MCP 同时开启：四源装配顺序为 mx / mx_mcp / fuyao。"""
        class _Cfg:
            ifind_mcp_endpoint = None
            ifind_mcp_token = None
            ifind_mcp_timeout_seconds = 8.0
            enable_mx_mcp = True
            mx_mcp_api_key = "redacted"
            mx_mcp_endpoint = "https://mx.example"
            mx_mcp_timeout_seconds = 30.0
            enable_fuyao = True
            fuyao_api_key = "redacted"
            fuyao_endpoint = "https://fuyao.example"
            fuyao_timeout_seconds = 30.0
        names = [s.name for s in h._build_sources(_Cfg())]
        self.assertEqual(names, ["mx", "mx_mcp", "fuyao"])


if __name__ == "__main__":
    unittest.main()
