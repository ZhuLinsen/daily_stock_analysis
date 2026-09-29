# -*- coding: utf-8 -*-
"""Read real stock holdings from a Futu OpenD instance."""

from __future__ import annotations

import ipaddress
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from data_provider.us_index_mapping import is_us_stock_code
from src.services.stock_code_utils import normalize_code


logger = logging.getLogger(__name__)


class FutuPortfolioError(RuntimeError):
    """Raised when a Futu portfolio cannot be resolved safely."""


@dataclass(frozen=True)
class _FutuAccount:
    """Identify one usable real Futu securities account."""

    acc_id: int
    security_firm: Any


@dataclass(frozen=True)
class _FutuApi:
    """Hold the imported Futu SDK surface used by portfolio loading."""

    OpenQuoteContext: Any
    OpenSecTradeContext: Any
    Market: Any
    RET_OK: Any
    SecurityFirm: Any
    SecurityType: Any
    TrdEnv: Any
    TrdMarket: Any


_SUPPORTED_ACCOUNT_ROLES = frozenset({"NORMAL", "MASTER"})
_SUPPORTED_ANALYSIS_MARKETS = frozenset({"US", "HK", "SH", "SZ"})
_UNKNOWN_SECURITY_TYPES = frozenset({"", "N/A", "NONE", "UNKNOWN", "NAN"})
_STATIC_INFO_BATCH_SIZE = 100


