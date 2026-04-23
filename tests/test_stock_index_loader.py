# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data import stock_index_loader


class TestStockIndexLoader(unittest.TestCase):
    def setUp(self):
        stock_index_loader._clear_stock_index_cache_for_tests()

    def tearDown(self):
        stock_index_loader._clear_stock_index_cache_for_tests()

    def test_get_index_stock_name_supports_display_canonical_and_hk_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "stocks.index.json"
            index_path.write_text(
                json.dumps(
                    [
                        ["000001.SZ", "000001", "平安银行", "pinganyinhang", "payh", [], "CN", "stock", True, 100],
                        ["00700.HK", "00700", "腾讯控股", "tengxunkonggu", "txkg", [], "HK", "stock", True, 100],
                        ["AAPL", "AAPL", "苹果", "pingguo", "pg", [], "US", "stock", True, 100],
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(index_path,)):
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "平安银行")
                self.assertEqual(stock_index_loader.get_index_stock_name("000001.SZ"), "平安银行")
                self.assertEqual(stock_index_loader.get_index_stock_name("HK00700"), "腾讯控股")
                self.assertEqual(stock_index_loader.get_index_stock_name("00700"), "腾讯控股")
                self.assertEqual(stock_index_loader.get_index_stock_name("700.HK"), "腾讯控股")
                self.assertEqual(stock_index_loader.get_index_stock_name("aapl"), "苹果")

    def test_get_stock_name_index_map_is_cached_after_first_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "stocks.index.json"
            index_path.write_text(
                json.dumps([["000001.SZ", "000001", "平安银行"]], ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(index_path,)):
                first = stock_index_loader.get_stock_name_index_map()
                index_path.write_text(
                    json.dumps([["000001.SZ", "000001", "变更后名称"]], ensure_ascii=False),
                    encoding="utf-8",
                )
                second = stock_index_loader.get_stock_name_index_map()

            self.assertIs(first, second)
            self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "平安银行")

    def test_get_index_stock_name_returns_none_when_index_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "stocks.index.json"
            with patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(missing_path,)):
                self.assertEqual(stock_index_loader.get_stock_name_index_map(), {})
                self.assertIsNone(stock_index_loader.get_index_stock_name("000001"))

    def test_get_stock_name_index_map_skips_invalid_utf8_and_uses_next_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_path = Path(temp_dir) / "invalid-stocks.index.json"
            valid_path = Path(temp_dir) / "stocks.index.json"
            invalid_path.write_bytes(b"\xff\xfe\xfd")
            valid_path.write_text(
                json.dumps([["000001.SZ", "000001", "平安银行"]], ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                stock_index_loader,
                "get_stock_index_candidate_paths",
                return_value=(invalid_path, valid_path),
            ):
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "平安银行")

    def test_get_stock_name_index_map_skips_unexpected_json_shape_and_uses_next_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            malformed_path = Path(temp_dir) / "malformed-stocks.index.json"
            valid_path = Path(temp_dir) / "stocks.index.json"
            malformed_path.write_text(
                json.dumps({"code": "000001", "name": "平安银行"}, ensure_ascii=False),
                encoding="utf-8",
            )
            valid_path.write_text(
                json.dumps([["000001.SZ", "000001", "平安银行"]], ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                stock_index_loader,
                "get_stock_index_candidate_paths",
                return_value=(malformed_path, valid_path),
            ):
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "平安银行")


if __name__ == "__main__":
    unittest.main()
