# -*- coding: utf-8 -*-
"""Offline tests for zero-key A-share free-source adapters."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class _FakeResponse:
    def __init__(self, payload, text=None):
        self._payload = payload
        self.text = text if text is not None else ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "cls.cn/v1/roll/get_roll_list" in url:
            return _FakeResponse(
                {
                    "data": {
                        "roll_data": [
                            {
                                "id": "1",
                                "ctime": 1785391200,
                                "title": "快讯标题",
                                "content": "快讯内容",
                                "shareurl": "https://www.cls.cn/detail/1",
                            }
                        ]
                    }
                }
            )
        if "getharden" in url:
            return _FakeResponse(
                {
                    "errocode": 0,
                    "data": [
                        {
                            "code": "SH600519",
                            "name": "贵州茅台",
                            "reason": "白酒+消费",
                            "zhangfu": "3.21",
                            "huanshou": "0.8",
                            "chengjiaoe": "1234567",
                            "close": "1500.5",
                        }
                    ],
                }
            )
        if "szse_stock.json" in url:
            return _FakeResponse({"stockList": [{"code": "601318", "orgId": "9900002221"}]})
        if "MoneyFlow.ssl_qsfx_zjlrqs" in url:
            return _FakeResponse(
                None,
                text='[{"opendate":"2026-07-29","trade":"1500.5","netamount":"12345","turnover":"1.2"}]',
            )
        if "ShowReport/data" in url:
            return _FakeResponse(
                [
                    {
                        "data": [
                            {
                                "zqdm": "000001",
                                "zqjc": "平安银行",
                                "cjje": "1000000",
                                "plyy": "日涨幅偏离值达到7%",
                            }
                        ]
                    }
                ]
            )
        if "showTradePublicFile.do" in url:
            return _FakeResponse(None, text='cb({"fileContents":["600519 贵州茅台 营业部席位"]})')
        if "np-anotice-stock.eastmoney.com" in url:
            return _FakeResponse(
                {
                    "data": {
                        "list": [
                            {
                                "art_code": "AN202607300001",
                                "title": "沪市公告",
                                "notice_date": "2026-07-30 00:00:00",
                            }
                        ]
                    }
                }
            )
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "hisAnnouncement/query" in url:
            return _FakeResponse(
                {
                    "announcements": [
                        {
                            "announcementId": "abc",
                            "announcementTitle": "年度报告",
                            "announcementTypeName": "定期报告",
                            "announcementTime": 1785369600000,
                            "adjunctUrl": "finalpage/2026-07-30/test.pdf",
                        }
                    ]
                }
            )
        if "announcement/annList" in url:
            return _FakeResponse(
                {
                    "data": [
                        {
                            "id": "sz-1",
                            "title": "深市公告",
                            "publishTime": "2026-07-30 12:00:00",
                            "attachPath": "/disc/2026/test.pdf",
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected POST: {url}")


class TestAStockFreeFetcher(unittest.TestCase):
    def setUp(self):
        from data_provider.a_stock_free_fetcher import AStockFreeFetcher

        self.fetcher = AStockFreeFetcher(client=_FakeClient())

    def test_cls_telegraph_normalizes_rows(self):
        rows = self.fetcher.cls_telegraph(page_size=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "cls")
        self.assertEqual(rows[0]["title"], "快讯标题")
        self.assertIn("time", rows[0])

    def test_ths_hot_reason_normalizes_code_and_reason(self):
        rows = self.fetcher.ths_hot_reason(date="2026-07-30")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["reason"], "白酒+消费")
        self.assertAlmostEqual(rows[0]["change_pct"], 3.21)
        self.assertEqual(rows[0]["source"], "ths_hot_reason")

    def test_cninfo_announcements_use_dynamic_orgid_and_pdf_url(self):
        rows = self.fetcher.cninfo_announcements("601318", page_size=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "601318")
        self.assertEqual(rows[0]["source"], "cninfo")
        self.assertTrue(rows[0]["pdf_url"].startswith("https://static.cninfo.com.cn/"))

        post_call = [c for c in self.fetcher.client.calls if c[0] == "POST"][0]
        self.assertIn("601318,9900002221", post_call[2]["data"]["stock"])

    def test_cninfo_orgid_fallback_rules(self):
        from data_provider.a_stock_free_fetcher import AStockFreeFetcher

        class FailingClient(_FakeClient):
            def get(self, url, **kwargs):
                if "szse_stock.json" in url:
                    raise RuntimeError("offline")
                return super().get(url, **kwargs)

        fetcher = AStockFreeFetcher(client=FailingClient())
        self.assertEqual(fetcher._cninfo_orgid("600519"), "gssh0600519")
        self.assertEqual(fetcher._cninfo_orgid("000001"), "gssz0000001")
        self.assertEqual(fetcher._cninfo_orgid("920001"), "gsbj0920001")

    def test_sina_fund_flow_backup_normalizes_rows(self):
        rows = self.fetcher.sina_fund_flow_backup("600519", days=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600519")
        self.assertEqual(rows[0]["date"], "2026-07-29")
        self.assertAlmostEqual(rows[0]["net_amount"], 12345.0)
        self.assertEqual(rows[0]["source"], "sina_fund_flow")

    def test_official_dragon_tiger_backup_combines_exchange_sources(self):
        data = self.fetcher.official_dragon_tiger_backup("2026-07-30")

        self.assertEqual(data["source"], "official_exchange")
        self.assertEqual(data["szse"][0]["code"], "000001")
        self.assertIn("贵州茅台", data["sse_raw"])

    def test_announcement_fallback_uses_szse_for_shenzhen(self):
        rows = self.fetcher.announcement_fallback("000001", page_size=3)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "szse_announcement")
        self.assertTrue(rows[0]["pdf_url"].startswith("https://disc.static.szse.cn/download"))

    def test_announcement_fallback_uses_eastmoney_for_shanghai(self):
        rows = self.fetcher.announcement_fallback("600519", page_size=3)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "eastmoney_announcement_fallback")
        self.assertIn("AN202607300001", rows[0]["pdf_url"])


class TestAStockFreeFetcherManagerHooks(unittest.TestCase):
    @patch("src.config.get_config")
    def test_manager_free_source_methods_fail_open(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace()

        from data_provider.base import DataFetcherManager

        fetcher = MagicMock()
        fetcher.cls_telegraph.side_effect = RuntimeError("network")
        fetcher.ths_hot_reason.return_value = [{"code": "600519"}]
        fetcher.cninfo_announcements.return_value = [{"title": "公告"}]
        fetcher.sina_fund_flow_backup.return_value = [{"date": "2026-07-29"}]
        fetcher.official_dragon_tiger_backup.return_value = {"date": "2026-07-30", "szse": []}
        fetcher.announcement_fallback.return_value = [{"title": "fallback"}]

        manager = DataFetcherManager(fetchers=[])
        manager._a_stock_free_fetcher = fetcher

        self.assertEqual(manager.get_free_market_news(), [])
        self.assertEqual(manager.get_free_hot_reasons(), [{"code": "600519"}])
        self.assertEqual(manager.get_free_announcements("600519"), [{"title": "公告"}])
        self.assertEqual(manager.get_fallback_fund_flow("600519"), [{"date": "2026-07-29"}])
        self.assertEqual(manager.get_fallback_dragon_tiger("2026-07-30"), {"date": "2026-07-30", "szse": []})
        self.assertEqual(manager.get_fallback_announcements("600519"), [{"title": "fallback"}])


if __name__ == "__main__":
    unittest.main()
