# -*- coding: utf-8 -*-
"""Read-only client for the IBKR Flex Web Service (version 3).

A Flex query is downloaded in two steps: ``SendRequest`` returns a reference
code, then ``GetStatement`` is polled until the statement is generated. The
token only grants access to pre-configured Flex reports; it cannot trade.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import requests

from src.brokers.errors import BrokerPortfolioError

logger = logging.getLogger(__name__)

FLEX_SEND_REQUEST_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
)
FLEX_GET_STATEMENT_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
)
FLEX_API_VERSION = "3"

# "Please try again shortly" codes from the Flex Web Service error table.
_RETRYABLE_ERROR_CODES = frozenset({"1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"})
_THROTTLED_ERROR_CODE = "1018"
_THROTTLED_DELAY_SECONDS = 10.0
_MAX_RETRY_DELAY_SECONDS = 10.0
_DATE_PATTERN = re.compile(r"^\d{8}$")


class IbkrPortfolioError(BrokerPortfolioError):
    """Raised when an IBKR Flex statement cannot be downloaded or parsed safely."""


def download_flex_statement(
    token: str,
    query_id: str,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    max_attempts: int = 8,
    timeout: float = 30.0,
    session: Optional[requests.Session] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """Download one Flex query result as raw ``FlexQueryResponse`` XML bytes.

    ``from_date``/``to_date`` (``yyyymmdd``) optionally override the query
    period; IBKR limits one request to 365 days. Errors never include the token.
    """
    token = (token or "").strip()
    query_id = (query_id or "").strip()
    if not token:
        raise IbkrPortfolioError("IBKR Flex token 未配置")
    if not query_id.isdigit():
        raise IbkrPortfolioError("IBKR Flex query id 必须是数字")
    if (from_date is None) != (to_date is None):
        raise IbkrPortfolioError("IBKR Flex 起止日期必须同时提供")
    for value in (from_date, to_date):
        if value is not None and not _DATE_PATTERN.match(value):
            raise IbkrPortfolioError(f"IBKR Flex 日期格式必须为 yyyymmdd: {value!r}")
    if max_attempts < 1:
        raise IbkrPortfolioError("max_attempts 必须 >= 1")

    http = session or requests.Session()
    params = {"t": token, "q": query_id, "v": FLEX_API_VERSION}
    if from_date is not None:
        params.update({"fd": from_date, "td": to_date})

    reference_code: Optional[str] = None
    for attempt in range(max_attempts):
        body = _get(http, FLEX_SEND_REQUEST_URL, params, timeout)
        status, payload = _parse_statement_response(body)
        if status == "ok":
            reference_code = payload
            break
        _raise_or_wait(status, payload, attempt, max_attempts, sleep)
    if reference_code is None:  # pragma: no cover - loop always breaks or raises
        raise IbkrPortfolioError("IBKR Flex 未返回 reference code")

    poll_params = {"t": token, "q": reference_code, "v": FLEX_API_VERSION}
    for attempt in range(max_attempts):
        sleep(min(2.0 + 2.0 * attempt, _MAX_RETRY_DELAY_SECONDS))
        body = _get(http, FLEX_GET_STATEMENT_URL, poll_params, timeout)
        if _root_tag(body) == "FlexQueryResponse":
            return body
        status, payload = _parse_statement_response(body)
        if status == "ok":
            raise IbkrPortfolioError("IBKR Flex GetStatement 返回了意外的响应")
        _raise_or_wait(status, payload, attempt, max_attempts, sleep, already_waited=True)
    raise IbkrPortfolioError(f"IBKR Flex 报表在 {max_attempts} 次轮询后仍未生成")


def _get(http: requests.Session, url: str, params: dict, timeout: float) -> bytes:
    try:
        response = http.get(
            url,
            params=params,
            headers={"User-Agent": "daily-stock-analysis-ibkr-flex"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # requests error messages embed the full URL including the token.
        raise IbkrPortfolioError(f"IBKR Flex 请求失败: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise IbkrPortfolioError(f"IBKR Flex 请求失败: HTTP {response.status_code}")
    return response.content


def _root_tag(body: bytes) -> Optional[str]:
    try:
        return ET.fromstring(body).tag
    except ET.ParseError:
        return None


def _parse_statement_response(body: bytes) -> tuple[str, str]:
    """Return ``("ok", reference)`` or ``(error_code, error_message)``."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise IbkrPortfolioError("IBKR Flex 返回了无法解析的 XML") from None
    if root.tag != "FlexStatementResponse":
        raise IbkrPortfolioError(f"IBKR Flex 返回了意外的 XML 根节点: {root.tag}")
    status = (root.findtext("Status") or "").strip()
    if status == "Success":
        reference = (root.findtext("ReferenceCode") or "").strip()
        if not reference:
            raise IbkrPortfolioError("IBKR Flex 未返回 reference code")
        return "ok", reference
    code = (root.findtext("ErrorCode") or "").strip() or "unknown"
    message = (root.findtext("ErrorMessage") or "").strip()
    return code, message


def _raise_or_wait(
    code: str,
    message: str,
    attempt: int,
    max_attempts: int,
    sleep: Callable[[float], None],
    *,
    already_waited: bool = False,
) -> None:
    retryable = code in _RETRYABLE_ERROR_CODES or code == _THROTTLED_ERROR_CODE
    if not retryable:
        raise IbkrPortfolioError(f"IBKR Flex 错误 {code}: {message}")
    if attempt + 1 >= max_attempts:
        raise IbkrPortfolioError(f"IBKR Flex 错误 {code} 重试 {max_attempts} 次后仍未恢复: {message}")
    logger.info("IBKR Flex 暂不可用（%s: %s），稍后重试", code, message)
    if code == _THROTTLED_ERROR_CODE:
        sleep(_THROTTLED_DELAY_SECONDS)
    elif not already_waited:
        sleep(min(2.0 + 2.0 * attempt, _MAX_RETRY_DELAY_SECONDS))
