# -*- coding: utf-8 -*-
"""fuyao_adapter 单测 —— 100% 覆盖（网络层 mocked）。

覆盖：
- ``_to_thscode``：A 股 6 位数字（按交易所字典）/ 港股 5 位 / 美股字母 / 后缀透传 / 非法。
- ``_map_period``：年报/Q4/Q3/Q2/Q1 + 半年报/三季度报 + 非法形态。
- ``_endpoint_for``：已知/未知字段。
- ``_parse_fuyao_response``：正常 / 业务错误 / 缺字段 / 畸形 JSON / 空 body。
- ``FuyaoResponse`` Pydantic strict + frozen。
- ``FuyaoFetcher``：available / 200 / 401 / 429 / 500 / timeout / 网络错误 / 业务错误码。
- ``FuyaoSource``：fail-open 矩阵 + 凭据脱敏。
"""

from __future__ import annotations

import json
import logging
import os
import unittest
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import requests
from pydantic import ValidationError

from data_provider.cross_source_validator import AnchorReading
from data_provider.fuyao_adapter import (
    FuyaoFetcher,
    FuyaoResponse,
    FuyaoSource,
    _endpoint_for,
    _map_period,
    _parse_fuyao_response,
    _to_thscode,
)


# ------------------------------------------------------------------
# 解析层单测：_to_thscode
# ------------------------------------------------------------------


class ToThscodeTests(unittest.TestCase):
    """_to_thscode 标的符号转换边界。"""

    def test_a_share_sh_main_board(self) -> None:
        self.assertEqual(_to_thscode("600519"), "600519.SH")

    def test_a_share_sh_star(self) -> None:
        self.assertEqual(_to_thscode("688981"), "688981.SH")

    def test_a_share_sh_b(self) -> None:
        self.assertEqual(_to_thscode("900901"), "900901.SH")

    def test_a_share_sz_main(self) -> None:
        self.assertEqual(_to_thscode("000001"), "000001.SZ")

    def test_a_share_sz_chinext(self) -> None:
        self.assertEqual(_to_thscode("300750"), "300750.SZ")

    def test_a_share_sz_b(self) -> None:
        self.assertEqual(_to_thscode("200002"), "200002.SZ")

    def test_a_share_bj_8_prefix(self) -> None:
        self.assertEqual(_to_thscode("830799"), "830799.BJ")

    def test_a_share_bj_4_prefix(self) -> None:
        self.assertEqual(_to_thscode("430047"), "430047.BJ")

    def test_hk_5_digit(self) -> None:
        self.assertEqual(_to_thscode("00700"), "00700.HK")

    def test_hk_passthrough(self) -> None:
        self.assertEqual(_to_thscode("00700.HK"), "00700.HK")

    def test_us_uppercase(self) -> None:
        self.assertEqual(_to_thscode("AAPL"), "AAPL.US")

    def test_us_lowercase_normalized(self) -> None:
        self.assertEqual(_to_thscode("aapl"), "AAPL.US")

    def test_us_passthrough(self) -> None:
        self.assertEqual(_to_thscode("AAPL.US"), "AAPL.US")

    def test_a_share_passthrough(self) -> None:
        self.assertEqual(_to_thscode("600519.SH"), "600519.SH")

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("")

    def test_whitespace_only_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("   ")

    def test_unknown_a_share_prefix_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("123456")  # 123 / 1 均不在字典中

    def test_invalid_suffix_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("600519.XX")

    def test_unsupported_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("6005A9")

    def test_too_long_us_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_thscode("TOOLONGTICKER")


# ------------------------------------------------------------------
# 解析层单测：_map_period
# ------------------------------------------------------------------


class MapPeriodTests(unittest.TestCase):
    """_map_period 用户可见 period → fuyao YYYY-N 编码。"""

    def test_annual_report(self) -> None:
        self.assertEqual(_map_period("2024年报"), "2024-4")

    def test_annual_report_full(self) -> None:
        self.assertEqual(_map_period("2024年年度报告"), "2024-4")

    def test_q4(self) -> None:
        self.assertEqual(_map_period("2024Q4"), "2024-4")

    def test_q3(self) -> None:
        self.assertEqual(_map_period("2024Q3"), "2024-3")

    def test_q3_full(self) -> None:
        self.assertEqual(_map_period("2024三季度"), "2024-3")

    def test_q3_with_quarter_word(self) -> None:
        self.assertEqual(_map_period("2024第三季度报告"), "2024-3")

    def test_q2(self) -> None:
        self.assertEqual(_map_period("2024Q2"), "2024-2")

    def test_half_year(self) -> None:
        self.assertEqual(_map_period("2024半年报"), "2024-2")

    def test_interim(self) -> None:
        self.assertEqual(_map_period("2024中期"), "2024-2")

    def test_q1(self) -> None:
        self.assertEqual(_map_period("2024Q1"), "2024-1")

    def test_q1_full(self) -> None:
        self.assertEqual(_map_period("2024一季度"), "2024-1")

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_map_period(None))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_map_period(""))

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(_map_period("foo"))

    def test_unsupported_year_format_returns_none(self) -> None:
        # "2024月度" 不在已知模式 → None
        self.assertIsNone(_map_period("2024月度"))


