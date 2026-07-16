# -*- coding: utf-8 -*-
"""Helpers for parsing the user-facing STOCK_LIST value."""

from __future__ import annotations

import re
from typing import List

_STOCK_LIST_SEPARATOR_RE = re.compile(r"[\s,;\uFF0C\u3001\uFF1B]+")


def split_stock_list(value: str) -> List[str]:
    """Split STOCK_LIST values on common copy/paste separators."""
    return [
        item.strip()
        for item in _STOCK_LIST_SEPARATOR_RE.split(value or "")
        if item.strip()
    ]


def serialize_stock_list(value: str) -> str:
    """Return STOCK_LIST in the canonical comma-separated storage form."""
    return ",".join(split_stock_list(value))
