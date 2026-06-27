# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, Optional

from src.data.stock_mapping import is_meaningful_stock_name
from src.services.market_symbol_utils import get_suffix_market, suffix_base_lookup_allowed
from src.services.stock_index_remote_service import (
    get_remote_stock_index_cache_path,
    is_valid_remote_stock_index_file,
    validate_stock_index_payload,
)

logger = logging.getLogger(__name__)

_STOCK_INDEX_FILENAME = "stocks.index.json"
_STOCK_INDEX_CACHE: Dict[str, str] | None = None
_STOCK_CODE_LOOKUP_CACHE: Dict[str, str] | None = None
_REMOTE_INDEX_VALIDITY_CACHE: tuple[Path, float, int, bool] | None = None
_STOCK_INDEX_CACHE_LOCK = RLock()


def get_stock_index_candidate_paths() -> tuple[Path, ...]:
    """Return the supported locations for the generated stock index."""
    repo_root = Path(__file__).resolve().parents[2]
    return (
        get_remote_stock_index_cache_path(),
        repo_root / "apps" / "dsa-web" / "public" / _STOCK_INDEX_FILENAME,
        repo_root / "static" / _STOCK_INDEX_FILENAME,
    )


def _same_path(left: Path, right: Path) -> bool:
    return left == right or left.resolve() == right.resolve()


def _add_lookup_key(keys: set[str], value: str) -> None:
    candidate = str(value or "").strip()
    if not candidate:
        return
    keys.add(candidate)
    keys.add(candidate.upper())


def _build_lookup_keys(canonical_code: str, display_code: str) -> Iterable[str]:
    keys: set[str] = set()
    _add_lookup_key(keys, canonical_code)
    _add_lookup_key(keys, display_code)

    canonical_upper = str(canonical_code or "").strip().upper()
    display_upper = str(display_code or "").strip().upper()

    if "." in canonical_upper:
        base, suffix = canonical_upper.rsplit(".", 1)
        if suffix in {"SH", "SZ", "SS", "BJ"} and base.isdigit():
            _add_lookup_key(keys, base)
        elif suffix == "HK" and base.isdigit() and 1 <= len(base) <= 5:
            digits = base.zfill(5)
            _add_lookup_key(keys, digits)
            _add_lookup_key(keys, f"HK{digits}")

    for candidate in (canonical_upper, display_upper):
        if candidate.startswith("HK"):
            digits = candidate[2:]
            if digits.isdigit() and 1 <= len(digits) <= 5:
                digits = digits.zfill(5)
                _add_lookup_key(keys, digits)
                _add_lookup_key(keys, f"HK{digits}")

    return keys


def _load_stock_index_payload(index_path: Path) -> list:
    with index_path.open("r", encoding="utf-8") as fh:
        raw_items = json.load(fh)

    if not isinstance(raw_items, list):
        raise ValueError(
            f"Unexpected {_STOCK_INDEX_FILENAME} payload type: {type(raw_items).__name__}"
        )
    return raw_items


def _build_stock_name_map(raw_items: list) -> Dict[str, str]:
    stock_name_map: Dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, list) or len(item) < 3:
            continue

        canonical_code, display_code, name_zh = item[0], item[1], item[2]
        if not is_meaningful_stock_name(name_zh, str(display_code or canonical_code or "")):
            continue

        for key in _build_lookup_keys(str(canonical_code or ""), str(display_code or "")):
            stock_name_map[key] = str(name_zh).strip()

    return stock_name_map


def _add_code_lookup(
    lookup: dict[str, set[str]],
    key: str,
    canonical_code: str,
) -> None:
    candidate = str(key or "").strip().upper()
    canonical = str(canonical_code or "").strip()
    if not candidate or not canonical:
        return
    lookup.setdefault(candidate, set()).add(canonical)


def _is_jp_kr_index_code(code: str) -> bool:
    """Return True for index-backed JP/KR suffix symbols eligible for lookup."""
    return get_suffix_market(code) in {"jp", "kr"}


