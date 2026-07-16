# -*- coding: utf-8 -*-
"""Read real stock holdings from a local Futu OpenD instance."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional


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
    SysConfig: Any
    TrdEnv: Any
    TrdMarket: Any


_SECURITY_FIRM_NAMES = (
    "NONE",
    "FUTUSECURITIES",
    "FUTUINC",
    "FUTUSG",
    "FUTUAU",
    "FUTUCA",
    "FUTUJP",
    "FUTUMY",
)
_SUPPORTED_ACCOUNT_ROLES = frozenset({"NORMAL", "MASTER"})
_SUPPORTED_ANALYSIS_MARKETS = frozenset({"US", "HK", "SH", "SZ", "JP"})
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
            SysConfig,
            TrdEnv,
            TrdMarket,
        )
    except ImportError as exc:
        raise FutuPortfolioError(
            "未安装 Futu OpenAPI SDK；请先执行 "
            "`pip install \"futu-api==10.8.6808\"`。"
        ) from exc

    return _FutuApi(
        OpenQuoteContext=OpenQuoteContext,
        OpenSecTradeContext=OpenSecTradeContext,
        Market=Market,
        RET_OK=RET_OK,
        SecurityFirm=SecurityFirm,
        SecurityType=SecurityType,
        SysConfig=SysConfig,
        TrdEnv=TrdEnv,
        TrdMarket=TrdMarket,
    )


def _enum_text(value: Any) -> str:
    """Normalize SDK enum-like values for stable comparisons."""

    if value is None:
        return ""
    name = getattr(value, "name", None)
    return str(name if name is not None else value).strip().upper()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read one field from mapping-like SDK or pandas rows."""

    if isinstance(row, dict):
        return row.get(key, default)
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _iter_rows(data: Any) -> Iterable[Any]:
    """Iterate over mapping, pandas, or generic iterable SDK payloads."""

    if data is None:
        return ()
    iterrows = getattr(data, "iterrows", None)
    if callable(iterrows):
        return (row for _, row in iterrows())
    if isinstance(data, dict):
        return (data,)
    return iter(data)


def _safe_close(context: Any) -> None:
    """Close an SDK context without masking the primary operation result."""

    if context is None:
        return
    try:
        context.close()
    except Exception:  # pragma: no cover - closing is best effort
        logger.debug("关闭 Futu OpenD 连接失败", exc_info=True)


def _connection_settings() -> tuple[str, int]:
    """Return the validated OpenD host and port from environment settings."""

    host = (os.getenv("FUTU_OPEND_HOST") or "127.0.0.1").strip()
    raw_port = (os.getenv("FUTU_OPEND_PORT") or "11111").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise FutuPortfolioError(f"FUTU_OPEND_PORT 不是有效端口: {raw_port!r}") from exc
    if not host or not 1 <= port <= 65535:
        raise FutuPortfolioError(f"Futu OpenD 地址无效: {host!r}:{port}")
    return host, port


def _configure_sdk_console_logging(api: _FutuApi) -> None:
    """Apply the process-wide Futu SDK console logging preference."""

    raw_value = (os.getenv("FUTU_SDK_CONSOLE_LOG_ENABLED") or "true").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        enabled = True
    elif raw_value in {"0", "false", "no", "off"}:
        enabled = False
    else:
        raise FutuPortfolioError(
            "FUTU_SDK_CONSOLE_LOG_ENABLED 必须是布尔值 "
            "（true/false、1/0、yes/no 或 on/off）"
        )
    api.SysConfig.enable_console_log(enabled)


