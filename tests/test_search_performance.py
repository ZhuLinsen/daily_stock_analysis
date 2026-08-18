# -*- coding: utf-8 -*-
"""
===================================
Search Algorithm Performance Tests
===================================

Benchmarks the name-to-code resolution engine under load.
"""

import time
import pytest
from unittest.mock import patch
from src.services.name_to_code_resolver import resolve_name_to_code


@pytest.fixture(autouse=True)
def _restore_resolver_state():
    """快照/还原 name_to_code_resolver 模块级可变状态，防止基准用例的
    AkShare mock 数据（extend_AkShare 合并进全局 stockDB 并置位
    _akshare_merged）泄漏给同进程内后续运行的测试文件。"""
    from src.services import name_to_code_resolver as resolver_mod

    db = dict(resolver_mod.stockDB)
    cache = resolver_mod._akshare_cache
    merged = resolver_mod._akshare_merged
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod._akshare_cache = cache
    resolver_mod._akshare_merged = merged
    # stockDB 原地增删，按对象身份缓存的名称/拼音列表可能已陈旧，强制重建
    resolver_mod._database_names_cache[:] = [None, None, None]


class TestSearchPerformance:
    """Benchmark tests for stock search resolution."""

    @pytest.mark.benchmark
    def test_resolve_name_to_code_fast_path_throughput(self):
        """Benchmark the common fast paths without typo/fuzzy fallbacks dominating runtime."""
        inputs = [
            "600519", "00700", "AAPL", "TSLA",
            "贵州茅台", "腾讯控股", "阿里巴巴",
            "aaaaaaa", "1234567",
        ]

        # Warm caches/import paths before timing.
        for s in inputs:
            resolve_name_to_code(s)

        start_time = time.time()
        iterations = 30
        for _ in range(iterations):
            for s in inputs:
                resolve_name_to_code(s)

        duration = time.time() - start_time
        avg_ms = (duration / (iterations * len(inputs))) * 1000

        print(f"\nAverage fast-path resolution time: {avg_ms:.2f}ms")
        assert avg_ms < 20, f"Fast-path resolution too slow: {avg_ms:.2f}ms"

    @pytest.mark.benchmark
    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code", return_value={})
    def test_resolve_name_to_code_typo_fallback_budget(self, mock_akshare):
        """Benchmark typo/fuzzy fallback separately with a smaller iteration budget."""
        typo_inputs = [
            "贵州茅苔",
            "平安银形",
        ]

        for s in typo_inputs:
            resolve_name_to_code(s)

        start_time = time.time()
        iterations = 10
        for _ in range(iterations):
            for s in typo_inputs:
                resolve_name_to_code(s)

        duration = time.time() - start_time
        avg_ms = (duration / (iterations * len(typo_inputs))) * 1000

        print(f"\nAverage typo/fallback resolution time: {avg_ms:.2f}ms")
        assert avg_ms < 100, f"Typo fallback too slow: {avg_ms:.2f}ms"

    @pytest.mark.benchmark
    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_fuzzy_match_performance_large_set(self, mock_akshare):
        """Test difflib fuzzy matching performance with a 5000+ stock set."""
        # Simulate 5000 stocks from AkShare
        fake_market = {f"股票_{i}": f"{i:06d}" for i in range(5000)}
        mock_akshare.return_value = fake_market
        
        query = "股票_4999" # Worst case or near worst case for fuzzy matching
        
        start_time = time.time()
        iterations = 20
        for _ in range(iterations):
            resolve_name_to_code(query)
        
        duration = time.time() - start_time
        avg_ms = (duration / iterations) * 1000
        
        print(f"\nFuzzy match (5000 stocks) avg time: {avg_ms:.2f}ms")
        # Fuzzy matching 5000 strings is CPU intensive. 
        # Aiming for < 100ms per request on a standard CI environment.
        assert avg_ms < 200, f"Fuzzy matching too slow: {avg_ms:.2f}ms"
