# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
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
_EXPLICIT_INDEX_ALIAS_RE = re.compile(
    r"^(?:(?:sh|sz|csi)\d{6}|\d{6}\.(?:sh|sz|csi))$"
)


def _normalize_index_identity_key(value: object) -> str:
    """Normalize an identity key to one resolver identity form.

    ``sh``/``sz`` prefix and ``{code}.SH`` / ``{code}.SZ`` suffix collapse to
    the canonical lowercase-prefixed key. CSI is deliberately **not**
    collapsed: ``csi{code}`` (prefix) and ``{code}.CSI`` (suffix) are kept
    distinct so an unregistered ``csi`` prefix never conflates with a
    registered ``{code}.CSI`` alias — mirroring ``stock_list_parser``.
    """
    normalized = unicodedata.normalize(
        "NFKC", str(value or "")
    ).strip().casefold()
    prefix_match = re.fullmatch(r"(sh|sz)(\d{6})", normalized)
    if prefix_match:
        return f"{prefix_match.group(1)}{prefix_match.group(2)}"
    suffix_match = re.fullmatch(r"(\d{6})\.(sh|sz)", normalized)
    if suffix_match:
        return f"{suffix_match.group(2)}{suffix_match.group(1)}"
    return normalized
_STOCK_INDEX_CACHE: Dict[str, str] | None = None
_STOCK_CODE_LOOKUP_CACHE: Dict[str, str] | None = None
_STOCK_CODE_CANDIDATES_CACHE: Dict[str, tuple[str, ...]] | None = None
_ACTIVE_INDEX_ROWS_CACHE: list | None = None
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


def _build_stock_code_candidates(raw_items: list) -> dict[str, set[str]]:
    candidates: dict[str, set[str]] = {}

    for item in raw_items:
        if not isinstance(item, list) or len(item) < 2:
            continue

        canonical_code = str(item[0] or "").strip().upper()
        display_code = str(item[1] or "").strip().upper()
        if not canonical_code:
            continue
        if len(item) > 8 and item[8] is False:
            continue

        indexed_market = (
            str(item[6] or "").strip().lower()
            if len(item) > 6
            else ""
        )
        if indexed_market not in {"cn", "hk", "jp", "kr"}:
            indexed_market = get_suffix_market(canonical_code) or ""
        if indexed_market not in {"cn", "hk", "jp", "kr"}:
            continue

        if indexed_market in {"jp", "kr"}:
            _add_code_lookup(candidates, canonical_code, canonical_code)
            _add_code_lookup(candidates, display_code, canonical_code)
            if "." in canonical_code and suffix_base_lookup_allowed(canonical_code):
                base, _suffix = canonical_code.rsplit(".", 1)
                if base.isdigit():
                    _add_code_lookup(candidates, base, canonical_code)
        elif indexed_market == "hk":
            base = canonical_code.removesuffix(".HK")
            if base.isdigit():
                _add_code_lookup(candidates, base.lstrip("0") or "0", canonical_code)
        elif indexed_market == "cn":
            base = canonical_code.rsplit(".", 1)[0]
            if base.isdigit() and len(base) == 6:
                _add_code_lookup(candidates, base, canonical_code)

    return candidates


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

    candidates = resolve_index_stock_code_candidates(code)
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    return candidate if _is_jp_kr_index_code(candidate) else None


def resolve_index_stock_code_candidates(query: str) -> tuple[str, ...]:
    """Return active indexed identities sharing one supported code alias."""
    code = str(query or "").strip().upper()
    if not code:
        return ()
    return get_stock_code_candidates_map().get(code, ())


