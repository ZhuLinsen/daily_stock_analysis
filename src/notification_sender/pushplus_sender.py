# -*- coding: utf-8 -*-
"""
PushPlus 发送提醒服务

职责：
1. 通过 PushPlus API 发送 PushPlus 消息
"""
import logging
import time
from typing import Any, Optional
from datetime import datetime
import requests

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)


class PushplusSender:
    
    def __init__(self, config: Config):
        """
        初始化 PushPlus 配置

        Args:
            config: 配置对象
        """
        self._pushplus_token = getattr(config, 'pushplus_token', None)
        self._pushplus_topic = getattr(config, 'pushplus_topic', None)
        self._pushplus_max_bytes = self._normalize_max_bytes(
            getattr(config, 'pushplus_max_bytes', 20000)
        )

    @staticmethod
    def _normalize_max_bytes(value: Any, default: int = 20000) -> int:
        if isinstance(value, bool):
            return default
        try:
            configured = int(value)
        except (TypeError, ValueError):
            configured = default
        return max(2500, configured)
        
    def send_to_pushplus(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 PushPlus

        PushPlus API 格式：
        POST http://www.pushplus.plus/send
        {
            "token": "用户令牌",
            "title": "消息标题",
            "content": "消息内容",
            "template": "html/txt/json/markdown"
        }

        PushPlus 特点：
        - 国内推送服务，免费额度充足
        - 支持微信公众号推送
        - 支持多种消息格式

        Args:
            content: 消息内容（Markdown 格式）
            title: 消息标题（可选）

        Returns:
            是否发送成功
        """
        if not self._pushplus_token:
            logger.warning("PushPlus Token not configured, skipping notification")
            return False

        api_url = "http://www.pushplus.plus/send"

        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("PushPlus message content is empty, skipping notification")
            return False

        try:
            content_bytes = len(sanitized_content.encode('utf-8'))
            if content_bytes > self._pushplus_max_bytes:
                logger.info(
                    "PushPlus message exceeds limit (%s bytes/%s chars), sending in chunks",
                    content_bytes,
                    len(sanitized_content),
                )
                return self._send_pushplus_chunked(
                    api_url,
                    sanitized_content,
                    title,
                    self._pushplus_max_bytes,
                    timeout_seconds=timeout_seconds,
                )

            return self._send_pushplus_message(
                api_url,
                sanitized_content,
                title,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            logger.error(f"Failed to send PushPlus message: {e}")
            return False

    def _send_pushplus_message(
        self,
        api_url: str,
        content: str,
        title: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        payload = {
            "token": self._pushplus_token,
            "title": title,
            "content": content,
            "template": "markdown",
        }

        if self._pushplus_topic:
            payload["topic"] = self._pushplus_topic

        try:
            response = requests.post(api_url, json=payload, timeout=timeout_seconds or 10)

            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict) and result.get('code') == 200:
                    logger.info("PushPlus message sent successfully")
                    return True

                error_msg = result.get('msg', 'unknown error') if isinstance(result, dict) else 'invalid JSON response'
                logger.error(f"PushPlus returned error: {error_msg}")
                return False

            logger.error(f"PushPlus request failed: HTTP {response.status_code}")
            return False
        except Exception as e:
            logger.error("Failed to send PushPlus message: %s", e)
            return False

    def _send_pushplus_chunked(
        self,
        api_url: str,
        content: str,
        title: str,
        max_bytes: int,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """分批发送长 PushPlus 消息，给 JSON payload 预留空间。"""
        budget = max(1000, max_bytes - 1500)
        chunks = chunk_content_by_max_bytes(content, budget, add_page_marker=True)
        if not chunks:
            return False
        total_chunks = len(chunks)
        success_count = 0

        logger.info(f"PushPlus sending in {total_chunks} chunks")

        for i, chunk in enumerate(chunks):
            chunk_title = f"{title} ({i+1}/{total_chunks})" if total_chunks > 1 else title
            if self._send_pushplus_message(
                api_url,
                chunk,
                chunk_title,
                timeout_seconds=timeout_seconds,
            ):
                success_count += 1
                logger.info(f"PushPlus chunk {i+1}/{total_chunks} sent successfully")
            else:
                logger.error(f"PushPlus chunk {i+1}/{total_chunks} send failed")

            if i < total_chunks - 1:
                time.sleep(1)

        return success_count == total_chunks
