"""Shared stock-list identity and optimistic edits for watchlist writers."""

from __future__ import annotations

import re
from typing import Callable, TypeVar

from data_provider.base import normalize_stock_code
from data_provider.us_index_mapping import normalize_us_hyphen_symbol
from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from src.services.system_config_service import ConfigConflictError, SystemConfigService

_EditResult = TypeVar("_EditResult")


def canonicalize_watchlist_code(code: str) -> str:
    """Preserve registered index identities and normalize stock-code aliases."""
    target = parse_analysis_target(code)
    if target.asset_type == ParseStatus.INDEX:
        return target.canonical_id
    return _normalize_watchlist_stock_code(code)


def _normalize_watchlist_stock_code(code: str) -> str:
    return normalize_us_hyphen_symbol(code) or normalize_stock_code(code).upper()


def watchlist_match_key(code: str) -> str:
    target = parse_analysis_target(code)
    if target.asset_type == ParseStatus.INDEX:
        return f"index:{target.canonical_id}"
    normalized = _normalize_watchlist_stock_code(code)
    if re.fullmatch(r"\d{5}", normalized):
        normalized = f"HK{normalized}"
    return f"stock:{normalized}"


def edit_watchlist(
    service: SystemConfigService,
    edit: Callable[[list[str]], _EditResult],
) -> tuple[list[str], _EditResult]:
    """Apply an in-place edit to the latest list, retrying conflicting writes."""
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            codes, version = service.get_watchlist_snapshot()
            updated_codes = codes.copy()
            result = edit(updated_codes)
            if updated_codes != codes:
                # A blank value falls back to each worker's process environment.
                # A separator-only value represents an explicitly empty list.
                value = ",".join(updated_codes) if updated_codes else ","
                service.update(
                    config_version=version,
                    items=[{"key": "STOCK_LIST", "value": value}],
                    reload_now=True,
                    expected_watchlist=codes,
                )
        except ConfigConflictError:
            if attempt == max_attempts:
                raise
        else:
            return updated_codes, result