def get_stock_code_candidates_map() -> Dict[str, tuple[str, ...]]:
    """Lazily load all indexed identities needed to detect bare-code ambiguity."""
    global _STOCK_CODE_CANDIDATES_CACHE

    if _STOCK_CODE_CANDIDATES_CACHE is not None:
        return _STOCK_CODE_CANDIDATES_CACHE

    with _STOCK_INDEX_CACHE_LOCK:
        if _STOCK_CODE_CANDIDATES_CACHE is not None:
            return _STOCK_CODE_CANDIDATES_CACHE

        merged_candidates: dict[str, set[str]] = {}
        remote_path = get_remote_stock_index_cache_path()
        for index_path in _get_fresh_stock_index_candidates(
            get_stock_index_candidate_paths(),
            remote_path,
        ):
            try:
                raw_items = _load_stock_index_payload(index_path)
                if _same_path(index_path, remote_path):
                    validate_stock_index_payload(raw_items)
                for key, values in _build_stock_code_candidates(raw_items).items():
                    merged_candidates.setdefault(key, set()).update(values)
            except (OSError, TypeError, ValueError) as exc:
                logger.debug(
                    "[股票索引] 解析代码候选失败 %s: %s",
                    index_path,
                    exc,
                )

        _STOCK_CODE_CANDIDATES_CACHE = {
            key: tuple(sorted(values))
            for key, values in merged_candidates.items()
        }
        return _STOCK_CODE_CANDIDATES_CACHE


def get_stock_code_index_map() -> Dict[str, str]:
    """Lazily load and cache generated stock-code lookup entries."""
    global _STOCK_CODE_LOOKUP_CACHE

    if _STOCK_CODE_LOOKUP_CACHE is not None:
        return _STOCK_CODE_LOOKUP_CACHE

    with _STOCK_INDEX_CACHE_LOCK:
        if _STOCK_CODE_LOOKUP_CACHE is not None:
            return _STOCK_CODE_LOOKUP_CACHE

        merged_lookup = {
            key: values[0]
            for key, values in get_stock_code_candidates_map().items()
            if len(values) == 1 and _is_jp_kr_index_code(values[0])
        }

        _STOCK_CODE_LOOKUP_CACHE = merged_lookup
        return _STOCK_CODE_LOOKUP_CACHE


def _load_active_index_rows() -> list:
    """Load and cache the active ``assetType=index`` rows from the best candidate.

    Returns raw compressed tuples (no parser type dependency) so the loader
    stays free of a circular import with ``stock_list_parser``. Each candidate
    must pass base + semantic validation before its index rows are used.

    Non-regression guard: when the bundled candidate is a valid baseline, every
    OTHER candidate — the remote cache AND the legacy ``static`` fallback — must
    be a legal superset of the bundled active-index canonical set to be selected.
    A candidate that drops any bundled active index canonical is skipped
    (WARNING) in favour of the bundled candidate, so a stale or partial
    non-bundled file can never bypass the bundled baseline when the remote cache
    is missing/invalid.
    """
    global _ACTIVE_INDEX_ROWS_CACHE

    if _ACTIVE_INDEX_ROWS_CACHE is not None:
        return _ACTIVE_INDEX_ROWS_CACHE

    with _STOCK_INDEX_CACHE_LOCK:
        if _ACTIVE_INDEX_ROWS_CACHE is not None:
            return _ACTIVE_INDEX_ROWS_CACHE

        remote_path = get_remote_stock_index_cache_path()
        candidate_paths = get_stock_index_candidate_paths()
        candidates = _get_fresh_stock_index_candidates(candidate_paths, remote_path)

        # First pass: find the bundled candidate's active index canonical set
        # as the non-regression baseline. The bundled candidate is the
        # ``apps/dsa-web/public/stocks.index.json`` path (identified from the
        # declared candidate order, not the first non-remote candidate ordered
        # by mtime), and its index rows must pass semantic validation before
        # they become the baseline.
        bundled_path = _get_bundled_stock_index_path(candidate_paths, remote_path)
        bundled_rows: list | None = None
        bundled_canonicals: set[str] | None = None
        if bundled_path is not None:
            try:
                raw_items = _load_stock_index_payload(bundled_path)
                validate_stock_index_payload(raw_items, min_items=0)
                rows = _extract_active_index_rows(raw_items)
                if rows:
                    _validate_index_rows_semantics(
                        rows, _extract_active_non_index_rows(raw_items)
                    )
                    bundled_rows = rows
                    bundled_canonicals = {str(r[0]) for r in rows}
            except (OSError, TypeError, ValueError) as exc:
                logger.debug("[股票索引] 解析 bundled 指数行失败 %s: %s", bundled_path, exc)

        # Second pass: pick the best candidate (remote preferred when it is a
        # legal superset of the bundled baseline).
        for index_path in candidates:
            try:
                raw_items = _load_stock_index_payload(index_path)
                if _same_path(index_path, remote_path):
                    validate_stock_index_payload(raw_items)
                else:
                    validate_stock_index_payload(raw_items, min_items=0)
                rows = _extract_active_index_rows(raw_items)
                if not rows:
                    continue
                _validate_index_rows_semantics(
                    rows, _extract_active_non_index_rows(raw_items)
                )
                # Non-regression guard: when the bundled candidate is a valid
                # baseline, every OTHER candidate (remote cache or legacy
                # ``static`` fallback) must be a legal superset of the bundled
                # active-index canonical set. A candidate that drops any
                # bundled baseline canonical is skipped (WARNING) so a stale
                # or partial legacy-static file can never bypass the bundled
                # baseline when the remote cache is missing/invalid.
                if bundled_canonicals and bundled_path is not None and not _same_path(index_path, bundled_path):
                    candidate_canonicals = {str(r[0]) for r in rows}
                    missing = bundled_canonicals - candidate_canonicals
                    if missing:
                        logger.warning(
                            "[股票索引] 指数候选 %s 缺少 bundled baseline canonical: %s — 回退 bundled",
                            index_path,
                            sorted(missing),
                        )
                        continue
                _ACTIVE_INDEX_ROWS_CACHE = rows
                return rows
            except (OSError, TypeError, ValueError) as exc:
                logger.debug("[股票索引] 解析指数行失败 %s: %s", index_path, exc)

        # All candidates failed or were skipped — empty registry + WARNING.
        logger.warning("[股票索引] 所有指数候选均失败，指数注册表为空")
        _ACTIVE_INDEX_ROWS_CACHE = []
        return _ACTIVE_INDEX_ROWS_CACHE