# ------------------------------------------------------------------
# 解析层单测：_endpoint_for
# ------------------------------------------------------------------


class EndpointForTests(unittest.TestCase):
    def test_known_field(self) -> None:
        spec = _endpoint_for("pe_ratio")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.path, "/v1/valuations/snapshot")
        self.assertEqual(spec.item_key, "pe_ttm")
        self.assertFalse(spec.needs_period)

    def test_period_field(self) -> None:
        spec = _endpoint_for("revenue")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(spec.needs_period)

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(_endpoint_for("not_a_real_field"))


# ------------------------------------------------------------------
# 解析层单测：_parse_fuyao_response
# ------------------------------------------------------------------


def _ok_envelope(item: dict[str, Any]) -> str:
    """构造合法 fuyao 响应包络。"""
    return json.dumps(
        {"code": 0, "message": "success", "request_id": "r-1", "data": {"items": [item]}},
        ensure_ascii=False,
    )


class ParseFuyaoResponseTests(unittest.TestCase):
    def test_normal_pe_ttm(self) -> None:
        raw = _ok_envelope(
            {"thscode": "600519.SH", "fields": {"pe_ttm": 25.3, "pb_mrq": 6.5}}
        )
        r = _parse_fuyao_response(raw, "pe_ratio", period=None)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r.source, "fuyao")
        self.assertAlmostEqual(r.value, 25.3)
        self.assertEqual(r.caliber, "TTM")
        self.assertIsNone(r.period)

    def test_period_field_with_period(self) -> None:
        raw = _ok_envelope(
            {"thscode": "600519.SH", "report": "2024-4", "fields": {"revenue": 1.7e11}}
        )
        r = _parse_fuyao_response(raw, "revenue", period="2024年报")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.value, 1.7e11)
        self.assertEqual(r.period, "2024年报")
        self.assertIsNone(r.caliber)

    def test_period_field_without_period_is_none(self) -> None:
        # _parse_fuyao_response 不强制 period 透传；period 透传由 fetcher 负责
        raw = _ok_envelope(
            {"thscode": "600519.SH", "fields": {"revenue": 1.7e11}}
        )
        r = _parse_fuyao_response(raw, "revenue", period=None)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertIsNone(r.period)

    def test_business_error_returns_none(self) -> None:
        raw = json.dumps({"code": 2001, "message": "unauth", "data": None})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_rate_limit_returns_none(self) -> None:
        raw = json.dumps({"code": 4001, "message": "rate limit", "data": None})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_empty_body_returns_none(self) -> None:
        self.assertIsNone(_parse_fuyao_response("", "pe_ratio", None))

    def test_invalid_json_returns_none(self) -> None:
        self.assertIsNone(_parse_fuyao_response("{not json", "pe_ratio", None))

    def test_missing_data_returns_none(self) -> None:
        raw = json.dumps({"code": 0, "message": "ok"})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_empty_items_returns_none(self) -> None:
        raw = json.dumps({"code": 0, "message": "ok", "data": {"items": []}})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_missing_field_returns_none(self) -> None:
        raw = _ok_envelope({"thscode": "600519.SH", "fields": {"pb_mrq": 6.5}})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_null_field_value_returns_none(self) -> None:
        raw = _ok_envelope({"thscode": "600519.SH", "fields": {"pe_ttm": None}})
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_null_fields_returns_none(self) -> None:
        """``{"fields": null}`` 显式 null：Pydantic strict 应拒绝字段，解析走 fail-open。"""
        raw = json.dumps(
            {"code": 0, "message": "ok", "data": {"items": [{"thscode": "600519.SH", "fields": None}]}}
        )
        self.assertIsNone(_parse_fuyao_response(raw, "pe_ratio", None))

    def test_unknown_field_returns_none(self) -> None:
        raw = _ok_envelope({"thscode": "600519.SH", "fields": {"x": 1.0}})
        self.assertIsNone(_parse_fuyao_response(raw, "not_a_real_field", None))

    def test_skips_invalid_item_continues(self) -> None:
        # 第一条 item 缺 thscode（被 Pydantic 拒绝），第二条合法
        raw = json.dumps(
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "items": [
                        {"fields": {"pe_ttm": 99}},  # 缺 thscode
                        {"thscode": "600519.SH", "fields": {"pe_ttm": 25.3}},
                    ]
                },
            }
        )
        r = _parse_fuyao_response(raw, "pe_ratio", None)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.value, 25.3)

    def test_string_value_parsed_via_safe_float(self) -> None:
        raw = _ok_envelope({"thscode": "600519.SH", "fields": {"pe_ttm": "25.3"}})
        r = _parse_fuyao_response(raw, "pe_ratio", None)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.value, 25.3)

    def test_cn_unit_value_parsed(self) -> None:
        # _safe_float 支持「万亿/亿/万」中文单位
        raw = _ok_envelope({"thscode": "600519.SH", "fields": {"total_mv": "1.5097万亿"}})
        r = _parse_fuyao_response(raw, "total_mv", None)
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.value, 1.5097e12, places=4)


