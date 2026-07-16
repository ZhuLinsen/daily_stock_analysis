# -*- coding: utf-8 -*-
"""Tests for STOCK_LIST separator handling."""

from src.services.stock_list_parser import serialize_stock_list, split_stock_list


def test_split_stock_list_accepts_common_copy_paste_separators() -> None:
    value = "600519，300750  hk00700;AAPL、7203.T\n005930.KS；002594"

    assert split_stock_list(value) == [
        "600519",
        "300750",
        "hk00700",
        "AAPL",
        "7203.T",
        "005930.KS",
        "002594",
    ]


def test_serialize_stock_list_uses_canonical_commas() -> None:
    assert serialize_stock_list("600519，300750\nAAPL") == "600519,300750,AAPL"