def _build_stock_code_lookup(raw_items: list) -> Dict[str, str]:
    exact_lookup: dict[str, set[str]] = {}
    suffix_base_lookup: dict[str, set[str]] = {}

    for item in raw_items:
        if not isinstance(item, list) or len(item) < 2:
            continue

        canonical_code = str(item[0] or "").strip()
        display_code = str(item[1] or "").strip()
        if not canonical_code:
            continue
        if not _is_jp_kr_index_code(canonical_code):
            continue
        if len(item) > 8 and item[8] is False:
            continue

        _add_code_lookup(exact_lookup, canonical_code, canonical_code)
        _add_code_lookup(exact_lookup, display_code, canonical_code)

        canonical_upper = canonical_code.upper()
        if "." in canonical_upper and suffix_base_lookup_allowed(canonical_upper):
            base, _suffix = canonical_upper.rsplit(".", 1)
            if base.isdigit():
                _add_code_lookup(suffix_base_lookup, base, canonical_code)

    result: Dict[str, str] = {}
    for lookup in (exact_lookup, suffix_base_lookup):
        for key, codes in lookup.items():
            if key in result:
                continue
            if len(codes) == 1:
                result[key] = next(iter(codes))
    return result


def _load_stock_index_file(index_path: Path) -> Dict[str, str]:
    return _build_stock_name_map(_load_stock_index_payload(index_path))


def _load_remote_stock_index_file(index_path: Path) -> Dict[str, str]:
    raw_items = _load_stock_index_payload(index_path)
    validate_stock_index_payload(raw_items)
    return _build_stock_name_map(raw_items)


def _get_stock_index_signature(index_path: Path) -> tuple[float, int] | None:
    try:
        stat_result = index_path.stat()
    except OSError as exc:
        logger.debug("[股票名称] 读取股票索引元数据失败 %s: %s", index_path, exc)
        return None
    if not index_path.is_file():
        return None
    return stat_result.st_mtime, stat_result.st_size


def _get_fresh_stock_index_candidates(
    candidate_paths: Iterable[Path],
    remote_cache_path: Path,
) -> tuple[Path, ...]:
    paths = tuple(candidate_paths)
    candidates: list[tuple[tuple[float, int], Path]] = []

    for position, candidate_path in enumerate(paths):
        signature = _get_stock_index_signature(candidate_path)
        if signature is None:
            continue

        mtime, _size = signature
        tie_breaker = 0 if _same_path(candidate_path, remote_cache_path) else len(paths) - position
        candidates.append(((mtime, tie_breaker), candidate_path))

    return tuple(path for _sort_key, path in sorted(candidates, reverse=True))


def _is_remote_stock_index_cache_usable(
    index_path: Path,
    remote_cache_path: Path,
    signature: tuple[float, int],
) -> bool:
    global _REMOTE_INDEX_VALIDITY_CACHE

    if not _same_path(index_path, remote_cache_path):
        return True

    mtime, size = signature
    cached = _REMOTE_INDEX_VALIDITY_CACHE
    if cached is not None and cached[:3] == (index_path, mtime, size):
        return cached[3]

    is_valid = is_valid_remote_stock_index_file(index_path)
    _REMOTE_INDEX_VALIDITY_CACHE = (index_path, mtime, size, is_valid)
    return is_valid


def find_existing_stock_index_path(
    candidate_paths: Optional[Iterable[Path]] = None,
    *,
    remote_cache_path: Optional[Path] = None,
) -> Path | None:
    """Return the newest usable stock index across remote and bundled candidates."""
    paths = tuple(candidate_paths) if candidate_paths is not None else get_stock_index_candidate_paths()
    remote_path = remote_cache_path or get_remote_stock_index_cache_path()

    for candidate_path in _get_fresh_stock_index_candidates(paths, remote_path):
        signature = _get_stock_index_signature(candidate_path)
        if signature is None:
            continue
        if not _is_remote_stock_index_cache_usable(candidate_path, remote_path, signature):
            continue

        return candidate_path

    return None


