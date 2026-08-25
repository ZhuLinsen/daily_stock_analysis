# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

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

    def test_resolve_index_stock_code_rejects_cross_market_bare_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    [
                        ["08035.HK", "08035", "HK 8035", "hk8035", "hk", [], "HK", "stock", True, 100],
                        ["8035.T", "8035.T", "JP 8035", "jp8035", "jp", [], "JP", "stock", True, 100],
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
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("8035"))

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

    def test_resolve_index_stock_code_does_not_bare_resolve_tw_suffix_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    [
                        ["2330.TW", "2330.TW", "台积电", "taijidian", "tjd", [], "TW", "stock", True, 100],
                        ["6505.TWO", "6505.TWO", "台塑化", "taisu", "ts", [], "TW", "stock", True, 100],
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("2330"))
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("2330.TW"))
                self.assertIsNone(stock_index_loader.resolve_index_stock_code("6505.TWO"))

    # ------------------------------------------------------------------
    # Active index row loader
    # ------------------------------------------------------------------

    def _index_payload(self, canonicals):
        rows = []
        for c in canonicals:
            display = f"{c[3:]}.CSI" if c.startswith("csi") else c
            rows.append([c, display, f"指数{c}", "zhishu", "zs", [], "CN", "index", True, 100])
        return rows

    def _pad_payload(self, rows, size=100):
        """Pad a payload with stock rows so it passes the remote min_items check."""
        padded = list(rows)
        while len(padded) < size:
            i = len(padded)
            padded.append([f"{i:06d}.SZ", f"{i:06d}", f"股票{i}", "gupiao", "gp", [], "CN", "stock", True, 100])
        return padded

    def test_load_active_index_rows_returns_index_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    self._index_payload(["sh000300", "csi930955"])
                    + [["000001.SZ", "000001", "平安银行", "payh", "payh", [], "CN", "stock", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual({r[0] for r in rows}, {"sh000300", "csi930955"})

    def test_load_active_index_rows_remote_superset_wins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            remote_cache.parent.mkdir(parents=True, exist_ok=True)
            remote_cache.write_text(
                json.dumps(self._pad_payload(self._index_payload(["sh000300", "sh000016", "csi930955"])), ensure_ascii=False),
                encoding="utf-8",
            )
            bundled_path.parent.mkdir(parents=True, exist_ok=True)
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016"]), ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016", "csi930955"})

    def test_load_active_index_rows_remote_subset_falls_back_to_bundled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            remote_cache.parent.mkdir(parents=True, exist_ok=True)
            # Remote drops sh000016 (a bundled baseline canonical).
            remote_cache.write_text(
                json.dumps(self._pad_payload(self._index_payload(["sh000300"])), ensure_ascii=False),
                encoding="utf-8",
            )
            bundled_path.parent.mkdir(parents=True, exist_ok=True)
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016"]), ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path)):
                rows = stock_index_loader._load_active_index_rows()
            # Falls back to bundled (which has both).
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016"})

    def test_load_active_index_rows_all_failed_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=missing_path), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(missing_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_load_active_index_rows_rejects_semantic_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            # Two index rows share the same canonical — semantic conflict.
            bundled_path.write_text(
                json.dumps(
                    self._index_payload(["sh000300"]) + self._index_payload(["sh000300"]),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            # Semantic conflict rejects the candidate → empty registry.
            self.assertEqual(rows, [])

    def test_clear_stock_index_cache_clears_active_index_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300"]), ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                first = stock_index_loader._load_active_index_rows()
                stock_index_loader.clear_stock_index_cache()
                second = stock_index_loader._load_active_index_rows()
            self.assertEqual(first, second)

    def test_validate_index_rows_semantics_rejects_malformed_csi_display(self):
        """Gap 1: a CSI row whose display is not ``{code}.CSI`` is rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            # csi930955 with a wrong display (not ``930955.CSI``).
            bundled_path.write_text(
                json.dumps(
                    [["csi930955", "930955", "红利低波100", "honglidibo100", "hldb100", [], "CN", "index", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            # Malformed CSI display rejects the candidate → empty registry.
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_stock_key_collision(self):
        """Gap 3: an index canonical/display/alias that collides with an active
        stock/ETF key after normalization is rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            # A stock row whose canonical ``sh000300`` collides with the index
            # canonical ``sh000300`` in the same candidate.
            bundled_path.write_text(
                json.dumps(
                    self._index_payload(["sh000300"])
                    + [["sh000300", "sh000300", "冲突股票", "ctgp", "ctgp", [], "CN", "stock", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            # The candidate is rejected because both identities claim one key.
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_csi_canonical_stock_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(
                    self._index_payload(["csi930955"])
                    + [["csi930955", "930955", "冲突股票", "ctgp", "ctgp", [], "CN", "stock", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_text_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300"])
            payload[0][5] = ["CSI300"]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_blank_pinyin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300"])
            payload[0][3] = ""
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_non_string_pinyin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300"])
            payload[0][3] = ["hushen300"]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_equivalent_suffix_stock_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh600519"])
            payload += [["600519.SH", "600519", "贵州茅台", "gzmt", "gzmt", [], "CN", "stock", True, 100]]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_load_active_index_rows_rejects_mixed_valid_and_short_local_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300"]) + [["too-short"]]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_non_integer_popularity(self):
        """PR #2267 review fix: only a plain non-negative integer popularity is
        valid at the runtime candidate boundary; fractional/boolean/negative/
        string popularities reject the candidate."""
        for bad_popularity in (1.5, True, -1, 1.0, "100"):
            with tempfile.TemporaryDirectory() as temp_dir:
                bundled_path = Path(temp_dir) / "stocks.index.json"
                payload = self._index_payload(["sh000300"])
                payload[0][9] = bad_popularity
                bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                     patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                    rows = stock_index_loader._load_active_index_rows()
                self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_accepts_integer_popularity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300"]), ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual({r[0] for r in rows}, {"sh000300"})

    def test_validate_index_rows_semantics_rejects_cross_entry_duplicate_alias(self):
        """PR #2267 review fix: two index rows whose aliases normalize to the
        same identity key (e.g. ``csi930955`` and ``CSI930955`` as aliases of
        different canonicals) must reject the candidate — no silent overwrite."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300", "sz399001"])
            payload[0][5] = ["csi930955"]
            payload[1][5] = ["CSI930955"]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_validate_index_rows_semantics_rejects_duplicate_aliases_in_one_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_path = Path(temp_dir) / "stocks.index.json"
            payload = self._index_payload(["sh000300"])
            payload[0][5] = ["000300.CSI", "０００３００．ＣＳＩ"]
            bundled_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=Path(temp_dir) / "missing.json"), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(bundled_path,)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual(rows, [])

    def test_load_active_index_rows_bundled_baseline_ignores_newer_legacy_static(self):
        """Gap 4: the bundled baseline comes from the declared bundled candidate
        (``apps/dsa-web/public``), not the first non-remote candidate ordered by
        mtime. A newer legacy ``static`` candidate must not become the baseline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            legacy_static = Path(temp_dir) / "static" / "stocks.index.json"
            for p in (remote_cache, bundled_path, legacy_static):
                p.parent.mkdir(parents=True, exist_ok=True)
            # Remote is a superset of the bundled baseline.
            remote_cache.write_text(
                json.dumps(self._pad_payload(self._index_payload(["sh000300", "sh000016", "csi930955"])), ensure_ascii=False),
                encoding="utf-8",
            )
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016"]), ensure_ascii=False),
                encoding="utf-8",
            )
            # Legacy static is NEWER than bundled but only carries sh000300.
            legacy_static.write_text(
                json.dumps(self._index_payload(["sh000300"]), ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(remote_cache, (3_000, 3_000))
            os.utime(legacy_static, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path, legacy_static)):
                rows = stock_index_loader._load_active_index_rows()
            # Remote superset of the bundled baseline wins.
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016", "csi930955"})

    def test_load_active_index_rows_malformed_bundled_falls_back_to_valid_remote(self):
        """Gap 4: a malformed bundled candidate (fails semantic validation) must
        not become the baseline; a valid remote superset is then accepted."""
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            remote_cache.parent.mkdir(parents=True, exist_ok=True)
            bundled_path.parent.mkdir(parents=True, exist_ok=True)
            # Remote is a valid superset.
            remote_cache.write_text(
                json.dumps(self._pad_payload(self._index_payload(["sh000300", "sh000016", "csi930955"])), ensure_ascii=False),
                encoding="utf-8",
            )
            # Bundled has a malformed CSI display (not ``{code}.CSI``).
            bundled_path.write_text(
                json.dumps(
                    [["csi930955", "930955", "红利低波100", "honglidibo100", "hldb100", [], "CN", "index", True, 100]],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.utime(remote_cache, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path)):
                rows = stock_index_loader._load_active_index_rows()
            # Malformed bundled is skipped; valid remote superset is loaded.
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016", "csi930955"})

    def test_load_active_index_rows_legacy_static_subset_cannot_bypass_bundled_baseline(self):
        """Review remediation: when the remote cache is missing/invalid, a newer
        legacy ``static`` candidate that is a SUBSET of the bundled baseline must
        NOT be selected — the bundled baseline wins so no active index is lost."""
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            legacy_static = Path(temp_dir) / "static" / "stocks.index.json"
            for p in (remote_cache, bundled_path, legacy_static):
                p.parent.mkdir(parents=True, exist_ok=True)
            # Remote cache is invalid (not JSON).
            remote_cache.write_text("not-json", encoding="utf-8")
            # Bundled baseline carries sh000300 + sh000016.
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016"]), ensure_ascii=False),
                encoding="utf-8",
            )
            # Legacy static is NEWER than bundled but only carries sh000300.
            legacy_static.write_text(
                json.dumps(self._index_payload(["sh000300"]), ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(remote_cache, (3_000, 3_000))
            os.utime(legacy_static, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path, legacy_static)):
                rows = stock_index_loader._load_active_index_rows()
            # Bundled baseline wins (both canonicals preserved).
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016"})

    def test_load_active_index_rows_legacy_static_superset_still_wins(self):
        """A legacy ``static`` candidate that is a legal SUPERSET of the bundled
        baseline is still accepted (future supersets are allowed)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            remote_cache = Path(temp_dir) / "cache" / "stocks.index.json"
            bundled_path = Path(temp_dir) / "apps" / "stocks.index.json"
            legacy_static = Path(temp_dir) / "static" / "stocks.index.json"
            for p in (remote_cache, bundled_path, legacy_static):
                p.parent.mkdir(parents=True, exist_ok=True)
            remote_cache.write_text("not-json", encoding="utf-8")
            bundled_path.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016"]), ensure_ascii=False),
                encoding="utf-8",
            )
            # Legacy static is a superset (adds csi930955).
            legacy_static.write_text(
                json.dumps(self._index_payload(["sh000300", "sh000016", "csi930955"]), ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(remote_cache, (3_000, 3_000))
            os.utime(legacy_static, (2_000, 2_000))
            os.utime(bundled_path, (1_000, 1_000))
            with patch.object(stock_index_loader, "get_remote_stock_index_cache_path", return_value=remote_cache), \
                 patch.object(stock_index_loader, "get_stock_index_candidate_paths", return_value=(remote_cache, bundled_path, legacy_static)):
                rows = stock_index_loader._load_active_index_rows()
            self.assertEqual({r[0] for r in rows}, {"sh000300", "sh000016", "csi930955"})


if __name__ == "__main__":
    unittest.main()
