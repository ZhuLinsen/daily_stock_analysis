# -*- coding: utf-8 -*-
"""
Telegram 发送提醒服务

职责：
1. 通过 Telegram Bot API 发送 文本消息
2. 通过 Telegram Bot API 发送 图片消息
"""
import logging
from typing import Optional
import requests
import time
import re

from src.config import Config
from src.formatters import (
    _custom_unit_to_index,
    escape_telegram_non_link_markdown_chars,
    strip_hidden_markdown_metadata,
    utf16_len,
)
from ._delivery_context import (
    is_at_most_once_delivery,
    is_delivery_ambiguous,
    is_valid_http_url,
    record_delivery_ambiguous,
    record_delivery_confirmed_absent,
    record_delivery_succeeded,
    validate_http_post_request,
)


logger = logging.getLogger(__name__)


class TelegramSender:

    def __init__(self, config: Config):
        """
        初始化 Telegram 配置

        Args:
            config: 配置对象
        """
        self._telegram_config = {
            'bot_token': getattr(config, 'telegram_bot_token', None),
            'chat_id': getattr(config, 'telegram_chat_id', None),
            'message_thread_id': getattr(config, 'telegram_message_thread_id', None),
        }

    def _is_telegram_configured(self) -> bool:
        """检查 Telegram 配置是否完整"""
        return bool(self._telegram_config['bot_token'] and self._telegram_config['chat_id'])

    def send_to_telegram(
        self,
        content: str,
        *,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 Telegram 机器人

        Telegram Bot API 格式：
        POST https://api.telegram.org/bot<token>/sendMessage
        {
            "chat_id": "xxx",
            "text": "消息内容",
            "parse_mode": "Markdown"
        }

        Args:
            content: 消息内容（Markdown 格式）

        Returns:
            是否发送成功
        """
        target_chat_id = chat_id if chat_id is not None else self._telegram_config.get("chat_id")
        target_message_thread_id = (
            message_thread_id
            if message_thread_id is not None
            else self._telegram_config.get("message_thread_id")
        )

        if not (self._telegram_config["bot_token"] and target_chat_id):
            logger.warning("Telegram configuration incomplete, skipping")
            record_delivery_confirmed_absent("invalid_config")
            return False

        bot_token = self._telegram_config['bot_token']
        chat_id = target_chat_id
        message_thread_id = target_message_thread_id

        try:
            # Telegram API 端点
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            if not is_valid_http_url(api_url):
                logger.error("Telegram API URL is invalid, cannot send")
                record_delivery_confirmed_absent("invalid_config")
                return False

            # Telegram 消息最大长度 4096（按 UTF-16 code unit 计）
            max_length = 4096

            sanitized_content = strip_hidden_markdown_metadata(content).strip()
            if not sanitized_content:
                logger.warning("Telegram message content is empty, skipping")
                record_delivery_confirmed_absent("invalid_content")
                return False

            telegram_content = self._convert_to_telegram_markdown(sanitized_content)

            if utf16_len(telegram_content) <= max_length:
                # 单条消息发送
                return self._send_telegram_message(
                    api_url,
                    chat_id,
                    sanitized_content,
                    message_thread_id,
                    timeout_seconds=timeout_seconds,
                )
            else:
                # 按 Markdown 转义后的最终 payload 分段，避免转义字符使请求超限
                return self._send_telegram_chunked(
                    api_url,
                    chat_id,
                    telegram_content,
                    max_length,
                    message_thread_id,
                    timeout_seconds=timeout_seconds,
                )

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            record_delivery_ambiguous("send_failed")
            return False

    def _send_telegram_message(
        self,
        api_url: str,
        chat_id: str,
        text: str,
        message_thread_id: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
        markdown_converted: bool = False,
    ) -> bool:
        """Send a single Telegram message with exponential backoff retry (Fixes #287)"""
        if not is_valid_http_url(api_url):
            logger.error("Telegram API URL is invalid, cannot send")
            record_delivery_confirmed_absent("invalid_config")
            return False

        # Convert Markdown to Telegram-compatible format
        telegram_text = text if markdown_converted else self._convert_to_telegram_markdown(text)

        payload = {
            "chat_id": chat_id,
            "text": telegram_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        if message_thread_id:
            payload['message_thread_id'] = message_thread_id

        if not validate_http_post_request(api_url, json=payload):
            logger.error("Telegram request preparation failed, cannot send")
            record_delivery_confirmed_absent("invalid_config")
            return False

        post_kwargs = {
            "json": payload,
            "timeout": timeout_seconds or 10,
        }
        if is_at_most_once_delivery():
            post_kwargs["allow_redirects"] = False

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(api_url, **post_kwargs)
            except requests.exceptions.ConnectTimeout as e:
                if attempt < max_retries:
                    delay = 2 ** attempt  # 2s, 4s
                    logger.warning(f"Telegram request failed (attempt {attempt}/{max_retries}): {e}, "
                                   f"retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                logger.error(f"Telegram request failed after {max_retries} attempts: {e}")
                record_delivery_confirmed_absent("connect_timeout")
                return False
            except requests.exceptions.RequestException as e:
                error_code = "read_timeout" if isinstance(e, requests.exceptions.Timeout) else "connection_error"
                record_delivery_ambiguous(error_code)
                if is_at_most_once_delivery():
                    logger.error(f"Telegram request failed in at-most-once mode ({error_code}): {e}")
                    return False
                if attempt < max_retries:
                    delay = 2 ** attempt  # 2s, 4s
                    logger.warning(f"Telegram request failed (attempt {attempt}/{max_retries}): {e}, "
                                   f"retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Telegram request failed after {max_retries} attempts: {e}")
                    return False

            if response.status_code == 200:
                try:
                    result = response.json()
                except ValueError:
                    logger.error("Telegram request failed: response is not valid JSON")
                    record_delivery_ambiguous("invalid_response")
                    return False
                if not isinstance(result, dict):
                    logger.error("Telegram request failed: response JSON is not an object")
                    record_delivery_ambiguous("invalid_response")
                    return False
                ok_val = result.get('ok')
                if ok_val is True:
                    logger.info("Telegram message sent successfully")
                    record_delivery_succeeded()
                    return True
                if ok_val is not False:
                    logger.error("Telegram request failed: missing or invalid 'ok' field in HTTP 200 response")
                    record_delivery_ambiguous("invalid_response")
                    return False

                error_desc = result.get('description', 'unknown error')
                logger.error(f"Telegram returned error: {error_desc}")

                # If Markdown parsing failed, fall back to plain text
                if self._should_fallback_to_plain_text(error_desc=error_desc):
                    if self._send_plain_text_fallback(api_url, payload, text, timeout_seconds=timeout_seconds):
                        return True

                record_delivery_confirmed_absent("telegram_api_rejected")
                return False
            elif response.status_code == 429:
                if attempt < max_retries:
                    retry_after = self._get_telegram_retry_after_seconds(response, attempt)
                    logger.warning(f"Telegram rate limited, retrying in {retry_after}s "
                                   f"(attempt {attempt}/{max_retries})...")
                    time.sleep(retry_after)
                    continue
                else:
                    logger.error(f"Telegram rate limited after {max_retries} attempts")
                    record_delivery_confirmed_absent("rate_limited")
                    return False
            else:
                if response.status_code >= 500:
                    record_delivery_ambiguous("http_5xx")
                    if is_at_most_once_delivery():
                        logger.error(f"Telegram request failed: HTTP {response.status_code}")
                        logger.error(f"Response body: {response.text}")
                        return False
                    if attempt < max_retries:
                        delay = 2 ** attempt
                        logger.warning(f"Telegram server error HTTP {response.status_code} "
                                       f"(attempt {attempt}/{max_retries}), retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    logger.error(f"Telegram request failed: HTTP {response.status_code}")
                    logger.error(f"Response body: {response.text}")
                    return False
                if 300 <= response.status_code < 400:
                    logger.error(f"Telegram request failed: HTTP {response.status_code}")
                    logger.error(f"Response body: {response.text}")
                    record_delivery_ambiguous("http_3xx")
                    return False
                if 400 <= response.status_code < 500 and self._should_fallback_to_plain_text(response_text=response.text):
                    if self._send_plain_text_fallback(api_url, payload, text, timeout_seconds=timeout_seconds):
                        return True
                logger.error(f"Telegram request failed: HTTP {response.status_code}")
                logger.error(f"Response body: {response.text}")
                if 400 <= response.status_code < 500:
                    record_delivery_confirmed_absent("http_4xx")
                else:
                    record_delivery_ambiguous("send_failed")
                return False

        return False

    @staticmethod
    def _get_telegram_retry_after_seconds(response: requests.Response, attempt: int) -> int:
        try:
            retry_after = response.json().get("parameters", {}).get("retry_after")
        except (AttributeError, ValueError):
            retry_after = None

        for value in (retry_after, response.headers.get("Retry-After")):
            try:
                delay = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if delay >= 0:
                return delay

        return 2 ** attempt

    @staticmethod
    def _should_fallback_to_plain_text(error_desc: str = "", response_text: str = "") -> bool:
        """Detect Telegram Markdown parsing failures that should retry as plain text."""
        haystack = f"{error_desc}\n{response_text}".lower()
        markers = (
            "can't parse entities",
            "can't parse entity",
            "can't find end of the entity",
            "parse entities",
            "parse_mode",
            "markdown",
        )
        return any(marker in haystack for marker in markers)

    def _send_plain_text_fallback(
        self,
        api_url: str,
        payload: dict,
        text: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Retry Telegram send without parse_mode when Markdown parsing fails."""
        if not is_valid_http_url(api_url):
            logger.error("Telegram API URL is invalid, cannot send plain-text fallback")
            record_delivery_confirmed_absent("invalid_config")
            return False

        logger.info("Telegram Markdown parsing failed, retrying in plain text...")
        plain_payload = dict(payload)
        plain_payload.pop('parse_mode', None)
        plain_payload['text'] = text

        if not validate_http_post_request(api_url, json=plain_payload):
            logger.error("Telegram plain-text request preparation failed, cannot send")
            record_delivery_confirmed_absent("invalid_config")
            return False

        post_kwargs = {
            "json": plain_payload,
            "timeout": timeout_seconds or 10,
        }
        if is_at_most_once_delivery():
            post_kwargs["allow_redirects"] = False

        try:
            response = requests.post(api_url, **post_kwargs)
        except requests.exceptions.ConnectTimeout as e:
            logger.error(f"Telegram plain-text fallback failed: {e}")
            record_delivery_confirmed_absent("connect_timeout")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram plain-text fallback failed: {e}")
            record_delivery_ambiguous("read_timeout" if isinstance(e, requests.exceptions.Timeout) else "connection_error")
            return False

        if response.status_code == 200:
            try:
                result = response.json()
            except ValueError:
                logger.error("Telegram plain-text fallback failed: response is not valid JSON")
                logger.error(f"Response body: {response.text}")
                record_delivery_ambiguous("invalid_response")
                return False
            if not isinstance(result, dict):
                logger.error("Telegram plain-text fallback failed: response JSON is not an object")
                record_delivery_ambiguous("invalid_response")
                return False

            ok_val = result.get('ok')
            if ok_val is True:
                logger.info("Telegram message sent successfully (plain text)")
                record_delivery_succeeded()
                return True
            if ok_val is not False:
                logger.error("Telegram plain-text fallback failed: missing or invalid 'ok' field in HTTP 200 response")
                logger.error(f"Response body: {response.text}")
                record_delivery_ambiguous("invalid_response")
                return False

            logger.error("Telegram plain-text fallback failed: Telegram API returned ok=false")
            logger.error(f"Response body: {response.text}")
            record_delivery_confirmed_absent("telegram_api_rejected")
            return False

        logger.error(f"Telegram plain-text fallback failed: HTTP {response.status_code}")
        logger.error(f"Response body: {response.text}")
        if 400 <= response.status_code < 500:
            record_delivery_confirmed_absent("rate_limited" if response.status_code == 429 else "http_4xx")
        elif 300 <= response.status_code < 400:
            record_delivery_ambiguous("http_3xx")
        else:
            record_delivery_ambiguous("http_5xx" if response.status_code >= 500 else "send_failed")
        return False

    def _send_telegram_chunked(
        self,
        api_url: str,
        chat_id: str,
        content: str,
        max_length: int,
        message_thread_id: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """按已转换的 Telegram Markdown payload 分段发送长消息。"""
        # 按段落分割
        sections = content.split("\n---\n")
        delimiter = "\n---\n"
        delimiter_length = len(delimiter)

        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1

        def _flush_chunk() -> bool:
            nonlocal current_chunk, current_length, chunk_index, all_success
            if not current_chunk:
                return all_success

            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"Sending Telegram message chunk {chunk_index}...")
            chunk_index += 1
            current_chunk = []
            current_length = 0
            if not self._send_telegram_message(
                api_url,
                chat_id,
                chunk_content,
                message_thread_id,
                timeout_seconds=timeout_seconds,
                markdown_converted=True,
            ):
                all_success = False
            return all_success

        def _split_long_section(section: str, limit: int) -> list[str]:
            chunks: list[str] = []
            while utf16_len(section) > limit:
                cut = max(1, _custom_unit_to_index(section, limit, utf16_len))
                chunks.append(section[:cut])
                section = section[cut:]
            chunks.append(section)
            return chunks

        for section in sections:
            if is_at_most_once_delivery() and is_delivery_ambiguous():
                return False
            if utf16_len(section) > max_length:
                # 单段超限时强制切片，避免依赖“\\n---\\n”边界导致的整段超长发送
                if not _flush_chunk():
                    return False
                if is_at_most_once_delivery() and is_delivery_ambiguous():
                    return False
                for long_chunk in _split_long_section(section, max_length):
                    logger.info(f"Sending Telegram message chunk {chunk_index}...")
                    chunk_index += 1
                    if not self._send_telegram_message(
                        api_url,
                        chat_id,
                        long_chunk,
                        message_thread_id,
                        timeout_seconds=timeout_seconds,
                        markdown_converted=True,
                    ):
                        all_success = False
                        if is_at_most_once_delivery() and is_delivery_ambiguous():
                            return False
                continue

            additional_length = utf16_len(section)
            if current_chunk:
                additional_length += delimiter_length

            if current_length + additional_length > max_length:
                _flush_chunk()
                if is_at_most_once_delivery() and is_delivery_ambiguous():
                    return False
                current_chunk = [section]
                current_length = utf16_len(section)
                continue

            current_chunk.append(section)
            current_length += additional_length

        # 发送最后一块
        if not _flush_chunk():
            return False

        return all_success

    def _send_telegram_photo(self, image_bytes: bytes) -> bool:
        """Send image via Telegram sendPhoto API (Issue #289)."""
        if not self._is_telegram_configured():
            record_delivery_confirmed_absent("invalid_config")
            return False
        bot_token = self._telegram_config['bot_token']
        chat_id = self._telegram_config['chat_id']
        message_thread_id = self._telegram_config.get('message_thread_id')
        api_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        if not is_valid_http_url(api_url):
            logger.error("Telegram photo API URL is invalid, cannot send")
            record_delivery_confirmed_absent("invalid_config")
            return False
        try:
            data = {"chat_id": chat_id}
            if message_thread_id:
                data['message_thread_id'] = message_thread_id
            files = {"photo": ("report.png", image_bytes, "image/png")}
            if not validate_http_post_request(api_url, data=data, files=files):
                logger.error("Telegram photo request preparation failed, cannot send")
                record_delivery_confirmed_absent("invalid_config")
                return False
            post_kwargs = {
                "data": data,
                "files": files,
                "timeout": 30,
            }
            if is_at_most_once_delivery():
                post_kwargs["allow_redirects"] = False
            response = requests.post(api_url, **post_kwargs)
            if response.status_code == 200:
                try:
                    result = response.json()
                except ValueError:
                    logger.error("Telegram image send failed: response is not valid JSON")
                    record_delivery_ambiguous("invalid_response")
                    return False
                if not isinstance(result, dict):
                    logger.error("Telegram image send failed: response JSON is not an object")
                    record_delivery_ambiguous("invalid_response")
                    return False
                ok_val = result.get('ok')
                if ok_val is True:
                    logger.info("Telegram image sent successfully")
                    record_delivery_succeeded()
                    return True
                if ok_val is not False:
                    logger.error("Telegram image send failed: missing or invalid 'ok' field in HTTP 200 response")
                    record_delivery_ambiguous("invalid_response")
                    return False
                logger.error("Telegram image send failed: %s", response.text[:200])
                record_delivery_confirmed_absent("telegram_api_rejected")
                return False
            logger.error("Telegram image send failed: %s", response.text[:200])
            if 400 <= response.status_code < 500:
                record_delivery_confirmed_absent("rate_limited" if response.status_code == 429 else "http_4xx")
            elif 300 <= response.status_code < 400:
                record_delivery_ambiguous("http_3xx")
            else:
                record_delivery_ambiguous("http_5xx" if response.status_code >= 500 else "send_failed")
            return False
        except requests.exceptions.ConnectTimeout as e:
            logger.error("Telegram image send connect timeout: %s", e)
            record_delivery_confirmed_absent("connect_timeout")
            return False
        except Exception as e:
            logger.error("Telegram image send exception: %s", e)
            record_delivery_ambiguous("read_timeout" if isinstance(e, requests.exceptions.Timeout) else "send_failed")
            return False

    def _convert_to_telegram_markdown(self, text: str) -> str:
        """
        将标准 Markdown 转换为 Telegram 支持的格式

        Telegram Markdown 限制：
        - 不支持 # 标题
        - 使用 *bold* 而非 **bold**
        - 使用 _italic_
        """
        result = strip_hidden_markdown_metadata(text)

        # 移除 # 标题标记（Telegram 不支持）
        result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)

        # 转换 **bold** 为 *bold*
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result)

        return escape_telegram_non_link_markdown_chars(result)