def get_stock_name_index_map() -> Dict[str, str]:
    """Lazily load and cache the generated stock-name index."""
    global _STOCK_INDEX_CACHE

    if _STOCK_INDEX_CACHE is not None:
        return _STOCK_INDEX_CACHE

    with _STOCK_INDEX_CACHE_LOCK:
        if _STOCK_INDEX_CACHE is not None:
            return _STOCK_INDEX_CACHE

        remote_path = get_remote_stock_index_cache_path()
        for index_path in _get_fresh_stock_index_candidates(get_stock_index_candidate_paths(), remote_path):
            try:
                if _same_path(index_path, remote_path):
                    _STOCK_INDEX_CACHE = _load_remote_stock_index_file(index_path)
                else:
                    _STOCK_INDEX_CACHE = _load_stock_index_file(index_path)
                logger.debug(
                    "[股票名称] 已加载前端股票索引映射: %s (%d 条)",
                    index_path,
                    len(_STOCK_INDEX_CACHE),
                )
                return _STOCK_INDEX_CACHE
            except (OSError, TypeError, ValueError) as exc:
                logger.debug("[股票名称] 读取股票索引失败 %s: %s", index_path, exc)

        _STOCK_INDEX_CACHE = {}
        return _STOCK_INDEX_CACHE


def get_index_stock_name(stock_code: str) -> str | None:
    """Resolve a stock name from the generated frontend stock index."""
    code = str(stock_code or "").strip()
    if not code:
        return None

    stock_name_map = get_stock_name_index_map()
    for key in _build_lookup_keys(code, code):
        name = stock_name_map.get(key)
        if is_meaningful_stock_name(name, code):
            return name

    return None


def resolve_index_stock_code(query: str) -> str | None:
    """Resolve an input code against the stock index pool.

    Exact canonical/display-code matches win first. Bare JP/KR base-code matches
    are accepted only when unambiguous, so ``005930`` can resolve to
    ``005930.KS`` when that is the only indexed match.
    """
    code = str(query or "").strip().upper()
    if not code:
        return None

    return get_stock_code_index_map().get(code)


def get_stock_code_index_map() -> Dict[str, str]:
    """Lazily load and cache generated stock-code lookup entries."""
    global _STOCK_CODE_LOOKUP_CACHE

    if _STOCK_CODE_LOOKUP_CACHE is not None:
        return _STOCK_CODE_LOOKUP_CACHE

    with _STOCK_INDEX_CACHE_LOCK:
        if _STOCK_CODE_LOOKUP_CACHE is not None:
            return _STOCK_CODE_LOOKUP_CACHE

        merged_lookup: Dict[str, str] = {}
        remote_path = get_remote_stock_index_cache_path()
        for index_path in _get_fresh_stock_index_candidates(get_stock_index_candidate_paths(), remote_path):
            try:
                raw_items = _load_stock_index_payload(index_path)
                if _same_path(index_path, remote_path):
                    validate_stock_index_payload(raw_items)
                for key, value in _build_stock_code_lookup(raw_items).items():
                    merged_lookup.setdefault(key, value)
            except (OSError, TypeError, ValueError) as exc:
                logger.debug("[鑲＄エ绱㈠紩] 瑙ｆ瀽浠ｇ爜绱㈠紩澶辫触 %s: %s", index_path, exc)

        _STOCK_CODE_LOOKUP_CACHE = merged_lookup
        return _STOCK_CODE_LOOKUP_CACHE


def _resolve_index_stock_code_uncached(query: str) -> str | None:
    code = str(query or "").strip().upper()
    if not code:
        return None

    remote_path = get_remote_stock_index_cache_path()
    for index_path in _get_fresh_stock_index_candidates(get_stock_index_candidate_paths(), remote_path):
        try:
            raw_items = _load_stock_index_payload(index_path)
            if _same_path(index_path, remote_path):
                validate_stock_index_payload(raw_items)
            resolved = _build_stock_code_lookup(raw_items).get(code)
            if resolved:
                return resolved
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("[股票索引] 解析代码索引失败 %s: %s", index_path, exc)

    return None


def clear_stock_index_cache() -> None:
    """Clear the in-process stock index lookup cache."""
    global _REMOTE_INDEX_VALIDITY_CACHE, _STOCK_INDEX_CACHE, _STOCK_CODE_LOOKUP_CACHE
    with _STOCK_INDEX_CACHE_LOCK:
        _STOCK_INDEX_CACHE = None
        _STOCK_CODE_LOOKUP_CACHE = None
        _REMOTE_INDEX_VALIDITY_CACHE = None


def _clear_stock_index_cache_for_tests() -> None:
    clear_stock_index_cache()