def _load_futu_api() -> _FutuApi:
    """Import the supported Futu SDK surface or raise an actionable error."""

    try:
        from futu import (
            Market,
            OpenQuoteContext,
            OpenSecTradeContext,
            RET_OK,
            SecurityFirm,
            SecurityType,
            TrdEnv,
            TrdMarket,
        )
    except ImportError as exc:
        raise FutuPortfolioError(
            "未安装 Futu OpenAPI SDK；请先执行 "
            "`pip install \"futu-api==10.8.6808\"`。"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - SDK import initializes its file logger
        raise FutuPortfolioError(f"加载 Futu OpenAPI SDK 失败: {exc}") from exc

    return _FutuApi(
        OpenQuoteContext=OpenQuoteContext,
        OpenSecTradeContext=OpenSecTradeContext,
        Market=Market,
        RET_OK=RET_OK,
        SecurityFirm=SecurityFirm,
        SecurityType=SecurityType,
        TrdEnv=TrdEnv,
        TrdMarket=TrdMarket,
    )


def _enum_text(value: Any) -> str:
    """Normalize SDK enum-like values for stable comparisons."""

    if value is None:
        return ""
    name = getattr(value, "name", None)
    return str(name if name is not None else value).strip().upper()


def _iter_rows(data: Any, operation: str) -> Iterable[Any]:
    """Iterate the pandas-style table returned by the pinned Futu SDK."""

    iterrows = getattr(data, "iterrows", None)
    if not callable(iterrows):
        raise FutuPortfolioError(f"{operation}返回了非表格数据")
    return (row for _, row in iterrows())


def _safe_close(context: Any) -> None:
    """Close an SDK context without masking the primary operation result."""

    if context is None:
        return
    try:
        context.close()
    except Exception:  # pragma: no cover - closing is best effort
        logger.debug("关闭 Futu OpenD 连接失败", exc_info=True)


def _connection_settings() -> tuple[str, int]:
    """Return the validated IPv4 OpenD host and port from environment settings."""

    host = (os.getenv("FUTU_OPEND_HOST") or "127.0.0.1").strip()
    raw_port = (os.getenv("FUTU_OPEND_PORT") or "11111").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise FutuPortfolioError(f"FUTU_OPEND_PORT 不是有效端口: {raw_port!r}") from exc
    if not host or not 1 <= port <= 65535:
        raise FutuPortfolioError(f"Futu OpenD 地址无效: {host!r}:{port}")

    address_text = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        address = None
    if address is not None and address.version != 4:
        raise FutuPortfolioError(
            "futu-api==10.8.6808 的网络层仅支持 IPv4；"
            f"FUTU_OPEND_HOST 当前为 {host!r}，请改用 IPv4 地址或可解析到 IPv4 的主机名。"
        )
    return host, port


def _configured_account_id() -> Optional[int]:
    """Return the optional configured real account ID."""

    value = (os.getenv("FUTU_ACC_ID") or "").strip()
    if not value:
        return None
    try:
        account_id = int(value)
    except ValueError as exc:
        raise FutuPortfolioError("FUTU_ACC_ID 必须是正整数账户 ID") from exc
    if account_id <= 0:
        raise FutuPortfolioError("FUTU_ACC_ID 必须是正整数账户 ID")
    return account_id


def _configured_security_firm(api: _FutuApi) -> Any:
    """Resolve one firm, defaulting to the SDK's official auto-detection mode."""

    name = (os.getenv("FUTU_SECURITY_FIRM") or "NONE").strip().upper()
    firm = getattr(api.SecurityFirm, name, None)
    if firm is None:
        raise FutuPortfolioError(f"不支持的 FUTU_SECURITY_FIRM: {name}")
    return firm


def _discover_real_accounts(api: _FutuApi, host: str, port: int) -> List[_FutuAccount]:
    """Discover explicitly ACTIVE NORMAL or MASTER REAL accounts."""

    accounts: List[_FutuAccount] = []
    seen_ids = set()
    requested_acc_id = _configured_account_id()
    security_firm = _configured_security_firm(api)
    context = None
    try:
        context = api.OpenSecTradeContext(
            host=host,
            port=port,
            filter_trdmarket=api.TrdMarket.NONE,
            security_firm=security_firm,
        )
        ret, data = context.get_acc_list()
        if ret != api.RET_OK:
            raise FutuPortfolioError(f"查询 Futu 真实账户失败: {data}")
        for row in _iter_rows(data, "Futu 账户查询"):
            if _enum_text(row.get("trd_env")) != "REAL":
                continue
            if _enum_text(row.get("acc_status")) != "ACTIVE":
                continue
            if _enum_text(row.get("acc_role")) not in _SUPPORTED_ACCOUNT_ROLES:
                continue
            raw_acc_id = row.get("acc_id")
            try:
                acc_id = int(raw_acc_id)
                exact_integer = isinstance(raw_acc_id, str) or bool(
                    raw_acc_id == acc_id
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise FutuPortfolioError(
                    "Futu 账户查询返回了无效账户 ID"
                ) from exc
            if isinstance(raw_acc_id, bool) or not exact_integer or acc_id <= 0:
                raise FutuPortfolioError("Futu 账户查询返回了无效账户 ID")
            if acc_id in seen_ids:
                continue
            returned_firm_name = _enum_text(row.get("security_firm"))
            returned_firm = getattr(
                api.SecurityFirm,
                returned_firm_name,
                security_firm,
            )
            seen_ids.add(acc_id)
            accounts.append(_FutuAccount(acc_id=acc_id, security_firm=returned_firm))
    except FutuPortfolioError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate SDK/network failures
        raise FutuPortfolioError(f"查询 Futu 真实账户失败: {exc}") from exc
    finally:
        _safe_close(context)

    if requested_acc_id is not None:
        accounts = [account for account in accounts if account.acc_id == requested_acc_id]
        if not accounts:
            raise FutuPortfolioError(
                "FUTU_ACC_ID 未匹配到可用的真实证券账户；请检查账户 ID、券商和 OpenD 登录状态。"
            )

    if not accounts:
        raise FutuPortfolioError(
            "未找到状态为 ACTIVE 的 Futu REAL 普通或 MASTER 证券账户"
        )
    return accounts


def _load_position_codes(
    api: _FutuApi,
    host: str,
    port: int,
    accounts: Iterable[_FutuAccount],
) -> List[str]:
    """Load deduplicated non-zero LONG position codes from selected accounts."""

    codes: List[str] = []
    seen_codes = set()
    skipped_short_count = 0
    skipped_unknown_side_count = 0

    for account in accounts:
        context = None
        try:
            context = api.OpenSecTradeContext(
                host=host,
                port=port,
                filter_trdmarket=api.TrdMarket.NONE,
                security_firm=account.security_firm,
            )
            ret, data = context.position_list_query(
                trd_env=api.TrdEnv.REAL,
                acc_id=account.acc_id,
                refresh_cache=True,
            )
            if ret != api.RET_OK:
                raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {data}")
            for row in _iter_rows(data, "Futu 持仓查询"):
                position_side = _enum_text(row.get("position_side"))
                if position_side == "SHORT":
                    skipped_short_count += 1
                    continue
                if position_side != "LONG":
                    skipped_unknown_side_count += 1
                    continue
                raw_code = row.get("code")
                code = (
                    raw_code.strip().upper()
                    if isinstance(raw_code, str)
                    else ""
                )
                raw_quantity = row.get("qty")
                try:
                    if isinstance(raw_quantity, bool):
                        raise TypeError("boolean quantity")
                    quantity = float(raw_quantity)
                except (TypeError, ValueError) as exc:
                    suffix = f": {code}" if code else ""
                    raise FutuPortfolioError(f"Futu 持仓数量无效{suffix}") from exc
                if not math.isfinite(quantity):
                    suffix = f": {code}" if code else ""
                    raise FutuPortfolioError(f"Futu 持仓数量无效{suffix}")
                if quantity == 0:
                    continue
                if not isinstance(raw_code, str):
                    raise FutuPortfolioError("Futu 非零持仓返回了无效证券代码")
                if not code:
                    raise FutuPortfolioError("Futu 非零持仓返回了空证券代码")
                market, separator, symbol = code.partition(".")
                if not separator or not market or not symbol:
                    raise FutuPortfolioError(
                        f"Futu 非零持仓返回了无效证券代码: {code}"
                    )
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                codes.append(code)
        except FutuPortfolioError:
            raise
        except Exception as exc:  # noqa: BLE001 - translate SDK/network errors for CLI callers
            raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {exc}") from exc
        finally:
            _safe_close(context)

    if skipped_short_count:
        logger.info("已跳过 %d 个 Futu SHORT 空头持仓", skipped_short_count)
    if skipped_unknown_side_count:
        logger.warning(
            "已跳过 %d 个持仓方向不是 LONG 的 Futu 持仓",
            skipped_unknown_side_count,
        )
    return codes


def _market_prefix(code: str) -> str:
    """Extract the Futu market prefix from a qualified security code."""

    return code.split(".", 1)[0] if "." in code else ""


def _is_cn_b_share_code(code: str) -> bool:
    """Return whether a qualified Futu code is a Shanghai/Shenzhen B-share."""

    prefix, separator, symbol = code.partition(".")
    if not separator or not (symbol.isdigit() and len(symbol) == 6):
        return False
    return (prefix == "SH" and symbol.startswith("900")) or (
        prefix == "SZ" and symbol.startswith("200")
    )


def _to_analysis_code(futu_code: str) -> Optional[str]:
    """Convert a supported Futu code into the analysis pipeline format."""

    prefix, separator, symbol = futu_code.partition(".")
    if not separator or not symbol:
        return None
    prefix = prefix.upper()
    symbol = symbol.upper()
    if prefix == "US":
        normalized = normalize_code(symbol)
        if normalized == symbol and is_us_stock_code(normalized):
            return normalized
        return None
    if prefix == "HK":
        normalized = normalize_code(f"HK.{symbol}")
        return f"HK{normalized}" if normalized is not None else None
    if prefix in {"SH", "SZ"}:
        normalized = normalize_code(f"{prefix}.{symbol}")
        return normalized if normalized == symbol else None
    return None


def _filter_stock_codes(
    api: _FutuApi,
    host: str,
    port: int,
    position_codes: List[str],
) -> List[str]:
    """Keep A/HK/US stocks and report unsupported Futu market codes."""

    if not position_codes:
        return []

    grouped: dict[str, List[str]] = {}
    unsupported_codes: List[str] = []
    for code in position_codes:
        prefix = _market_prefix(code)
        if prefix not in _SUPPORTED_ANALYSIS_MARKETS or _is_cn_b_share_code(code):
            unsupported_codes.append(code)
            continue
        grouped.setdefault(prefix, []).append(code)

    if not grouped:
        logger.warning(
            "已跳过 %d 个当前分析流程不支持的 Futu 持仓: %s",
            len(unsupported_codes),
            ", ".join(unsupported_codes),
        )
        return []

    stock_codes = set()
    classified_codes = set()
    context = None
    try:
        context = api.OpenQuoteContext(host=host, port=port)
        for prefix, codes in grouped.items():
            market = getattr(api.Market, prefix, None)
            if market is None:
                unsupported_codes.extend(codes)
                continue
            for start in range(0, len(codes), _STATIC_INFO_BATCH_SIZE):
                batch = codes[start : start + _STATIC_INFO_BATCH_SIZE]
                ret, data = context.get_stock_basicinfo(
                    market,
                    stock_type=api.SecurityType.STOCK,
                    code_list=batch,
                )
                if ret != api.RET_OK:
                    raise FutuPortfolioError(
                        f"查询 Futu 持仓证券类型失败（{prefix}）: {data}"
                    )
                for row in _iter_rows(data, "Futu 证券类型查询"):
                    code = str(row.get("code", "") or "").strip().upper()
                    if not code:
                        continue
                    stock_type = _enum_text(row.get("stock_type"))
                    if stock_type in _UNKNOWN_SECURITY_TYPES:
                        continue
                    classified_codes.add(code)
                    if stock_type == "STOCK":
                        stock_codes.add(code)
    except FutuPortfolioError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate SDK/network errors for CLI callers
        raise FutuPortfolioError(f"查询 Futu 持仓证券类型失败: {exc}") from exc
    finally:
        _safe_close(context)

    missing_codes = [
        code
        for codes in grouped.values()
        for code in codes
        if code not in classified_codes
    ]
    if unsupported_codes:
        logger.warning(
            "已跳过 %d 个当前分析流程不支持的 Futu 持仓: %s",
            len(unsupported_codes),
            ", ".join(unsupported_codes),
        )
    if missing_codes:
        raise FutuPortfolioError(
            "无法确认证券类型的 Futu 持仓: " + ", ".join(missing_codes)
        )

    result: List[str] = []
    conversion_failures: List[str] = []
    for futu_code in position_codes:
        if futu_code not in stock_codes:
            continue
        analysis_code = _to_analysis_code(futu_code)
        if not analysis_code:
            conversion_failures.append(futu_code)
            continue
        if analysis_code not in result:
            result.append(analysis_code)
    if conversion_failures:
        raise FutuPortfolioError(
            "无法转换已确认的 Futu 正股代码到当前分析格式: "
            + ", ".join(conversion_failures)
        )
    return result


def load_futu_stock_codes() -> List[str]:
    """Return deduplicated analysis codes from all selected REAL Futu accounts.

    Only explicitly ACTIVE REAL accounts and Futu ``SecurityType.STOCK`` LONG
    positions with non-zero quantity are kept. ``FUTU_ACC_ID`` can select one
    account; otherwise NORMAL and MASTER accounts are merged. ``MASTER`` is an
    account role, while read-only describes this integration's query-only API
    calls. Firm discovery uses the SDK's ``SecurityFirm.NONE`` auto-detection
    unless ``FUTU_SECURITY_FIRM`` is explicitly set. Position data is always
    refreshed. Symbol conversion is limited to A/HK/US stocks; holdings from
    other Futu markets are logged with their codes and skipped.
    """
    api = _load_futu_api()
    host, port = _connection_settings()
    accounts = _discover_real_accounts(api, host, port)
    position_codes = _load_position_codes(api, host, port, accounts)
    stock_codes = _filter_stock_codes(api, host, port, position_codes)
    logger.info(
        "已从 Futu 真实账户加载 %d 只正股（账户数: %d，原始非零多头持仓数: %d）: %s",
        len(stock_codes),
        len(accounts),
        len(position_codes),
        ", ".join(stock_codes),
    )
    return stock_codes
