# -*- coding: utf-8 -*-
"""
自定义 Webhook 发送提醒服务

职责：
1. 发送自定义 Webhook 消息
"""
import logging
import json
import re
import time
from string import Template
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.config import Config
from src.formatters import strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)

# Bark 经 APNs 下发，APNs 普通通知的整个 payload 上限为 4096 字节
# （含 aps 结构、标题、分组、category 等开销）。正文按 JSON 编码后的
# UTF-8 字节数限制在该预算内，超限时 Bark 服务端会返回 HTTP 500
# (PayloadTooLarge)，手机收不到任何通知。
BARK_BODY_MAX_BYTES = 3000
BARK_TRUNCATION_SUFFIX = "..."

# Linear-time keyword matcher for quoted, arbitrarily nested escaped-JSON, and
# unquoted credential values; all boundary scanning runs in O(n) without regex
# quantifier backtracking.
_CREDENTIAL_KEY_RE = re.compile(
    r"(?i)(?:access_token|token|secret|password|sign|sendkey|api_key)"
)
_UNQUOTED_VALUE_STOP_CHARS = frozenset(" \t\r\n\f\v,;&\"')]}")


def _scan_credential_value_start(text: str, start: int) -> Tuple[Optional[int], int]:
    """Advance past optional escaped closing quote + '=' / ':' after a key name.

    Returns ``(val_start, next_pos)``. When the matched keyword is not followed
    by a key-value delimiter, ``val_start`` is ``None`` and ``next_pos`` skips
    past any scanned non-letter delimiter characters so callers stay O(n).
    """
    n = len(text)
    j = start
    bs_start = j
    while j < n and text[j] == "\\":
        j += 1
    if j < n and text[j] in ('"', "'"):
        j += 1
    elif j > bs_start:
        return None, j

    while j < n and text[j].isspace():
        j += 1
    if j >= n or text[j] not in ("=", ":"):
        return None, j
    j += 1
    while j < n and text[j].isspace():
        j += 1
    return j, j


def _find_nested_quoted_value_end(text: str, start: int, quote: str, bs_open: int) -> int:
    """Return index past closing quote for arbitrary json.dumps nesting depth.

    At JSON nesting depth ``d >= 0``, an opening/closing quote is preceded by
    ``2^d - 1`` backslashes (plus multiples of ``2^(d+1)`` for trailing literal
    backslashes), while an inner escaped quote is preceded by ``2^(d+1) - 1``
    (plus multiples of ``2^(d+1)``). Any quote whose ``(run + 1)`` is not
    divisible by ``stride = 2^d`` belongs to an outer JSON layer (e.g., when
    the inner value was truncated), so we stop right before the outer delimiter.
    """
    n = len(text)
    # Extract the trailing 1-bits of bs_open so valid depths (0, 1, 3, 7, 15, ...)
    # map to stride = 2^d, and malformed non-(2^d - 1) prefixes degrade safely.
    stride = (bs_open + 1) & -(bs_open + 1)
    period = 2 * stride
    i = start
    while i < n:
        ch = text[i]
        if ch == "\\":
            run = 0
            while i + run < n and text[i + run] == "\\":
                run += 1
            if i + run < n and text[i + run] == quote:
                r1 = run + 1
                rem = r1 % period
                if rem == stride:
                    return i + run + 1
                if rem != 0:
                    outer_bs = (r1 & -r1) - 1
                    return i + run - outer_bs
                i += run + 1
                continue
            i += run
            continue
        if ch == quote:
            if stride == 1:
                return i + 1
            return i
        i += 1
    return n