def _configured_account_id() -> Optional[int]:
    """Return the optional configured real account ID."""

    value = (os.getenv("FUTU_ACC_ID") or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise FutuPortfolioError("FUTU_ACC_ID 必须是整数账户 ID") from exc


def _candidate_security_firms(api: _FutuApi) -> List[Any]:
    """Resolve configured or discoverable Futu security firms."""

    configured = (os.getenv("FUTU_SECURITY_FIRM") or "").strip().upper()
    names = (configured,) if configured else _SECURITY_FIRM_NAMES
    firms: List[Any] = []
    for name in names:
        firm = getattr(api.SecurityFirm, name, None)
        if firm is None:
            if configured:
                raise FutuPortfolioError(f"不支持的 FUTU_SECURITY_FIRM: {configured}")
            continue
        if firm not in firms:
            firms.append(firm)
    return firms


def _discover_real_accounts(api: _FutuApi, host: str, port: int) -> List[_FutuAccount]:
    """Discover enabled NORMAL or MASTER REAL accounts across candidate firms."""

    accounts: List[_FutuAccount] = []
    seen_ids = set()
    errors: List[str] = []

    for candidate_firm in _candidate_security_firms(api):
        context = None
        try:
            context = api.OpenSecTradeContext(
                host=host,
                port=port,
                filter_trdmarket=api.TrdMarket.NONE,
                security_firm=candidate_firm,
            )
            ret, data = context.get_acc_list()
            if ret != api.RET_OK:
                errors.append(str(data))
                continue
            for row in _iter_rows(data):
                if _enum_text(_row_value(row, "trd_env")) != "REAL":
                    continue
                if _enum_text(_row_value(row, "acc_status")) == "DISABLED":
                    continue
                if _enum_text(_row_value(row, "acc_role")) not in _SUPPORTED_ACCOUNT_ROLES:
                    continue
                try:
                    acc_id = int(_row_value(row, "acc_id"))
                except (TypeError, ValueError):
                    continue
                if acc_id in seen_ids:
                    continue
                returned_firm_name = _enum_text(_row_value(row, "security_firm"))
                returned_firm = getattr(
                    api.SecurityFirm,
                    returned_firm_name,
                    candidate_firm,
                )
                seen_ids.add(acc_id)
                accounts.append(_FutuAccount(acc_id=acc_id, security_firm=returned_firm))
        except Exception as exc:  # noqa: BLE001 - continue probing other supported firms
            errors.append(str(exc))
        finally:
            _safe_close(context)

    requested_acc_id = _configured_account_id()
    if requested_acc_id is not None:
        accounts = [account for account in accounts if account.acc_id == requested_acc_id]
        if not accounts:
            raise FutuPortfolioError(
                "FUTU_ACC_ID 未匹配到可用的真实证券账户；请检查账户 ID、券商和 OpenD 登录状态。"
            )

    if not accounts:
        detail = next((item for item in errors if item), "未返回账户数据")
        raise FutuPortfolioError(f"未找到可用的 Futu 真实证券账户: {detail}")
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
            for row in _iter_rows(data):
                try:
                    quantity = float(_row_value(row, "qty", 0) or 0)
                except (TypeError, ValueError):
                    quantity = 0
                code = str(_row_value(row, "code", "") or "").strip().upper()
                if quantity == 0 or not code:
                    continue
                position_side = _enum_text(_row_value(row, "position_side"))
                if position_side == "SHORT":
                    skipped_short_count += 1
                    continue
                if position_side != "LONG":
                    skipped_unknown_side_count += 1
                    continue
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


def _to_analysis_code(futu_code: str) -> Optional[str]:
    """Convert a supported Futu code into the analysis pipeline format."""

    prefix, separator, symbol = futu_code.partition(".")
    if not separator or not symbol:
        return None
    prefix = prefix.upper()
    symbol = symbol.upper()
    if prefix == "US":
        return symbol
    if prefix == "HK" and symbol.isdigit():
        return f"HK{symbol.zfill(5)}"
    if prefix in {"SH", "SZ"} and symbol.isdigit():
        return symbol
    if prefix == "JP" and symbol.isdigit():
        return f"{symbol}.T"
    return None


def _filter_stock_codes(
    api: _FutuApi,
    host: str,
    port: int,
    position_codes: List[str],
) -> List[str]:
    """Keep static-type stocks and convert them into analysis codes."""

    if not position_codes:
        return []

    grouped: dict[str, List[str]] = {}
    unsupported_count = 0
    for code in position_codes:
        prefix = _market_prefix(code)
        if prefix not in _SUPPORTED_ANALYSIS_MARKETS:
            unsupported_count += 1
            continue
        grouped.setdefault(prefix, []).append(code)

    stock_codes = set()
    classified_codes = set()
    context = None
    try:
        context = api.OpenQuoteContext(host=host, port=port)
        for prefix, codes in grouped.items():
            market = getattr(api.Market, prefix, None)
            if market is None:
                unsupported_count += len(codes)
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
                for row in _iter_rows(data):
                    code = str(_row_value(row, "code", "") or "").strip().upper()
                    if not code:
                        continue
                    classified_codes.add(code)
                    if _enum_text(_row_value(row, "stock_type")) == "STOCK":
                        stock_codes.add(code)
    except FutuPortfolioError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate SDK/network errors for CLI callers
        raise FutuPortfolioError(f"查询 Futu 持仓证券类型失败: {exc}") from exc
    finally:
        _safe_close(context)

    missing_count = sum(
        1 for codes in grouped.values() for code in codes if code not in classified_codes
    )
    if unsupported_count:
        logger.warning("已跳过 %d 个当前分析流程不支持的 Futu 市场持仓", unsupported_count)
    if missing_count:
        logger.warning("已跳过 %d 个无法确认证券类型的 Futu 持仓", missing_count)

    result: List[str] = []
    for futu_code in position_codes:
        if futu_code not in stock_codes:
            continue
        analysis_code = _to_analysis_code(futu_code)
        if analysis_code and analysis_code not in result:
            result.append(analysis_code)
    return result


def load_futu_stock_codes() -> List[str]:
    """Return deduplicated analysis codes from all selected REAL Futu accounts.

    Only Futu ``SecurityType.STOCK`` LONG positions with non-zero quantity are
    kept. ``FUTU_ACC_ID`` can select one account; otherwise all usable real
    securities NORMAL and read-only MASTER accounts are merged. The call is
    read-only and always refreshes position data.
    """
    api = _load_futu_api()
    _configure_sdk_console_logging(api)
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
