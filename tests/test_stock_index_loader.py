# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data import stock_index_loader


def _write_stock_index(path: Path, name: str, size: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                [
                    f"{index + 1:06d}.SZ",
                    f"{index + 1:06d}",
                    name,
                    "pinganyinhang",
                    "payh",
                    [],
                    "CN",
                    "stock",
                    True,
                    100,
                ]
                for index in range(size)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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

    def test_default_candidate_paths_prefer_remote_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "data" / "cache" / "stocks.index.json"
            with patch.object(
                stock_index_loader,
                "get_remote_stock_index_cache_path",
                return_value=remote_cache,
            ):
                paths = stock_index_loader.get_stock_index_candidate_paths()

            self.assertEqual(paths[0], remote_cache)
            self.assertTrue(paths[1].as_posix().endswith("apps/dsa-web/public/stocks.index.json"))
            self.assertTrue(paths[2].as_posix().endswith("static/stocks.index.json"))

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

    def test_newer_bundled_index_wins_over_older_remote_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            _write_stock_index(remote_cache, "旧远程缓存", size=100)
            _write_stock_index(bundled_path, "新内置索引")
            os.utime(remote_cache, (1_000, 1_000))
            os.utime(bundled_path, (2_000, 2_000))

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(
                     stock_index_loader,
                     "get_stock_index_candidate_paths",
                     return_value=(remote_cache, bundled_path),
                 ):
                self.assertEqual(stock_index_loader.find_existing_stock_index_path(), bundled_path)
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "新内置索引")

    def test_newer_remote_cache_wins_when_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            _write_stock_index(remote_cache, "新远程缓存", size=100)
            _write_stock_index(bundled_path, "旧内置索引")
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(
                     stock_index_loader,
                     "get_stock_index_candidate_paths",
                     return_value=(remote_cache, bundled_path),
                 ):
                self.assertEqual(stock_index_loader.find_existing_stock_index_path(), remote_cache)
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "新远程缓存")

    def test_invalid_remote_cache_is_skipped_even_when_newer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            remote_cache.parent.mkdir(parents=True, exist_ok=True)
            remote_cache.write_text("not-json", encoding="utf-8")
            _write_stock_index(bundled_path, "内置索引")
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(
                     stock_index_loader,
                     "get_stock_index_candidate_paths",
                     return_value=(remote_cache, bundled_path),
                 ):
                self.assertEqual(stock_index_loader.find_existing_stock_index_path(), bundled_path)
                self.assertEqual(stock_index_loader.get_index_stock_name("000001"), "内置索引")

    def test_resolve_index_stock_code_falls_through_to_bundled_jp_kr_pool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            _write_stock_index(remote_cache, "old remote", size=100)
            bundled_path.parent.mkdir(parents=True, exist_ok=True)
            bundled_path.write_text(
                json.dumps(
                    [
                        ["005930.KS", "005930.KS", "Samsung", "samsung", "ss", [], "KR", "stock", True, 100],
                        ["7203.T", "7203.T", "Toyota", "toyota", "tyt", [], "JP", "stock", True, 100],
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(
                     stock_index_loader,
                     "get_stock_index_candidate_paths",
                     return_value=(remote_cache, bundled_path),
                 ):
                self.assertEqual(stock_index_loader.resolve_index_stock_code("005930"), "005930.KS")
                self.assertEqual(stock_index_loader.resolve_index_stock_code("7203"), "7203.T")

    def test_resolve_index_stock_code_reuses_cached_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    [["005930.KS", "005930.KS", "Samsung", "samsung", "ss", [], "KR", "stock", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)), \
                 patch.object(stock_index_loader, "_load_stock_index_payload", wraps=stock_index_loader._load_stock_index_payload) as load_payload:
                self.assertEqual(stock_index_loader.resolve_index_stock_code("005930"), "005930.KS")
                self.assertEqual(stock_index_loader.resolve_index_stock_code("005930"), "005930.KS")

            self.assertEqual(load_payload.call_count, 1)

    def test_resolve_index_stock_code_skips_inactive_jp_kr_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    [
                        [
                            "005930.KS",
                            "005930.KS",
                            "三星电子",
                            "samsung",
                            "ss",
                            [],
                            "KR",
                            "stock",
                            False,
                            100,
                        ],
                        [
                            "7203.T",
                            "7203.T",
                            "丰田汽车",
                            "toyota",
                            "tyt",
                            [],
                            "JP",
                            "stock",
                            False,
                            100,
                        ],
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(
                stock_index_loader,
                "get_remote_stock_index_cache_path",
                return_value=Path(temp_dir) / "missing.json",
            ), patch.object(
                stock_index_loader,
                "get_stock_index_candidate_paths",
                return_value=(bundled_path,),
            ):
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("005930"))
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("7203"))


if __name__ == "__main__":
    unittest.main()
