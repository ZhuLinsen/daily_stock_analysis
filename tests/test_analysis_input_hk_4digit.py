# -*- coding: utf-8 -*-
"""Regression: bare 4-digit HK codes must reach the analysis pipeline.

``0001`` (长和) / ``0941`` (中国移动) are treated as HK stocks by
``data_provider.base._is_hk_market``, ``resolve_daily_stock_identity`` and
``parse_analysis_target`` (issue #2091), but ``POST /analyze`` previously
rejected them with a 400 because ``is_code_like`` only recognized 5-6 digit
bare numerics. This test guards the input gate used by the analyze API.
"""

import os
import tempfile
import unittest
from pathlib import Path

_ORIGINAL_ENVIRON = dict(os.environ)
_MODULE_TEMP_DIR = tempfile.TemporaryDirectory()
_MODULE_ENV_FILE = Path(_MODULE_TEMP_DIR.name) / ".env"
_MODULE_ENV_FILE.write_text("STOCK_LIST=600519,000001\n", encoding="utf-8")
os.environ["ENV_FILE"] = str(_MODULE_ENV_FILE)

from tests.litellm_stub import ensure_litellm_stub  # noqa: E402

ensure_litellm_stub()

from api.v1.endpoints.analysis import _resolve_and_normalize_input  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def tearDownModule() -> None:
    for key in list(os.environ):
        if key == "PYTEST_CURRENT_TEST":
            continue
        if key not in _ORIGINAL_ENVIRON:
            os.environ.pop(key, None)
    _MODULE_TEMP_DIR.cleanup()


class AnalysisInputHkBareCodeTestCase(unittest.TestCase):
    def test_bare_4_digit_hk_codes_are_accepted(self) -> None:
        # Issue #2091 core examples: 0001 长和 / 0941 中国移动.
        self.assertEqual(_resolve_and_normalize_input("0001"), "0001")
        self.assertEqual(_resolve_and_normalize_input("0941"), "0941")
        self.assertEqual(_resolve_and_normalize_input("1810"), "1810")

    def test_bare_5_digit_hk_codes_still_work(self) -> None:
        self.assertEqual(_resolve_and_normalize_input("00700"), "00700")

    def test_prefixed_and_suffixed_hk_codes_still_work(self) -> None:
        self.assertEqual(_resolve_and_normalize_input("HK0001"), "HK0001")
        self.assertEqual(_resolve_and_normalize_input("0001.HK"), "0001.HK")

    def test_invalid_input_still_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _resolve_and_normalize_input("not-a-code")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