def redact_quoted_credentials(text: str) -> str:
    """Redact quoted and arbitrarily nested escaped-JSON credential values in O(n)."""
    if not text:
        return text
    n = len(text)
    pos = 0
    search_pos = 0
    parts: List[str] = []
    while search_pos < n:
        match = _CREDENTIAL_KEY_RE.search(text, search_pos)
        if match is None:
            parts.append(text[pos:])
            break
        val_start, next_pos = _scan_credential_value_start(text, match.end())
        if val_start is None:
            search_pos = max(match.end(), next_pos)
            continue
        if val_start >= n:
            parts.append(text[pos:])
            break
        bs_end = val_start
        while bs_end < n and text[bs_end] == "\\":
            bs_end += 1
        if bs_end < n and text[bs_end] in ('"', "'"):
            bs_open = bs_end - val_start
            end = _find_nested_quoted_value_end(text, bs_end + 1, text[bs_end], bs_open)
            parts.append(text[pos:val_start])
            parts.append("[REDACTED]")
            pos = end
            search_pos = end
        else:
            search_pos = max(val_start, bs_end)
    else:
        if pos < n:
            parts.append(text[pos:])
    return "".join(parts)


def redact_unquoted_credentials(text: str) -> str:
    """Redact unquoted credential values in O(n) while preserving existing ``[REDACTED]`` tokens."""
    if not text:
        return text
    n = len(text)
    pos = 0
    search_pos = 0
    parts: List[str] = []
    while search_pos < n:
        match = _CREDENTIAL_KEY_RE.search(text, search_pos)
        if match is None:
            parts.append(text[pos:])
            break
        val_start, next_pos = _scan_credential_value_start(text, match.end())
        if val_start is None:
            search_pos = max(match.end(), next_pos)
            continue
        if val_start >= n:
            parts.append(text[pos:])
            break
        if text.startswith("[REDACTED]", val_start) and (
            val_start + 10 == n or text[val_start + 10] in _UNQUOTED_VALUE_STOP_CHARS
        ):
            search_pos = val_start + 10
            continue
        end = val_start
        while end < n and text[end] not in _UNQUOTED_VALUE_STOP_CHARS:
            end += 1
        if end > val_start:
            parts.append(text[pos:val_start])
            parts.append("[REDACTED]")
            pos = end
            search_pos = end
        else:
            search_pos = val_start
    else:
        if pos < n:
            parts.append(text[pos:])
    return "".join(parts)