# ------------------------------------------------------------------
# Pydantic schema 校验
# ------------------------------------------------------------------


class FuyaoResponseSchemaTests(unittest.TestCase):
    def test_strict_rejects_string_code(self) -> None:
        with self.assertRaises(ValidationError):
            FuyaoResponse.model_validate_json(json.dumps({"code": "0"}))

    def test_frozen_blocks_mutation(self) -> None:
        resp = FuyaoResponse.model_validate(json.loads(json.dumps({"code": 0})))
        with self.assertRaises(Exception):
            resp.code = 1  # type: ignore[misc]

    def test_extra_field_ignored(self) -> None:
        raw = json.dumps(
            {"code": 0, "message": "ok", "future_field": "x", "data": {"items": []}}
        )
        resp = FuyaoResponse.model_validate_json(raw)
        self.assertEqual(resp.code, 0)

    def test_missing_code_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FuyaoResponse.model_validate_json(json.dumps({"message": "ok"}))


# ------------------------------------------------------------------
# FuyaoFetcher 单测（mock requests.Session.post）
# ------------------------------------------------------------------


class _FakeResp:
    """requests.Response 替身。"""

    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} {self.text[:80]}")


class FuyaoFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        # 确保环境变量不污染（None 显式空串 → available=False）
        for key in ("FUYAO_ENDPOINT", "FUYAO_API_KEY"):
            os.environ.pop(key, None)

    def test_available_false_without_api_key(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="")
        self.assertFalse(f.available)

    def test_available_false_without_endpoint(self) -> None:
        f = FuyaoFetcher(endpoint="", api_key="k")
        self.assertFalse(f.available)

    def test_available_true_with_both(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertTrue(f.available)

    def test_endpoint_strips_trailing_slash(self) -> None:
        f = FuyaoFetcher(endpoint="https://x/", api_key="k")
        self.assertEqual(f._endpoint, "https://x")

    def test_api_key_stripped(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="  k  ")
        self.assertEqual(f._api_key, "k")

    def test_fetch_returns_none_when_not_available(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_returns_none_for_unknown_field(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "not_a_field"))

    def test_fetch_returns_none_for_unparseable_code(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("xyz", "pe_ratio"))

    def test_fetch_returns_none_for_period_field_without_period(self) -> None:
        f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "revenue"))

    def test_fetch_200_returns_anchor(self) -> None:
        raw = _ok_envelope(
            {"thscode": "600519.SH", "fields": {"pe_ttm": 25.3}}
        )
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(200, raw)
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k", timeout_seconds=5.0)
        r = f.fetch("600519", "pe_ratio")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r.source, "fuyao")
        self.assertAlmostEqual(r.value, 25.3)
        self.assertEqual(r.caliber, "TTM")
        # 验证 URL + payload + headers
        called = fake_session.post.call_args
        self.assertEqual(called.args[0], "https://x/v1/valuations/snapshot")
        self.assertEqual(called.kwargs["json"], {"thscode": "600519.SH"})
        self.assertEqual(
            called.kwargs["headers"]["Authorization"], "Bearer k"
        )

    def test_fetch_200_with_period(self) -> None:
        raw = _ok_envelope(
            {"thscode": "600519.SH", "report": "2024-4", "fields": {"revenue": 1.7e11}}
        )
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(200, raw)
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        r = f.fetch("600519", "revenue", period="2024年报")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.value, 1.7e11)
        self.assertEqual(r.period, "2024年报")
        called = fake_session.post.call_args
        self.assertEqual(
            called.kwargs["json"], {"thscode": "600519.SH", "report": "2024-4"}
        )

    def test_fetch_401_returns_none(self) -> None:
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(401, "unauth")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="bad")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_429_returns_none(self) -> None:
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(429, "rate limit")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_500_returns_none(self) -> None:
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(500, "server error")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_timeout_returns_none(self) -> None:
        fake_session = MagicMock()
        fake_session.post.side_effect = requests.Timeout("read timeout")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_connection_error_returns_none(self) -> None:
        fake_session = MagicMock()
        fake_session.post.side_effect = requests.ConnectionError("dns fail")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_fetch_business_error_returns_none(self) -> None:
        raw = json.dumps({"code": 4001, "message": "rate", "data": None})
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(200, raw)
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="k")
        self.assertIsNone(f.fetch("600519", "pe_ratio"))

    def test_logs_no_api_key(self) -> None:
        """凭据安全：debug 日志不应打印 API key 任何片段。"""
        fake_session = MagicMock()
        fake_session.post.return_value = _FakeResp(500, "server error")
        with patch.object(FuyaoFetcher, "_build_session", return_value=fake_session):
            f = FuyaoFetcher(endpoint="https://x", api_key="SECRET-KEY-DO-NOT-LEAK")
        with self.assertLogs("data_provider.fuyao_adapter", level=logging.DEBUG) as cm:
            f.fetch("600519", "pe_ratio")
        joined = "\n".join(cm.output)
        self.assertNotIn("SECRET-KEY-DO-NOT-LEAK", joined)


