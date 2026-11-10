# -*- coding: utf-8 -*-
"""ntfy notification sender."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse, urlunparse

import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata
from src.report_language import get_report_labels


logger = logging.getLogger(__name__)

# ntfy.sh caps the message body at 4096 bytes; keep headroom for page markers.
NTFY_SAFE_MAX_BYTES = 3800
NTFY_CHUNK_INTERVAL_SECONDS = 0.5


def resolve_ntfy_endpoint(ntfy_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split NTFY_URL into server root and topic from the final path segment."""
    raw_url = (ntfy_url or "").strip().rstrip("/")
    if not raw_url:
        return None, None

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, None

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        return None, None

    topic = unquote(path_segments[-1]).strip()
    if not topic:
        return None, None

    root_path = "/".join(path_segments[:-1])
    server_url = urlunparse(
        parsed._replace(
            path=f"/{root_path}" if root_path else "",
            params="",
            query="",
            fragment="",
        )
    ).rstrip("/")

    return server_url, topic


class NtfySender:
    """Send Markdown text notifications through the ntfy JSON publish API."""

    def __init__(self, config: Config):
        self._ntfy_url = getattr(config, "ntfy_url", None)
        self._ntfy_token = getattr(config, "ntfy_token", None)
        self._webhook_verify_ssl = getattr(config, "webhook_verify_ssl", True)
        self._report_language = getattr(config, "report_language", "zh") or "zh"

    def _is_ntfy_configured(self) -> bool:
        return bool(self._ntfy_url)

    def _resolve_ntfy_endpoint(self) -> Tuple[Optional[str], Optional[str]]:
        return resolve_ntfy_endpoint(self._ntfy_url)

    def send_to_ntfy(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Publish a notification to ntfy using a JSON body with UTF-8 text."""
        if not self._is_ntfy_configured():
            logger.warning("ntfy URL 未配置，跳过推送")
            return False

        server_url, topic = self._resolve_ntfy_endpoint()
        if not server_url or not topic:
            logger.error("NTFY_URL 必须是包含 topic path 的完整 endpoint，例如 https://ntfy.sh/my-topic")
            return False

        if title is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            report_title = get_report_labels(self._report_language).get("report_title", "股票分析报告")
            title = f"📈 {report_title} - {date_str}"
        sanitized_content = strip_hidden_markdown_metadata(content).strip()

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "daily_stock_analysis",
        }
        token = (self._ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # ntfy.sh rejects message bodies over 4096 bytes with HTTP 413, so long
        # reports are split into ordered parts, keeping headed sections intact.
        chunks = chunk_content_by_max_bytes(sanitized_content, max_bytes=NTFY_SAFE_MAX_BYTES)
        all_success = True
        for index, chunk in enumerate(chunks):
            chunk_title = title if len(chunks) == 1 else f"{title} ({index + 1}/{len(chunks)})"
            payload = {
                "topic": topic,
                "title": chunk_title,
                "message": chunk,
                "markdown": True,
            }
            if not self._post_payload(server_url, payload, headers, timeout_seconds):
                all_success = False
            if index < len(chunks) - 1:
                time.sleep(NTFY_CHUNK_INTERVAL_SECONDS)
        return all_success

    def _post_payload(
        self,
        server_url: str,
        payload: dict,
        headers: dict,
        timeout_seconds: Optional[float],
    ) -> bool:
        try:
            response = requests.post(
                server_url,
                json=payload,
                headers=headers,
                timeout=timeout_seconds or 10,
                verify=self._webhook_verify_ssl,
            )
            if 200 <= response.status_code < 300:
                logger.info("ntfy 消息发送成功")
                return True

            logger.error("ntfy 请求失败: HTTP %s", response.status_code)
            logger.debug("ntfy 响应内容: %s", response.text)
            return False
        except requests.exceptions.Timeout:
            logger.error("发送 ntfy 消息失败: 请求超时")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("发送 ntfy 消息失败: 网络请求异常")
            logger.debug("ntfy 请求异常类型: %s", type(exc).__name__)
            return False
        except Exception as exc:
            logger.error("发送 ntfy 消息失败: 未知异常")
            logger.debug("ntfy 未知异常类型: %s", type(exc).__name__)
            return False