class CustomWebhookSender:

    def __init__(self, config: Config):
        """
        初始化自定义 Webhook 配置

        Args:
            config: 配置对象
        """
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        self._custom_webhook_bearer_token = getattr(config, 'custom_webhook_bearer_token', None)
        self._custom_webhook_body_template = getattr(config, 'custom_webhook_body_template', None)
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
 
    def send_to_custom(self, content: str) -> bool:
        """
        推送消息到自定义 Webhook
        
        支持任意接受 POST JSON 的 Webhook 端点
        默认发送格式：{"text": "消息内容", "content": "消息内容"}
        
        适用于：
        - 钉钉机器人
        - Discord Webhook
        - Slack Incoming Webhook
        - 自建通知服务
        - 其他支持 POST JSON 的服务
        
        Args:
            content: 消息内容（Markdown 格式）
            
        Returns:
            是否至少有一个 Webhook 发送成功
        """
        if not self._custom_webhook_urls:
            logger.warning("Custom Webhook not configured, skipping")
            return False
        
        success_count = 0
        
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # 通用 JSON 格式，兼容大多数 Webhook
                # 钉钉格式: {"msgtype": "text", "text": {"content": "xxx"}}
                # Slack 格式: {"text": "xxx"}
                # Discord 格式: {"content": "xxx"}
                
                # 钉钉机器人对 body 有字节上限（约 20000 bytes），超长需要分批发送
                if self._is_dingtalk_webhook(url):
                    templated_payload = self._build_custom_webhook_template_payload(content)
                    if templated_payload is not None:
                        sent_ok, allow_chunk_fallback, _ = self._post_custom_webhook_with_detail(
                            url, templated_payload, timeout=30
                        )
                        if sent_ok:
                            logger.info(f"Custom Webhook {i+1} (DingTalk template) sent successfully")
                            success_count += 1
                        elif allow_chunk_fallback and self._send_dingtalk_chunked(url, content, max_bytes=20000):
                            logger.info(
                                f"Custom Webhook {i+1} (DingTalk template failed, "
                                "chunked fallback) sent successfully"
                            )
                            success_count += 1
                        else:
                            logger.error(f"Custom Webhook {i+1} (DingTalk template) send failed")
                    elif self._send_dingtalk_chunked(url, content, max_bytes=20000):
                        logger.info(f"Custom Webhook {i+1} (DingTalk) sent successfully")
                        success_count += 1
                    else:
                        logger.error(f"Custom Webhook {i+1} (DingTalk) send failed")
                    continue

                # 其他 Webhook：单次发送
                payload = self._build_custom_webhook_payload(url, content)
                if self._post_custom_webhook(url, payload, timeout=30):
                    logger.info(f"Custom Webhook {i+1} sent successfully")
                    success_count += 1
                else:
                    logger.error(f"Custom Webhook {i+1} send failed")
                    
            except Exception as e:
                logger.error(f"Custom Webhook {i+1} send exception: {e}")
        
        logger.info(f"Custom Webhook dispatch completed: {success_count}/{len(self._custom_webhook_urls)} succeeded")
        return success_count > 0

    
    def _send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        """Send image to Custom Webhooks; Discord supports file attachment (Issue #289)."""
        if not self._custom_webhook_urls:
            return False
        success_count = 0
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                if self._is_discord_webhook(url):
                    files = {"file": ("report.png", image_bytes, "image/png")}
                    data = {"content": "📈 股票智能分析报告"}
                    headers = {"User-Agent": "StockAnalysis/1.0"}
                    if self._custom_webhook_bearer_token:
                        headers["Authorization"] = (
                            f"Bearer {self._custom_webhook_bearer_token}"
                        )
                    response = requests.post(
                        url, data=data, files=files, headers=headers, timeout=30,
                        verify=self._webhook_verify_ssl
                    )
                    if response.status_code in (200, 204):
                        logger.info("Custom Webhook %d (Discord image) sent successfully", i + 1)
                        success_count += 1
                    else:
                        logger.error(
                            "Custom Webhook %d (Discord image) send failed: HTTP %s",
                            i + 1, response.status_code,
                        )
                else:
                    if fallback_content:
                        payload = self._build_custom_webhook_payload(url, fallback_content)
                        if self._post_custom_webhook(url, payload, timeout=30):
                            logger.info(
                                "Custom Webhook %d (image unsupported, text fallback) sent successfully", i + 1
                            )
                            success_count += 1
                    else:
                        logger.warning(
                            "Custom Webhook %d does not support images and has no fallback content, skipping",
                            i + 1,
                        )
            except Exception as e:
                logger.error("Custom Webhook %d image send exception: %s", i + 1, e)
        return success_count > 0

    _DINGTALK_RATE_LIMIT_ERRCODES = frozenset({88, 130101, 410100})
    _DINGTALK_RETRYABLE_ERRCODES = frozenset({-1}) | _DINGTALK_RATE_LIMIT_ERRCODES
    _DINGTALK_OVERSIZE_ERRCODES = frozenset({400002})

    @staticmethod
    def _mask_url_for_log(raw_url: str) -> str:
        """Strip query secret values and userinfo from URLs before logging or returning diagnostics."""
        try:
            parsed = urlparse(raw_url)
        except ValueError:
            return "[REDACTED_URL]"
        if not parsed.scheme or not parsed.netloc:
            return "[REDACTED_URL]"
        host = parsed.netloc.rsplit("@", 1)[-1]
        safe_segments: List[str] = []
        for segment in parsed.path.split("/"):
            if not segment:
                safe_segments.append(segment)
                continue
            lower = segment.lower()
            if (
                len(segment) >= 16
                or lower.startswith("bot")
                or "token" in lower
                or "secret" in lower
            ):
                safe_segments.append("[REDACTED]")
            else:
                safe_segments.append(segment)
        query = ""
        if parsed.query:
            query = "&".join(
                f"{part.split('=', 1)[0]}=[REDACTED]" if "=" in part else "[REDACTED]"
                for part in parsed.query.split("&")
                if part
            )
        sanitized = f"{parsed.scheme}://{host}{'/'.join(safe_segments)}"
        return f"{sanitized}?{query}" if query else sanitized

    @classmethod
    def _sanitize_error_text(cls, text: Any, max_len: int = 200) -> str:
        """Redact URLs, tokens, and inline secrets from untrusted webhook response messages."""
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if not raw:
            return ""
        # Redact quoted/escaped-JSON credentials before URL masking so trailing `\"`
        # or `\\` after a URL inside a secret value is not split apart by URL rewriting.
        sanitized = redact_quoted_credentials(raw)
        sanitized = re.sub(
            r"(?i)(bearer\s+)(?:\"[^\"]*\"|'[^']*'|[a-z0-9._\-:+/=]+)",
            r"\1[REDACTED]",
            sanitized,
        )
        sanitized = redact_unquoted_credentials(sanitized)
        sanitized = re.sub(
            r"https?://[^\s\"'\\<>\)\],;]+",
            lambda match: cls._mask_url_for_log(match.group(0)),
            sanitized,
        )
        return sanitized[:max_len]

    @classmethod
    def _inspect_dingtalk_response(cls, url: str, response: Any) -> Optional[Dict[str, Any]]:
        """Inspect DingTalk JSON payloads on HTTP 2xx and classify retryability and chunk fallback."""
        if not cls._is_dingtalk_api_host(url):
            return None
        try:
            data = response.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        errcode = data.get("errcode")
        if errcode is None:
            return None
        if isinstance(errcode, bool):
            errcode_int = None
        else:
            try:
                errcode_int = int(errcode)
            except (TypeError, ValueError):
                errcode_int = None
        if errcode_int == 0 or str(errcode).strip() == "0":
            return None

        raw_errmsg = str(data.get("errmsg") or "unknown error")
        raw_lower = raw_errmsg.lower()
        rate_limited = (
            (errcode_int in cls._DINGTALK_RATE_LIMIT_ERRCODES)
            or any(token in raw_lower for token in ("rate limit", "too fast", "frequency", "频繁", "限流"))
        )
        retryable = rate_limited or (errcode_int in cls._DINGTALK_RETRYABLE_ERRCODES)
        allow_chunk_fallback = (
            not retryable
            and (
                (errcode_int in cls._DINGTALK_OVERSIZE_ERRCODES)
                or any(token in raw_lower for token in ("too long", "超长", "长度"))
                or ("size" in raw_lower and "exceed" in raw_lower)
            )
        )
        safe_errmsg = cls._sanitize_error_text(raw_errmsg) or "unknown error"
        return {
            "errcode": errcode,
            "summary": f"errcode={errcode} ({safe_errmsg})",
            "retryable": retryable,
            "rate_limited": rate_limited,
            "allow_chunk_fallback": allow_chunk_fallback,
        }

    @classmethod
    def _extract_dingtalk_error(cls, url: str, response: Any) -> Optional[str]:
        """Inspect DingTalk JSON payloads on HTTP 2xx so API-level errors fail closed."""
        info = cls._inspect_dingtalk_response(url, response)
        return info["summary"] if info is not None else None

    def _post_custom_webhook_with_detail(self, url: str, payload: dict, timeout: int = 30) -> Tuple[bool, bool, bool]:
        """Post one webhook payload and return ``(success, allow_chunk_fallback, rate_limited)``."""
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        # 支持 Bearer Token 认证（#51）
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        response = requests.post(url, data=body, headers=headers, timeout=timeout, verify=self._webhook_verify_ssl)
        if 200 <= response.status_code < 300:
            dingtalk_info = self._inspect_dingtalk_response(url, response)
            if dingtalk_info is not None:
                logger.error("Custom Webhook DingTalk API error: %s", dingtalk_info["summary"])
                return False, bool(dingtalk_info["allow_chunk_fallback"]), bool(dingtalk_info["rate_limited"])
            return True, False, False
        logger.error(f"Custom Webhook send failed: HTTP {response.status_code}")
        logger.debug("Response body: %s", self._sanitize_error_text(getattr(response, "text", "")))
        return False, response.status_code != 429, response.status_code == 429

    def _post_custom_webhook(self, url: str, payload: dict, timeout: int = 30) -> bool:
        ok, _, _ = self._post_custom_webhook_with_detail(url, payload, timeout=timeout)
        return ok

    def test_custom_webhooks(self, content: str, *, timeout_seconds: float = 20.0) -> List[Dict[str, Any]]:
        """Send a test message to each custom webhook and return raw per-URL attempts."""
        attempts: List[Dict[str, Any]] = []
        for index, url in enumerate(self._custom_webhook_urls):
            try:
                payload = self._build_custom_webhook_payload(url, content)
                attempts.append(
                    self._post_custom_webhook_attempt(
                        url=url,
                        payload=payload,
                        timeout_seconds=timeout_seconds,
                        index=index,
                    )
                )
            except Exception as exc:
                attempts.append({
                    "channel": "custom",
                    "success": False,
                    "message": f"自定义 Webhook {index + 1} 测试异常: {exc}",
                    "target": url,
                    "error_code": self._classify_custom_webhook_exception(exc)[0],
                    "stage": "notification_send",
                    "retryable": self._classify_custom_webhook_exception(exc)[1],
                    "latency_ms": None,
                    "http_status": None,
                })
        return attempts

    def _post_custom_webhook_attempt(
        self,
        *,
        url: str,
        payload: dict,
        timeout_seconds: float,
        index: int,
    ) -> Dict[str, Any]:
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'StockAnalysis/1.0',
        }
        if self._custom_webhook_bearer_token:
            headers['Authorization'] = f'Bearer {self._custom_webhook_bearer_token}'

        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        started_at = time.perf_counter()
        try:
            response = requests.post(
                url,
                data=body,
                headers=headers,
                timeout=timeout_seconds,
                verify=self._webhook_verify_ssl,
            )
        except Exception as exc:
            error_code, retryable = self._classify_custom_webhook_exception(exc)
            return {
                "channel": "custom",
                "success": False,
                "message": f"自定义 Webhook {index + 1} 测试失败: {exc}",
                "target": url,
                "error_code": error_code,
                "stage": "notification_send",
                "retryable": retryable,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "http_status": None,
            }

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        if 200 <= response.status_code < 300:
            dingtalk_info = self._inspect_dingtalk_response(url, response)
            if dingtalk_info is not None:
                return {
                    "channel": "custom",
                    "success": False,
                    "message": f"自定义 Webhook {index + 1} 测试失败: DingTalk {dingtalk_info['summary']}",
                    "target": url,
                    "error_code": "api_error",
                    "stage": "notification_send",
                    "retryable": bool(dingtalk_info["retryable"]),
                    "latency_ms": latency_ms,
                    "http_status": response.status_code,
                }
            return {
                "channel": "custom",
                "success": True,
                "message": f"自定义 Webhook {index + 1} 测试发送成功",
                "target": url,
                "error_code": None,
                "stage": "notification_send",
                "retryable": False,
                "latency_ms": latency_ms,
                "http_status": response.status_code,
            }

        retryable = response.status_code == 429 or response.status_code >= 500
        return {
            "channel": "custom",
            "success": False,
            "message": f"自定义 Webhook {index + 1} 测试失败: HTTP {response.status_code}",
            "target": url,
            "error_code": "http_error",
            "stage": "notification_send",
            "retryable": retryable,
            "latency_ms": latency_ms,
            "http_status": response.status_code,
        }

    @staticmethod
    def _classify_custom_webhook_exception(exc: Exception) -> Tuple[str, bool]:
        if isinstance(exc, requests.exceptions.Timeout):
            return "timeout", True
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "network_error", True
        if isinstance(exc, requests.exceptions.RequestException):
            return "network_error", True
        return "unexpected_error", False
    
    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        根据 URL 构建对应的 Webhook payload
        
        自动识别常见服务并使用对应格式
        """
        payload = self._build_custom_webhook_payload_untruncated(url, content)
        if self._is_bark_webhook(url) and isinstance(payload.get("body"), str):
            # 在模板渲染并解析之后再截断 Bark 的 body 字段，避免截断原始正文
            # 破坏模板中的 JSON 转义，同时覆盖全局模板与自动 payload 两条路径
            payload["body"] = self._truncate_bark_body(payload["body"])
        return payload

    def _build_custom_webhook_payload_untruncated(self, url: str, content: str) -> dict:
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        templated_payload = self._build_custom_webhook_template_payload(sanitized_content)
        if templated_payload is not None:
            return templated_payload

        url_lower = url.lower()
        
        # 钉钉机器人
        if self._is_dingtalk_webhook(url):
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析报告",
                    "text": sanitized_content
                }
            }
        
        # Discord Webhook
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            # Discord 限制 2000 字符
            truncated = (
                sanitized_content[:1900] + "..."
                if len(sanitized_content) > 1900
                else sanitized_content
            )
            return {
                "content": truncated
            }
        
        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": sanitized_content,
                "mrkdwn": True
            }
        
        # Bark (iOS 推送)，正文由调用方按 APNs payload 字节上限截断
        if self._is_bark_webhook(url):
            return {
                "title": "股票分析报告",
                "body": sanitized_content,
                "group": "stock"
            }
        
        # 通用格式（兼容大多数服务）
        return {
            "text": sanitized_content,
            "content": sanitized_content,
            "message": sanitized_content,
            "body": sanitized_content
        }

    def _build_custom_webhook_template_payload(self, content: str) -> Optional[dict]:
        """Build payload from CUSTOM_WEBHOOK_BODY_TEMPLATE when configured."""
        content = strip_hidden_markdown_metadata(content).strip()
        template = (self._custom_webhook_body_template or "").strip()
        if not template:
            return None

        title = "股票分析报告"
        variables = {
            "title": title,
            "title_json": json.dumps(title, ensure_ascii=False),
            "content": content,
            "content_json": json.dumps(content, ensure_ascii=False),
        }
        rendered = Template(template).safe_substitute(variables)
        try:
            payload: Any = json.loads(rendered)
        except json.JSONDecodeError as exc:
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE is not valid JSON, falling back to default Webhook payload: %s",
                exc,
            )
            return None
        if not isinstance(payload, dict):
            logger.error(
                "CUSTOM_WEBHOOK_BODY_TEMPLATE must render to a JSON object, falling back to default Webhook payload"
            )
            return None
        return payload
    
    @staticmethod
    def _build_dingtalk_markdown_payload(text: str) -> dict:
        return {
            "msgtype": "markdown",
            "markdown": {
                "title": "股票分析报告",
                "text": text,
            },
        }

    @classmethod
    def _dingtalk_payload_bytes(cls, text: str) -> int:
        payload = cls._build_dingtalk_markdown_payload(text)
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    @classmethod
    def _split_dingtalk_chunks(cls, content: str, max_bytes: int) -> List[str]:
        """Split content losslessly so every serialized DingTalk payload fits within ``max_bytes``."""
        if cls._dingtalk_payload_bytes(content) <= max_bytes:
            return [content]

        total_hint = 10
        for _ in range(4):
            marker_sample = f"\n\n📄 *({total_hint}/{total_hint})*"
            if cls._dingtalk_payload_bytes(marker_sample) >= max_bytes:
                return []

            chunks: List[str] = []
            remaining = content
            while remaining:
                if cls._dingtalk_payload_bytes(remaining[:1] + marker_sample) > max_bytes:
                    return []
                low = 1
                high = len(remaining)
                while low < high:
                    mid = (low + high + 1) // 2
                    if cls._dingtalk_payload_bytes(remaining[:mid] + marker_sample) <= max_bytes:
                        low = mid
                    else:
                        high = mid - 1
                split_at = low
                if split_at < len(remaining):
                    newline_pos = remaining.rfind("\n", max(0, split_at // 2), split_at)
                    if newline_pos >= 0:
                        split_at = newline_pos + 1
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]

            if len(chunks) <= total_hint:
                return chunks
            total_hint = max(len(chunks) * 2, int("9" * max(2, len(str(len(chunks))))))
        return []

    def _send_dingtalk_chunked(self, url: str, content: str, max_bytes: int = 20000) -> bool:
        import time as _time
        content = strip_hidden_markdown_metadata(content).strip()
        if not content:
            logger.warning("Custom Webhook DingTalk message content is empty, skipping")
            return False

        chunks = self._split_dingtalk_chunks(content, max_bytes)
        if not chunks:
            logger.error("Custom Webhook DingTalk content cannot fit within max_bytes=%d", max_bytes)
            return False

        total = len(chunks)
        ok = 0

        for idx, chunk in enumerate(chunks):
            marker = f"\n\n📄 *({idx+1}/{total})*" if total > 1 else ""
            payload = self._build_dingtalk_markdown_payload(chunk + marker)
            body_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if body_bytes > max_bytes:
                logger.error(
                    "DingTalk chunk %d/%d serialized size (%d) exceeded max_bytes=%d; aborting chunk send",
                    idx + 1,
                    total,
                    body_bytes,
                    max_bytes,
                )
                return False

            try:
                sent_ok, _allow_fallback, rate_limited = self._post_custom_webhook_with_detail(url, payload, timeout=30)
                if sent_ok:
                    ok += 1
                elif rate_limited:
                    logger.warning(
                        "DingTalk chunk %d/%d hit rate limit; aborting remaining chunks",
                        idx + 1,
                        total,
                    )
                    return False
                else:
                    logger.error(f"DingTalk chunked send failed: chunk {idx+1}/{total}")
            except Exception as exc:
                logger.error("DingTalk chunked send exception: chunk %d/%d: %s", idx + 1, total, exc)

            if idx < total - 1:
                _time.sleep(1)

        return ok == total

    @staticmethod
    def _is_dingtalk_api_host(url: str) -> bool:
        try:
            hostname = (urlparse((url or "").strip()).hostname or "").lower()
        except ValueError:
            return False
        return hostname in ("oapi.dingtalk.com", "dingtalk.com") or hostname.endswith(".dingtalk.com")

    @staticmethod
    def _is_dingtalk_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower

    @staticmethod
    def _is_bark_webhook(url: str) -> bool:
        # 按解析后的主机名识别，避免路径/查询参数中含 api.day.app 的非 Bark 地址被误判
        try:
            hostname = urlparse((url or "").strip()).hostname
        except ValueError:
            return False
        return hostname == "api.day.app"

    @staticmethod
    def _bark_encoded_bytes(text: str) -> int:
        """Estimate the bytes ``text`` occupies inside the APNs JSON payload.

        Bark server encodes the payload with Go's ``encoding/json``: non-ASCII
        stays raw UTF-8, control characters and quotes are escaped, and
        ``<`` / ``>`` / ``&`` become 6-byte ``\\u003c``-style escapes, and
        U+2028 / U+2029 become 6-byte ``\\u2028`` escapes (3 raw UTF-8 bytes
        in Python's output).
        """
        encoded = len(json.dumps(text, ensure_ascii=False).encode('utf-8')) - 2
        return (
            encoded
            + 5 * sum(text.count(ch) for ch in '<>&')
            + 3 * sum(text.count(ch) for ch in '\u2028\u2029')
        )

    @classmethod
    def _truncate_bark_body(cls, content: str, max_bytes: int = BARK_BODY_MAX_BYTES) -> str:
        """Truncate Bark body so the APNs payload stays under its 4096-byte limit."""
        if cls._bark_encoded_bytes(content) <= max_bytes:
            return content
        budget = max_bytes - cls._bark_encoded_bytes(BARK_TRUNCATION_SUFFIX)
        # 二分查找满足字节预算的最长字符前缀
        low, high = 0, len(content)
        while low < high:
            mid = (low + high + 1) // 2
            if cls._bark_encoded_bytes(content[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return content[:low].rstrip() + BARK_TRUNCATION_SUFFIX

    @staticmethod
    def _is_discord_webhook(url: str) -> bool:
        url_lower = (url or "").lower()
        return (
            'discord.com/api/webhooks' in url_lower
            or 'discordapp.com/api/webhooks' in url_lower
        )