def _get_bundled_stock_index_path(
    candidate_paths: Iterable[Path],
    remote_path: Path,
) -> Path | None:
    """Return the bundled ``apps/dsa-web/public/stocks.index.json`` path.

    The bundled candidate is the deterministic non-remote baseline for the
    remote non-regression check, independent of mtime ordering. It is the
    declared ``apps/dsa-web/public`` candidate (the non-remote, non-legacy
    ``static`` candidate in the declared candidate order), not the remote cache
    and not the legacy ``static`` fallback.
    """
    for candidate in candidate_paths:
        if _same_path(candidate, remote_path):
            continue
        if candidate.as_posix().endswith("static/stocks.index.json"):
            continue
        if candidate.is_file():
            return candidate
    return None


def _extract_active_index_rows(raw_items: list) -> list:
    """Return the active ``assetType=index`` rows from a raw payload."""
    rows = []
    for item in raw_items:
        if not isinstance(item, list) or len(item) < 10:
            continue
        if item[7] != "index":
            continue
        if item[8] is not True:
            continue
        rows.append(item)
    return rows


def _extract_active_non_index_rows(raw_items: list) -> list:
    """Return the active stock/ETF rows from a raw payload (for collision checks)."""
    rows = []
    for item in raw_items:
        if not isinstance(item, list) or len(item) < 10:
            continue
        if str(item[7] or "").strip() == "index":
            continue
        if item[8] is not True:
            continue
        rows.append(item)
    return rows


