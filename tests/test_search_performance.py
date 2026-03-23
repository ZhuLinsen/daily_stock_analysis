# -*- coding: utf-8 -*-
"""
===================================
Search Algorithm Performance Tests
===================================

Benchmarks the name-to-code resolution engine under load.
"""

import time
import random
import string
import pytest
from unittest.mock import patch
from src.services.name_to_code_resolver import resolve_name_to_code

def generate_random_name(length=4):
    return ''.join(random.choices(string.ascii_letters, k=length))

def generate_random_cjk_name(length=3):
    return ''.join(chr(random.randint(0x4e00, 0x9fff)) for _ in range(length))

class TestSearchPerformance:
    """Benchmark tests for stock search resolution."""

    @pytest.mark.benchmark
    def test_resolve_name_to_code_throughput(self):
        """Test throughput of name resolution for various input types."""
        # 1. Realistic mixed inputs (codes, names, typos)
        inputs = [
            "600519", "00700", "AAPL", "TSLA",
            "贵州茅台", "腾讯控股", "阿里巴巴",
            "贵州茅苔", "平安银形", # typos
            "aaaaaaa", "1234567", # garbage
        ]
        
        start_time = time.time()
        iterations = 100
        for _ in range(iterations):
            for s in inputs:
                resolve_name_to_code(s)
        
        duration = time.time() - start_time
        avg_ms = (duration / (iterations * len(inputs))) * 1000
        
        print(f"\nAverage resolution time: {avg_ms:.2f}ms")
        # Resolution should be fast (mostly < 5ms for local hits, < 20ms for fuzzy)
        assert avg_ms < 50, f"Search resolution too slow: {avg_ms:.2f}ms"

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
