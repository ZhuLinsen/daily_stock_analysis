# -*- coding: utf-8 -*-
"""Tests for scripts.refresh_stock_index default fetch behavior."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

refresh_stock_index = importlib.import_module("refresh_stock_index")


def test_main_fetches_tushare_with_a_rk_by_default():
    with (
        patch.object(refresh_stock_index, "_has_tushare_token", return_value=True),
        patch.object(refresh_stock_index, "_run") as run,
        patch.object(refresh_stock_index, "_sync_static_index"),
    ):
        exit_code = refresh_stock_index.main([])

    assert exit_code == 0
    assert run.call_args_list[0].args[0] == [
        sys.executable,
        "scripts/fetch_tushare_stock_list.py",
        "--a-rk",
    ]
    assert run.call_args_list[1].args[0] == [
        sys.executable,
        "scripts/generate_index_from_csv.py",
        "--source",
        "tushare",
    ]