def _validate_index_rows_semantics(rows: list, non_index_rows: list | None = None) -> None:
    """Semantic validation for active index rows (implementation-contracts §Semantic Validation).

    Raises ``ValueError`` on any identity/alias/stock-index conflict so a
    malformed candidate is rejected rather than silently loaded. ``non_index_rows``
    carries the active stock/ETF rows from the same payload so an index
    canonical/display/alias that collides with a stock/ETF identity after
    normalization is rejected.
    """
    canonical_map: dict[str, str] = {}
    resolver_map: dict[str, str] = {}

    # Active stock/ETF identity keys an index explicit key must never collide with.
    stock_keys: dict[str, str] = {}
    for row in non_index_rows or []:
        stock_canonical = str(row[0] or "").strip()
        for key in [row[0], row[1]] + list(row[5] if isinstance(row[5], list) else []):
            norm_key = _normalize_index_identity_key(key)
            if norm_key:
                stock_keys.setdefault(norm_key, stock_canonical)

    for row in rows:
        canonical = str(row[0] or "").strip()
        display = str(row[1] or "").strip()
        name = str(row[2] or "").strip()
        pinyin_full = row[3]
        pinyin_abbr = row[4]
        market = str(row[6] or "").strip()
        asset_type = str(row[7] or "").strip()
        active = row[8]
        popularity = row[9]
        aliases = row[5]

        if not re.fullmatch(r"(sh|sz|csi)\d{6}", canonical):
            raise ValueError(f"index canonical must match ^(sh|sz|csi)\\d{{6}}$: {canonical!r}")
        namespace = canonical[:3] if canonical.startswith("csi") else canonical[:2]
        if namespace in {"sh", "sz"}:
            if display != canonical:
                raise ValueError(f"SH/SZ index display must equal canonical: {canonical!r}")
        elif namespace == "csi":
            if display != f"{canonical[3:]}.CSI":
                raise ValueError(f"CSI index display must be {canonical[3:]}.CSI: {display!r}")
        if market != "CN":
            raise ValueError(f"index market must be CN: {canonical!r}")
        if asset_type != "index":
            raise ValueError(f"index asset_type must be index: {canonical!r}")
        if active is not True:
            raise ValueError(f"index active must be True: {canonical!r}")
        if not name:
            raise ValueError(f"index name must be non-empty: {canonical!r}")
        if (
            not isinstance(pinyin_full, str)
            or not pinyin_full.strip()
            or not isinstance(pinyin_abbr, str)
            or not pinyin_abbr.strip()
        ):
            raise ValueError(f"index pinyin fields must be non-empty: {canonical!r}")
        if not isinstance(aliases, list):
            raise ValueError(f"index aliases must be a list: {canonical!r}")
        if (
            isinstance(popularity, bool)
            or not isinstance(popularity, int)
            or not math.isfinite(float(popularity))
            or popularity < 0
        ):
            raise ValueError(f"index popularity must be a non-negative integer: {canonical!r}")

        norm_canonical = _normalize_index_identity_key(canonical)
        if norm_canonical in canonical_map:
            raise ValueError(f"duplicate index canonical: {canonical!r}")
        canonical_map[norm_canonical] = canonical

        seen_aliases: set[str] = set()
        for alias in aliases:
            norm_alias = _normalize_index_identity_key(alias)
            if norm_alias in seen_aliases:
                raise ValueError(
                    f"duplicate index alias after normalization for {canonical!r}: {alias!r}"
                )
            seen_aliases.add(norm_alias)
            if norm_alias.isdigit():
                raise ValueError(f"bare numeric display/alias rejected for index: {alias!r}")
            if not _EXPLICIT_INDEX_ALIAS_RE.fullmatch(norm_alias):
                raise ValueError(
                    f"index aliases must use an explicit code form: {alias!r}"
                )

        for key in [canonical, display] + aliases:
            norm_key = _normalize_index_identity_key(key)
            if not norm_key:
                continue
            if norm_key.isdigit():
                raise ValueError(f"bare numeric display/alias rejected for index: {key!r}")
            if norm_key in resolver_map and resolver_map[norm_key] != canonical:
                raise ValueError(
                    f"index resolver key {key!r} maps to multiple canonicals "
                    f"({resolver_map[norm_key]} vs {canonical})"
                )
            if norm_key in stock_keys:
                raise ValueError(
                    f"index resolver key {key!r} collides with active stock/ETF "
                    f"identity {stock_keys[norm_key]!r}"
                )
            resolver_map[norm_key] = canonical


def clear_stock_index_cache() -> None:
    """Clear the in-process stock index lookup cache."""
    global _REMOTE_INDEX_VALIDITY_CACHE
    global _STOCK_CODE_CANDIDATES_CACHE, _STOCK_CODE_LOOKUP_CACHE, _STOCK_INDEX_CACHE
    global _ACTIVE_INDEX_ROWS_CACHE
    with _STOCK_INDEX_CACHE_LOCK:
        _STOCK_INDEX_CACHE = None
        _STOCK_CODE_LOOKUP_CACHE = None
        _STOCK_CODE_CANDIDATES_CACHE = None
        _ACTIVE_INDEX_ROWS_CACHE = None
        _REMOTE_INDEX_VALIDITY_CACHE = None


def _clear_stock_index_cache_for_tests() -> None:
    clear_stock_index_cache()