# ------------------------------------------------------------------
# FuyaoSource 单测（fail-open 矩阵 + 凭据脱敏）
# ------------------------------------------------------------------


class _FakeFetcher:
    """FuyaoFetcher 替身（注入 FuyaoSource 测试同步逻辑，对齐 SourceAdapter Protocol）。"""

    name: str = "fake"

    def __init__(
        self,
        available: bool = True,
        fetch_fn: Optional[Any] = None,
    ) -> None:
        self.available = available
        self._fetch_fn = fetch_fn or (lambda code, field, period: None)

    def fetch(self, code: str, field: str, period: Optional[str] = None) -> Optional[AnchorReading]:
        return self._fetch_fn(code, field, period)


class FuyaoSourceTests(unittest.TestCase):
    def test_name_is_fuyao(self) -> None:
        self.assertEqual(FuyaoSource.name, "fuyao")

    def test_available_false_without_fetcher(self) -> None:
        s = FuyaoSource()
        self.assertFalse(s.available)

    def test_available_false_when_fetcher_unavailable(self) -> None:
        s = FuyaoSource(fetcher=_FakeFetcher(available=False))
        self.assertFalse(s.available)

    def test_available_true_when_fetcher_available(self) -> None:
        s = FuyaoSource(fetcher=_FakeFetcher(available=True))
        self.assertTrue(s.available)

    def test_read_without_fetcher_returns_none(self) -> None:
        s = FuyaoSource()
        self.assertIsNone(s.read("600519", "pe_ratio"))

    def test_read_fetcher_returns_none(self) -> None:
        s = FuyaoSource(fetcher=_FakeFetcher(fetch_fn=lambda c, f, p: None))
        self.assertIsNone(s.read("600519", "pe_ratio"))

    def test_read_fetcher_returns_anchor(self) -> None:
        anchor = AnchorReading(source="fuyao", value=1.0, caliber="TTM", period=None)
        s = FuyaoSource(fetcher=_FakeFetcher(fetch_fn=lambda c, f, p: anchor))
        r = s.read("600519", "pe_ratio")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r.source, "fuyao")
        self.assertAlmostEqual(r.value, 1.0)
        self.assertEqual(r.caliber, "TTM")

    def test_read_fetcher_raises_returns_none(self) -> None:
        def boom(code: str, field: str, period: Optional[str]) -> AnchorReading:
            raise RuntimeError("explode")

        s = FuyaoSource(fetcher=_FakeFetcher(fetch_fn=boom))
        self.assertIsNone(s.read("600519", "pe_ratio"))

    def test_read_renames_source_to_fuyao(self) -> None:
        """即便利他 fetcher 误填 source，FuyaoSource 也应覆写为 'fuyao'。"""
        anchor = AnchorReading(source="wrong", value=1.0)
        s = FuyaoSource(fetcher=_FakeFetcher(fetch_fn=lambda c, f, p: anchor))
        r = s.read("600519", "pe_ratio")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r.source, "fuyao")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
